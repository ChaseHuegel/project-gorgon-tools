"""SQLite bootstrap, migrations, and session/insert helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from importlib.resources import files
from pathlib import Path
from typing import Any

from .timeutil import utc_now_ms

_SCHEMA_SQL = files("gorgon_tracker").joinpath("schema.sql").read_text(encoding="utf-8")

MIGRATIONS: list[tuple[int, str]] = [(1, _SCHEMA_SQL)]

COUNT_TABLES = (
    "raw_events",
    "sources",
    "loot",
    "burials",
    "target_sightings",
    "zone_changes",
    "encounters",
    "loot_drops",
)


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY,"
        "applied_at INTEGER NOT NULL"
        ")"
    )
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for version, ddl in MIGRATIONS:
        if version <= current:
            continue
        conn.executescript(ddl)
        with conn:
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, utc_now_ms()),
            )
            conn.execute(f"PRAGMA user_version = {int(version)}")


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _last_id(cursor: sqlite3.Cursor) -> int:
    if cursor.lastrowid is None:
        raise RuntimeError("insert did not return a row id")
    return int(cursor.lastrowid)


def new_session(
    conn: sqlite3.Connection, platform: str = "linux", config_snapshot: dict[str, Any] | None = None
) -> int:
    now = utc_now_ms()
    cursor = conn.execute(
        "INSERT INTO sessions (uuid, started_at, platform, config_snapshot_json, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), now, platform, json.dumps(config_snapshot or {}), now),
    )
    conn.commit()
    return _last_id(cursor)


def open_session(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["id"]) if row else None


def open_or_new_session(
    conn: sqlite3.Connection, platform: str = "linux", config_snapshot: dict[str, Any] | None = None
) -> int:
    existing = open_session(conn)
    if existing is not None:
        return existing
    return new_session(conn, platform=platform, config_snapshot=config_snapshot)


def close_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
        (utc_now_ms(), session_id),
    )
    conn.commit()


def get_session(conn: sqlite3.Connection, session_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def _insert(conn: sqlite3.Connection, table: str, values: dict[str, Any]) -> int:
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    cursor = conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", list(values.values())
    )
    return _last_id(cursor)


def insert_raw_event(
    conn: sqlite3.Connection,
    session_id: int,
    source: str,
    captured_at: int,
    payload: dict[str, Any],
    dedup_hash: str | None = None,
) -> int:
    return _insert(
        conn,
        "raw_events",
        {
            "session_id": session_id,
            "source": source,
            "captured_at": captured_at,
            "payload_json": json.dumps(payload),
            "dedup_hash": dedup_hash,
            "created_at": utc_now_ms(),
        },
    )


def insert_source(
    conn: sqlite3.Connection,
    session_id: int,
    raw_event_id: int,
    captured_at: int,
    monster: str,
    can_skin: bool,
    can_butcher: bool,
    can_extract: bool,
) -> int:
    return _insert(
        conn,
        "sources",
        {
            "session_id": session_id,
            "raw_event_id": raw_event_id,
            "captured_at": captured_at,
            "monster": monster,
            "can_skin": int(can_skin),
            "can_butcher": int(can_butcher),
            "can_extract": int(can_extract),
        },
    )


def insert_loot(
    conn: sqlite3.Connection, session_id: int, raw_event_id: int, captured_at: int, item: str, amount: int
) -> int:
    return _insert(
        conn,
        "loot",
        {
            "session_id": session_id,
            "raw_event_id": raw_event_id,
            "captured_at": captured_at,
            "item": item,
            "amount": amount,
        },
    )


def insert_burial(conn: sqlite3.Connection, session_id: int, raw_event_id: int, captured_at: int) -> int:
    return _insert(
        conn,
        "burials",
        {"session_id": session_id, "raw_event_id": raw_event_id, "captured_at": captured_at},
    )


def insert_target_sighting(
    conn: sqlite3.Connection, session_id: int, raw_event_id: int, captured_at: int, target_name: str
) -> int:
    return _insert(
        conn,
        "target_sightings",
        {
            "session_id": session_id,
            "raw_event_id": raw_event_id,
            "captured_at": captured_at,
            "target_name": target_name,
        },
    )


def insert_zone_change(
    conn: sqlite3.Connection, session_id: int, raw_event_id: int, captured_at: int, zone_name: str
) -> int:
    return _insert(
        conn,
        "zone_changes",
        {"session_id": session_id, "raw_event_id": raw_event_id, "captured_at": captured_at, "zone_name": zone_name},
    )


def insert_encounter(
    conn: sqlite3.Connection,
    session_id: int,
    encounter_uuid: str,
    monster: str,
    started_at: int,
    ended_at: int | None = None,
) -> int:
    return _insert(
        conn,
        "encounters",
        {
            "session_id": session_id,
            "encounter_uuid": encounter_uuid,
            "monster": monster,
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )


def insert_loot_drop(
    conn: sqlite3.Connection,
    session_id: int,
    encounter_id: int | None,
    captured_at: int,
    source: str,
    item: str,
    amount: int,
    activity: str,
    zone: str,
    status: str,
    lag_ms: int,
) -> int:
    return _insert(
        conn,
        "loot_drops",
        {
            "session_id": session_id,
            "encounter_id": encounter_id,
            "captured_at": captured_at,
            "source": source,
            "item": item,
            "amount": amount,
            "activity": activity,
            "zone": zone,
            "status": status,
            "lag_ms": int(lag_ms),
        },
    )


def status_overview(conn: sqlite3.Connection) -> dict[str, Any]:
    outcome: dict[str, Any] = {"sessions_total": 0, "open_session_id": None, "open_session_counts": None}
    outcome["sessions_total"] = int(conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"])
    sid = open_session(conn)
    outcome["open_session_id"] = sid
    if sid is not None:
        counts: dict[str, int] = {}
        for table in COUNT_TABLES:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE session_id = ?", (sid,)
            ).fetchone()
            counts[table] = int(row["c"])
        outcome["open_session_counts"] = counts
    return outcome