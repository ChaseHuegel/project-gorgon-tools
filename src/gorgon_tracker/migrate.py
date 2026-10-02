"""Import legacy PowerShell outputs (CSV/JSON) as historical DB sessions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import db
from .config import TrackerConfig
from .correlator import BuryEvent, LootDrop, LootEvent, SourceEvent
from .ingest import DbWriter
from .parsers import csvs as csv_parser
from .timeutil import iso_to_ms


def _kind_of(path: Path) -> str:
    name = path.name.lower()
    if "zone" in name:
        return "zones"
    if "target" in name:
        return "targets"
    if "parsed-chat" in name or "chat" in name:
        return "chat-json"
    if "parsed-packet" in name or "packet" in name:
        return "packets-json"
    return "loot"


def import_file(
    conn: sqlite3.Connection,
    session_id: int,
    path: Path,
    kind: str | None = None,
) -> tuple[str, int]:
    """Import one legacy file; returns (kind, imported_rows)."""
    kind = kind or _kind_of(path)
    writer = DbWriter(conn, session_id)
    count = 0

    if kind == "zones":
        for change in csv_parser.read_zone_changes(path):
            writer.zone(change)
            count += 1
    elif kind == "targets":
        for sighting in csv_parser.read_target_sightings(path):
            writer.target(sighting)
            count += 1
    elif kind == "loot":
        for row in csv_parser.read_legacy_loot_csv(path):
            writer.drop(
                LootDrop(
                    time_ms=row["time_ms"],
                    source=row["source"],
                    encounter_uuid=row["encounter_uuid"],
                    activity=row["activity"],
                    item=row["item"],
                    amount=row["amount"],
                    status=row["status"],
                    lag_ms=row["lag_ms"],
                    zone=row["zone"],
                )
            )
            writer.loot(
                LootEvent(time_ms=row["time_ms"], item=row["item"], amount=row["amount"])
            )
            count += 1
    elif kind == "chat-json":
        doc = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        for entry in doc:
            time_ms = _entry_time_ms(entry)
            if entry.get("EventType") == "Bury":
                writer.bury(BuryEvent(time_ms=time_ms))
            else:
                writer.loot(
                    LootEvent(
                        time_ms=time_ms,
                        item=entry.get("ItemName", "").strip(),
                        amount=int(entry.get("Amount") or 1),
                    )
                )
            count += 1
    elif kind == "packets-json":
        doc = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
        for entry in doc:
            writer.source(
                SourceEvent(
                    time_ms=_entry_time_ms(entry),
                    monster=entry.get("Monster", ""),
                    can_skin=_flag(entry.get("CanSkin")),
                    can_butcher=_flag(entry.get("CanButcher")),
                    can_extract=_flag(entry.get("CanExtract")),
                )
            )
            count += 1
    else:
        raise ValueError(f"cannot determine type of {path}")

    writer.close_encounters()
    writer.commit()
    return kind, count


def _flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes")


def _entry_time_ms(entry: dict[str, Any]) -> int:
    value = entry.get("Time")
    if isinstance(value, (int, float)):
        return round(float(value))
    return iso_to_ms(str(value))


def import_bundle(
    conn: sqlite3.Connection,
    cfg: TrackerConfig,
    path: Path,
    kind: str | None = None,
    platform: str = "linux",
) -> dict[str, Any]:
    """Import legacy CSV/JSON output files into a fresh historical session."""
    if not path.exists():
        raise FileNotFoundError(f"migrate input not found: {path}")
    session_id = db.new_session(conn, platform, cfg.model_dump())
    if kind is None:
        kind = _kind_of(path)
    imported = import_file(conn, session_id, path, kind)
    return {"session_id": session_id, "kind": imported[0], "imported": imported[1]}