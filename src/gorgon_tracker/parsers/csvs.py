"""CSV readers for legacy capture outputs (zones.csv, targets.csv, loot.csv)."""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

from ..correlator import TargetSighting, ZoneChange
from ..timeutil import iso_to_ms


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def cell(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return "Unknown"


def read_zone_changes(path: Path) -> list[ZoneChange]:
    changes = []
    for row in _rows(path):
        time_ms = iso_to_ms(cell(row, "Time", "time"), assume_utc=True)
        changes.append(ZoneChange(time_ms=time_ms, zone=cell(row, "Text", "Zone", "zone").strip()))
    return sorted(changes, key=lambda c: c.time_ms)


def read_target_sightings(path: Path) -> list[TargetSighting]:
    sightings = []
    for row in _rows(path):
        time_ms = iso_to_ms(cell(row, "Time", "time"), assume_utc=True)
        sightings.append(TargetSighting(time_ms=time_ms, name=cell(row, "Text", "Target", "target").strip()))
    return sorted(sightings, key=lambda s: s.time_ms)


def _lag_ms(value: str) -> int:
    try:
        lag = float(value) * 1000
    except (TypeError, ValueError):
        return 0
    return round(lag) if math.isfinite(lag) else 0


def read_legacy_loot_csv(path: Path) -> list[dict[str, Any]]:
    """Read a legacy CompileLootEvents loot.csv into normalized row dicts."""
    rows: list[dict[str, Any]] = []
    for row in _rows(path):
        rows.append(
            {
                "time_ms": iso_to_ms(cell(row, "Time", "time")),
                "source": cell(row, "Source"),
                "encounter_uuid": cell(row, "ID"),
                "activity": cell(row, "Activity"),
                "item": cell(row, "Item"),
                "amount": int(cell(row, "Amount", "amount") or "1"),
                "status": cell(row, "Status"),
                "lag_ms": _lag_ms(cell(row, "LagTime", "Lag") or "0"),
                "zone": cell(row, "Zone"),
            }
        )
    return sorted(rows, key=lambda r: r["time_ms"])