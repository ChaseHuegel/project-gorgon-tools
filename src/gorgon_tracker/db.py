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

# v2: audit evidence on loot_drops plus a reversible manual-override table.
_MIGRATION_V2_SQL = """
ALTER TABLE loot_drops ADD COLUMN linked_via TEXT NOT NULL DEFAULT 'monster';
ALTER TABLE loot_drops ADD COLUMN monster_name TEXT;
ALTER TABLE loot_drops ADD COLUMN monster_lag_ms INTEGER;
ALTER TABLE loot_drops ADD COLUMN target_name TEXT;
ALTER TABLE loot_drops ADD COLUMN target_lag_ms INTEGER;
ALTER TABLE loot_drops ADD COLUMN corroborated_by_search INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS loot_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loot_drop_id INTEGER NOT NULL UNIQUE REFERENCES loot_drops(id),
    source TEXT,
    status TEXT,
    activity TEXT,
    note TEXT,
    created_at INTEGER NOT NULL
);
"""

_MIGRATION_V3_SQL = """
ALTER TABLE loot ADD COLUMN instance_id INTEGER;
ALTER TABLE loot ADD COLUMN entity_id INTEGER;
ALTER TABLE loot ADD COLUMN source_class TEXT NOT NULL DEFAULT 'chat';

ALTER TABLE loot_drops ADD COLUMN instance_id INTEGER;
ALTER TABLE loot_drops ADD COLUMN entity_id INTEGER;
ALTER TABLE loot_drops ADD COLUMN item_code_id INTEGER;
ALTER TABLE loot_drops ADD COLUMN item_display TEXT;
ALTER TABLE loot_drops ADD COLUMN missed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE loot_drops ADD COLUMN killer_json TEXT;

CREATE TABLE IF NOT EXISTS corpse_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    raw_event_id INTEGER REFERENCES raw_events(id),
    captured_at INTEGER NOT NULL,
    entity_id INTEGER,
    monster TEXT NOT NULL,
    killer TEXT,
    participants_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_corpse_searches_session ON corpse_searches(session_id, captured_at);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    base_name TEXT NOT NULL,
    item_code TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL,
    display_inferred INTEGER NOT NULL DEFAULT 1,
    times_seen INTEGER NOT NULL DEFAULT 1,
    first_seen_at INTEGER NOT NULL,
    UNIQUE(base_name, item_code)
);
"""

MIGRATIONS: list[tuple[int, str]] = [(1, _SCHEMA_SQL), (2, _MIGRATION_V2_SQL), (3, _MIGRATION_V3_SQL)]

COUNT_TABLES = (
    "raw_events",
    "sources",
    "loot",
    "burials",
    "target_sightings",
    "zone_changes",
    "encounters",
    "loot_drops",
    "corpse_searches",
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
    conn: sqlite3.Connection,
    session_id: int,
    raw_event_id: int,
    captured_at: int,
    item: str,
    amount: int,
    instance_id: int | None = None,
    entity_id: int | None = None,
    source_class: str = "chat",
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
            "instance_id": instance_id,
            "entity_id": entity_id,
            "source_class": source_class,
        },
    )


def insert_corpse_search(
    conn: sqlite3.Connection,
    session_id: int,
    raw_event_id: int,
    captured_at: int,
    entity_id: int | None,
    monster: str,
    killer: str | None = None,
    participants: dict[str, Any] | None = None,
) -> int:
    import json as _json

    return _insert(
        conn,
        "corpse_searches",
        {
            "session_id": session_id,
            "raw_event_id": raw_event_id,
            "captured_at": captured_at,
            "entity_id": entity_id,
            "monster": monster,
            "killer": killer,
            "participants_json": _json.dumps(participants or {}),
        },
    )


def record_item(
    conn: sqlite3.Connection,
    base_name: str,
    item_code: str,
    display_name: str,
    seen_at: int,
    inferred: bool = True,
) -> None:
    """Learn/count a canonical item (base + variant code) -> display mapping."""
    if item_code:
        sql = (
            "INSERT INTO items (base_name, item_code, display_name, display_inferred, first_seen_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(base_name, item_code) DO UPDATE SET "
            "times_seen = items.times_seen + 1"
        )
        conn.execute(sql, (base_name, item_code, display_name, int(inferred), seen_at))


def get_item_display(conn: sqlite3.Connection, base_name: str, item_code: str) -> str | None:
    row = conn.execute(
        "SELECT display_name FROM items WHERE base_name = ? AND item_code = ?",
        (base_name, item_code),
    ).fetchone()
    return row["display_name"] if row else None


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
    linked_via: str = "monster",
    monster_name: str | None = None,
    monster_lag_ms: int | None = None,
    target_name: str | None = None,
    target_lag_ms: int | None = None,
    corroborated_by_search: bool = False,
    instance_id: int | None = None,
    entity_id: int | None = None,
    item_code_id: int | None = None,
    item_display: str | None = None,
    missed: bool = False,
    killer_json: str | None = None,
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
            "linked_via": linked_via,
            "monster_name": monster_name,
            "monster_lag_ms": monster_lag_ms,
            "target_name": target_name,
            "target_lag_ms": target_lag_ms,
            "corroborated_by_search": int(corroborated_by_search),
            "instance_id": instance_id,
            "entity_id": entity_id,
            "item_code_id": item_code_id,
            "item_display": item_display,
            "missed": int(missed),
            "killer_json": killer_json,
        },
    )


def upsert_loot_override(
    conn: sqlite3.Connection,
    loot_drop_id: int,
    source: str | None = None,
    status: str | None = None,
    activity: str | None = None,
    note: str | None = None,
) -> int:
    """Insert or replace the manual override for one loot drop; returns its row id.

    Partial updates are merged over any existing override so unset fields persist.
    """
    existing = get_loot_override(conn, loot_drop_id)
    values = {
        "loot_drop_id": loot_drop_id,
        "source": source if source is not None else (existing or {}).get("source"),
        "status": status if status is not None else (existing or {}).get("status"),
        "activity": activity if activity is not None else (existing or {}).get("activity"),
        "note": note if note is not None else (existing or {}).get("note"),
        "created_at": utc_now_ms(),
    }
    with conn:
        conn.execute("DELETE FROM loot_overrides WHERE loot_drop_id = ?", (loot_drop_id,))
        return _insert(conn, "loot_overrides", values)


def delete_loot_override(conn: sqlite3.Connection, loot_drop_id: int) -> None:
    """Remove the manual override for one loot drop (revert to correlated values)."""
    with conn:
        conn.execute("DELETE FROM loot_overrides WHERE loot_drop_id = ?", (loot_drop_id,))


def get_loot_override(conn: sqlite3.Connection, loot_drop_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM loot_overrides WHERE loot_drop_id = ?", (loot_drop_id,)
    ).fetchone()
    return dict(row) if row else None


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