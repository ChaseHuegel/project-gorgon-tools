"""Backwards-compatible CSV export of correlated loot."""

from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, TextIO

_HEADER = ["Time", "Source", "ID", "Activity", "Item", "Amount", "Status", "LagTime", "Zone"]
_EVIDENCE_HEADER = [
    "LinkedVia",
    "MonsterName",
    "MonsterLagMs",
    "TargetName",
    "TargetLagMs",
    "CorroboratedBySearch",
    "Missed",
    "InstanceId",
    "EntityId",
    "ItemCodeId",
    "KillerJson",
]

_SQL = """
SELECT ld.captured_at,
       COALESCE(ov.source, ld.source) AS source,
       e.encounter_uuid,
       COALESCE(ov.activity, ld.activity) AS activity,
       ld.item,
       ld.amount,
       COALESCE(ov.status, ld.status) AS status,
       ld.lag_ms,
       ld.zone,
       ld.linked_via,
       ld.monster_name,
       ld.monster_lag_ms,
       ld.target_name,
       ld.target_lag_ms,
       ld.corroborated_by_search,
       COALESCE(ld.missed, 0),
       ld.instance_id,
       ld.entity_id,
       ld.item_code_id,
       ld.killer_json
FROM loot_drops ld
LEFT JOIN encounters e ON e.id = ld.encounter_id
LEFT JOIN loot_overrides ov ON ov.loot_drop_id = ld.id
WHERE (? IS NULL OR ld.captured_at >= ?)
ORDER BY ld.captured_at
"""


def _local_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def export_loot_csv(
    conn: sqlite3.Connection,
    out: TextIO,
    since_ms: int | None = None,
    with_evidence: bool = False,
) -> int:
    """Write correlated drops to ``out`` in the legacy loot.csv format.

    Manual overrides (``loot_overrides``) are applied to Source/Activity/Status.
    ``with_evidence`` appends the attribution audit columns after Zone.
    """
    header = _HEADER + (_EVIDENCE_HEADER if with_evidence else [])
    rows = conn.execute(_SQL, (since_ms, since_ms)).fetchall()
    writer = csv.DictWriter(out, fieldnames=header)
    writer.writeheader()
    for row in rows:
        entry = {
            "Time": _local_time(row["captured_at"]),
            "Source": row["source"],
            "ID": row["encounter_uuid"],
            "Activity": row["activity"],
            "Item": row["item"],
            "Amount": row["amount"],
            "Status": row["status"],
            "LagTime": f"{row['lag_ms'] / 1000:.2f}",
            "Zone": row["zone"],
        }
        if with_evidence:
            entry.update(
                {
                    "LinkedVia": row["linked_via"],
                    "MonsterName": row["monster_name"] or "",
                    "MonsterLagMs": row["monster_lag_ms"] or "",
                    "TargetName": row["target_name"] or "",
                    "TargetLagMs": row["target_lag_ms"] or "",
                    "CorroboratedBySearch": bool(row["corroborated_by_search"]),
                    "Missed": bool(row["missed"]),
                    "InstanceId": row["instance_id"] or "",
                    "EntityId": row["entity_id"] or "",
                    "ItemCodeId": row["item_code_id"] or "",
                    "KillerJson": row["killer_json"] or "",
                }
            )
        writer.writerow(entry)
    return len(rows)


def export_loot_csv_text(
    conn: sqlite3.Connection,
    since_ms: int | None = None,
    with_evidence: bool = False,
) -> str:
    buffer = io.StringIO()
    export_loot_csv(conn, buffer, since_ms, with_evidence=with_evidence)
    return buffer.getvalue()


_ANALYSIS_HEADER = ["Monster", "Item", "Drops", "Quantity", "Encounters", "DropRate", "LastSeen"]


def export_analysis_rows_text(rows: Sequence[Mapping[str, Any]]) -> str:
    """Write pre-aggregated drop-rate rows (from ``serve._drop_rates``) as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_ANALYSIS_HEADER)
    for row in rows:
        writer.writerow(
            [
                row.get("monster", ""),
                row.get("item", ""),
                row.get("drops", ""),
                row.get("quantity", ""),
                row.get("encounters", ""),
                f"{row.get('drop_rate', 0) * 100:.2f}%" if row.get("drop_rate") is not None else "",
                _local_time(int(row["last_seen"])) if row.get("last_seen") else "",
            ]
        )
    return buffer.getvalue()