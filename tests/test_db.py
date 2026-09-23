from pathlib import Path

from gorgon_tracker import db

EXPECTED_TABLES = {
    "sessions",
    "raw_events",
    "sources",
    "loot",
    "burials",
    "target_sightings",
    "zone_changes",
    "encounters",
    "loot_drops",
    "schema_migrations",
}


def _table_names(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
    ).fetchall()
    return {r["name"] for r in rows}


def test_connect_creates_latest_schema(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "x" / "g.db")
    db.migrate(conn)
    tables = _table_names(conn)
    assert tables >= EXPECTED_TABLES
    assert db.schema_version(conn) == 1
    conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    db.migrate(conn)
    rows = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()
    assert rows["c"] == 1
    assert db.schema_version(conn) == 1
    conn.close()


def test_session_lifecycle(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)

    assert db.open_session(conn) is None

    first = db.open_or_new_session(conn, "linux", {"k": "v"})
    assert db.open_session(conn) == first
    session = db.get_session(conn, first)
    assert session is not None
    assert session["ended_at"] is None
    assert session["platform"] == "linux"

    # Reuse the open session rather than creating a new one.
    assert db.open_or_new_session(conn, "linux") == first

    db.close_session(conn, first)
    assert db.open_session(conn) is None
    assert db.get_session(conn, first)["ended_at"] is not None

    # A new session is created once the previous one is closed.
    second = db.open_or_new_session(conn, "linux")
    assert second != first
    conn.close()


def test_insert_helpers_roundtrip(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)

    raw_id = db.insert_raw_event(conn, session_id, "chat", 1000, {"line": "x"}, "hash-1")
    assert raw_id == 1

    source_id = db.insert_source(conn, session_id, raw_id, 1000, "Rat", True, False, True)
    loot_id = db.insert_loot(conn, session_id, raw_id, 1000, "Rat Jaw", 2)
    bury_id = db.insert_burial(conn, session_id, raw_id, 1000)
    sight_id = db.insert_target_sighting(conn, session_id, raw_id, 1000, "Rat")
    zone_id = db.insert_zone_change(conn, session_id, raw_id, 1000, "Ilmari")
    enc_id = db.insert_encounter(conn, session_id, "uuid-1", "Rat", 900, 1100)
    drop_id = db.insert_loot_drop(conn, session_id, enc_id, 1000, "Rat", "Rat Jaw", 2, "Looting", "Ilmari", "Linked", 0)

    assert source_id == loot_id == bury_id == sight_id == zone_id == drop_id == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM loot_drops WHERE encounter_id = ?", (enc_id,)).fetchone()["c"] == 1
    conn.close()


def test_status_overview(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)
    db.insert_loot(conn, session_id, db.insert_raw_event(conn, session_id, "chat", 1, {}), 1, "Item", 1)

    overview = db.status_overview(conn)
    assert overview["sessions_total"] == 1
    assert overview["open_session_id"] == session_id
    assert overview["open_session_counts"]["loot"] == 1
    assert overview["open_session_counts"]["raw_events"] == 1
    conn.close()