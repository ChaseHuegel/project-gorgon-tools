import sqlite3
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
    "loot_overrides",
    "corpse_searches",
    "items",
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
    assert db.schema_version(conn) == len(db.MIGRATIONS)
    conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    db.migrate(conn)
    rows = conn.execute("SELECT COUNT(*) AS c FROM schema_migrations").fetchone()
    assert rows["c"] == len(db.MIGRATIONS)
    assert db.schema_version(conn) == len(db.MIGRATIONS)
    conn.close()


def test_migrate_upgrades_version_1_database(tmp_path: Path) -> None:
    """A pre-evidence DB (v1) gains the new loot_drops columns and overrides table."""
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(
        """
        CREATE TABLE loot (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            raw_event_id INTEGER,
            captured_at INTEGER NOT NULL,
            item TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE loot_drops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            encounter_id INTEGER,
            captured_at INTEGER NOT NULL,
            source TEXT NOT NULL,
            item TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 1,
            activity TEXT NOT NULL DEFAULT 'Looting',
            zone TEXT NOT NULL DEFAULT 'Unknown',
            status TEXT NOT NULL DEFAULT 'Linked',
            lag_ms INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.execute("PRAGMA user_version = 1")
    conn.close()

    conn = db.connect(tmp_path / "old.db")
    db.migrate(conn)
    assert db.schema_version(conn) == len(db.MIGRATIONS)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(loot_drops)")}
    assert cols >= {
        "linked_via",
        "monster_name",
        "monster_lag_ms",
        "target_name",
        "target_lag_ms",
        "instance_id",
        "entity_id",
        "item_code_id",
        "item_display",
        "missed",
        "killer_json",
    }
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
    drop_id = db.insert_loot_drop(
        conn,
        session_id,
        enc_id,
        1000,
        "Rat",
        "Rat Jaw",
        2,
        "Looting",
        "Ilmari",
        "Linked",
        0,
        linked_via="monster",
        monster_name="Rat",
        monster_lag_ms=42,
        target_name="Dire Wolf",
        target_lag_ms=7,
        corroborated_by_search=True,
    )

    assert source_id == loot_id == bury_id == sight_id == zone_id == drop_id == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM loot_drops WHERE encounter_id = ?", (enc_id,)).fetchone()["c"] == 1
    row = conn.execute("SELECT * FROM loot_drops WHERE id = ?", (drop_id,)).fetchone()
    assert row["linked_via"] == "monster"
    assert row["monster_lag_ms"] == 42
    assert row["corroborated_by_search"] == 1
    conn.close()


def test_loot_override_upsert_delete(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)
    drop_id = db.insert_loot_drop(conn, session_id, None, 1000, "Rat", "Bone", 1, "Looting", "Ilmari", "Linked", 0)

    override_id = db.upsert_loot_override(
        conn, drop_id, source="Wolf", status="Linked", activity="Harvesting", note="manual"
    )
    assert override_id == 1
    override = db.get_loot_override(conn, drop_id)
    assert override["source"] == "Wolf"
    assert override["activity"] == "Harvesting"
    assert override["note"] == "manual"

    # Upsert replaces (unique on loot_drop_id, single row).
    db.upsert_loot_override(conn, drop_id, status="Orphaned")
    overrides = conn.execute("SELECT * FROM loot_overrides").fetchall()
    assert len(overrides) == 1
    assert overrides[0]["status"] == "Orphaned"
    assert overrides[0]["source"] == "Wolf"  # untouched fields persist

    db.delete_loot_override(conn, drop_id)
    assert db.get_loot_override(conn, drop_id) is None
    conn.close()


def test_delete_loot_drops_removes_rows_and_overrides(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)
    first = db.insert_loot_drop(conn, session_id, None, 1000, "Rat", "Bone", 1, "Looting", "Ilmari", "Linked", 0)
    second = db.insert_loot_drop(conn, session_id, None, 1001, "Wolf", "Fang", 1, "Looting", "Ilmari", "Linked", 0)
    db.upsert_loot_override(conn, first, source="Chest", status="Linked", activity="Looting")

    assert db.delete_loot_drops(conn, [first]) == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM loot_drops").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM loot_overrides").fetchone()["c"] == 0

    assert db.delete_loot_drops(conn, [second, 9999]) == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM loot_drops").fetchone()["c"] == 0

    assert db.delete_loot_drops(conn, [0, -1]) == 0
    conn.close()


def test_clear_all_wipes_everything_but_schema(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)
    raw_id = db.insert_raw_event(conn, session_id, "chat", 1, {})
    db.insert_loot(conn, session_id, raw_id, 1, "Item", 1)
    drop_id = db.insert_loot_drop(conn, session_id, None, 1000, "Rat", "Bone", 1, "Looting", "Ilmari", "Linked", 0)
    db.upsert_loot_override(conn, drop_id, source="Chest", status="Linked", activity="Looting")
    db.record_item(conn, "Base", "1", "Display", 1)
    db.insert_corpse_search(conn, session_id, raw_id, 1, 42, "Rat")

    cleared = db.clear_all(conn)
    assert cleared["loot_drops"] >= 1
    assert cleared["sessions"] == 1
    for table in EXPECTED_TABLES:
        if table == "schema_migrations":
            assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == len(db.MIGRATIONS)
        else:
            assert conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] == 0

    assert db.new_session(conn) == 1  # autoincrement reset
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


def test_insert_corpse_search_and_item_learning(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    session_id = db.new_session(conn)

    raw_id = db.insert_raw_event(conn, session_id, "unity_corpse", 1000, {"monster": "Rat"})
    search_id = db.insert_corpse_search(
        conn, session_id, raw_id, 1000, 42, "Rat", killer="Tester", participants={"Tester": {"health": 5, "aggro": 1.0}}
    )
    assert isinstance(search_id, int)

    extra_id = db.insert_corpse_search(
        conn,
        session_id,
        raw_id,
        2000,
        43,
        "Giant Bat",
        extractions={"skinned": "a Pelt", "butchered": "Pork"},
    )
    row = conn.execute(
        "SELECT extractions_json FROM corpse_searches WHERE id = ?", (extra_id,)
    ).fetchone()
    assert row["extractions_json"] == '{"skinned": "a Pelt", "butchered": "Pork"}'
    assert conn.execute(
        "SELECT extractions_json FROM corpse_searches WHERE id = ?", (search_id,)
    ).fetchone()["extractions_json"] == "{}"

    db.record_item(conn, "GoblinCallingCard", "15", "Gottak's Calling Card", 1000, inferred=False)
    assert db.get_item_display(conn, "GoblinCallingCard", "15") == "Gottak's Calling Card"
    db.record_item(conn, "GoblinCallingCard", "15", "Gottak's Calling Card", 2000)
    row = conn.execute("SELECT * FROM items WHERE base_name='GoblinCallingCard'").fetchone()
    assert row["times_seen"] == 2
    conn.close()

def test_seed_items_populates_canonical_rows(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    from gorgon_tracker import catalog

    rows = catalog.item_seed_rows()
    assert len(rows) == 11048
    db.seed_items(conn, rows)

    row = conn.execute(
        "SELECT * FROM items WHERE base_name='ArmorPatchKit' AND item_code='3'"
    ).fetchone()
    assert row["display_name"] == "Good Armor Patch Kit"
    assert row["display_inferred"] == 0
    assert row["times_seen"] == 0
    assert row["item_value"] == 25
    assert row["data_version"] == "486"

    # Idempotent: re-seeding keeps one row per key.
    db.seed_items(conn, rows)
    assert conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"] == 11048
    conn.close()


def test_seed_items_preserves_learned_rows_and_refreshes_metadata(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    from gorgon_tracker import catalog

    rows = catalog.item_seed_rows()
    db.seed_items(conn, rows)

    # A canonical (non-inferred) learned row keeps its display name.
    db.record_item(conn, "ArmorPatchKit", "3", "Good Armor Patch Kit", 1234, inferred=False)
    db.seed_items(conn, rows)
    row = conn.execute(
        "SELECT display_name, times_seen FROM items WHERE base_name='ArmorPatchKit' AND item_code='3'"
    ).fetchone()
    assert row["display_name"] == "Good Armor Patch Kit"
    assert row["times_seen"] == 1  # sighting count preserved across re-seed

    # Re-seed with mutated metadata refreshes value/stack/keywords.
    altered = []
    for r in rows:
        base, code = r[0], r[1]
        if code == "3":
            altered.append((base, code, r[2], 999, r[4], r[5], r[6], "987"))
        else:
            altered.append(r)
    db.seed_items(conn, altered)
    row = conn.execute(
        "SELECT item_value, data_version FROM items WHERE base_name='ArmorPatchKit' AND item_code='3'"
    ).fetchone()
    assert row["item_value"] == 999
    assert row["data_version"] == "987"
    conn.close()


def test_seed_from_catalog_only_runs_when_empty(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    assert db.seed_from_catalog(conn) == 11048
    assert db.seed_from_catalog(conn) == 0  # no-op once populated
    conn.close()


def test_clear_all_then_reseed_restores_catalog(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "g.db")
    db.migrate(conn)
    db.seed_from_catalog(conn)
    assert conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"] == 11048

    cleared = db.clear_all(conn)
    assert cleared["items"] == 11048
    assert conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"] == 0

    assert db.seed_from_catalog(conn) == 11048
    conn.close()
