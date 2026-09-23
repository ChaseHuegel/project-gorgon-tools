"""Backwards-compatible CSV export of correlated loot."""

from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime
from typing import TextIO

_HEADER = ["Time", "Source", "ID", "Activity", "Item", "Amount", "Status", "LagTime", "Zone"]

_SQL = """
SELECT ld.captured_at,
       ld.source,
       e.encounter_uuid,
       ld.activity,
       ld.item,
       ld.amount,
       ld.status,
       ld.lag_ms,
       ld.zone
FROM loot_drops ld
LEFT JOIN encounters e ON e.id = ld.encounter_id
WHERE (? IS NULL OR ld.captured_at >= ?)
ORDER BY ld.captured_at
"""


def _local_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def export_loot_csv(conn: sqlite3.Connection, out: TextIO, since_ms: int | None = None) -> int:
    """Write correlated drops to ``out`` in the legacy loot.csv format."""
    rows = conn.execute(_SQL, (since_ms, since_ms)).fetchall()
    writer = csv.DictWriter(out, fieldnames=_HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
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
        )
    return len(rows)


def export_loot_csv_text(conn: sqlite3.Connection, since_ms: int | None = None) -> str:
    buffer = io.StringIO()
    export_loot_csv(conn, buffer, since_ms)
    return buffer.getvalue()