import sqlite3
from pathlib import Path

from gorgon_tracker import backfill, db
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.correlator import LootDrop, LootEvent
from gorgon_tracker.ingest import DbWriter
from gorgon_tracker.replay import expand_inputs, run_replay

from . import scenario


def _populated(tmp_path: Path) -> sqlite3.Connection:
    files = scenario.build(tmp_path)
    conn = db.connect(tmp_path / "backfill.db")
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.player_log, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    return conn


def _downgrade_to_old_style(conn: sqlite3.Connection) -> None:
    """Restore the pre-activity state: no ledger, drop-derived encounters only."""
    conn.execute("DELETE FROM encounter_activities")
    conn.execute(
        "DELETE FROM encounters WHERE id NOT IN"
        " (SELECT DISTINCT encounter_id FROM loot_drops WHERE encounter_id IS NOT NULL)"
    )
    conn.execute(
        "UPDATE encounters SET"
        " started_at = (SELECT MIN(captured_at) FROM loot_drops WHERE loot_drops.encounter_id = encounters.id),"
        " ended_at = (SELECT MAX(captured_at) FROM loot_drops WHERE loot_drops.encounter_id = encounters.id),"
        " zone = 'Unknown'"
    )
    conn.commit()


def _activity_map(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT activity, COUNT(*) c FROM encounter_activities GROUP BY activity"
    ).fetchall()
    return {r["activity"]: r["c"] for r in rows}


def test_backfill_restores_fresh_state(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        fresh_encounters = conn.execute("SELECT COUNT(*) c FROM encounters").fetchone()["c"]
        fresh_activities = _activity_map(conn)
        fresh_drops = conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"]

        _downgrade_to_old_style(conn)
        assert conn.execute("SELECT COUNT(*) c FROM encounter_activities").fetchone()["c"] == 0

        results = backfill.backfill_all(conn)
        assert len(results) == 1
        result = results[0]
        assert result["encounters_created"] == 2  # the two zero-drop corpses
        assert result["encounters_matched"] == 3

        assert conn.execute("SELECT COUNT(*) c FROM encounters").fetchone()["c"] == fresh_encounters
        assert _activity_map(conn) == fresh_activities
        assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == fresh_drops

        # Matched encounters recover their zone and their real end time.
        bat = conn.execute(
            "SELECT started_at, ended_at, zone FROM encounters"
            " WHERE monster = 'Giant Bat' AND zone = 'Old Graveyard'"
        ).fetchone()
        assert bat is not None and bat["ended_at"] == bat["started_at"] + 4000  # ended at bury +6
        deer = conn.execute(
            "SELECT started_at, ended_at FROM encounters WHERE monster = 'Deer' ORDER BY started_at"
        ).fetchall()
        assert [(int(r["started_at"]) % 1_000_000, int(r["ended_at"]) % 1_000_000) for r in deer] == [
            (631000, 634000),
            (641000, 643000),
        ]
    finally:
        conn.close()


def test_backfill_single_session(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        _downgrade_to_old_style(conn)
        results = backfill.backfill_all(conn, session_id=1)
        assert len(results) == 1
        assert results[0]["session_id"] == 1
        assert results[0]["activities"] == 11
        assert _activity_map(conn) == {"Looting": 5, "Skinning": 2, "Buried": 4}
    finally:
        conn.close()


def test_backfill_golden_rates_unchanged(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        _downgrade_to_old_style(conn)
        backfill.backfill_all(conn)
        rates = conn.execute(
            "SELECT monster, activity, item, drops, encounters, drop_rate FROM v_drop_rates"
            " ORDER BY monster, item"
        ).fetchall()
        skin = [r for r in rates if r["item"] == "Crude Animal Skin"][0]
        assert skin["activity"] == "Skinning"
        assert skin["encounters"] == 2
        assert round(skin["drop_rate"], 4) == 0.5
    finally:
        conn.close()


def test_backfill_cli_command(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from gorgon_tracker.cli import app

    db_path = tmp_path / "cli.db"
    files = scenario.build(tmp_path / "scenario")
    conn = db.connect(db_path)
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.player_log, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    _downgrade_to_old_style(conn)
    conn.close()

    result = CliRunner().invoke(app, ["backfill-encounters", "--db", str(db_path)], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "Backfilled sessions" in result.output
    assert "encounters created" in result.output

    conn = db.connect(db_path)
    try:
        assert _activity_map(conn) == {"Looting": 5, "Skinning": 2, "Buried": 4}
    finally:
        conn.close()


def test_backfill_is_idempotent(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        _downgrade_to_old_style(conn)
        first = backfill.backfill_all(conn)
        second = backfill.backfill_all(conn)
        # Re-running matches every existing encounter and inserts nothing new.
        assert second[0]["encounters_created"] == 0
        assert second[0]["encounters_matched"] == first[0]["encounters_created"] + first[0]["encounters_matched"]
        assert _activity_map(conn) == {"Looting": 5, "Skinning": 2, "Buried": 4}
    finally:
        conn.close()


# --- legacy-migrated sessions (no corpse events in raw_events) ----------------


def _legacy_style_session(conn: sqlite3.Connection) -> int:
    """Mimic a legacy CSV import: pre-correlated drops + one chat raw row each."""
    session_id = db.new_session(conn)
    writer = DbWriter(conn, session_id)
    rows = [
        (1000, "leg-1", "Fallow Deer", "Skinning", "Crude Animal Skin", "Ilmari"),
        (2000, "leg-1", "Fallow Deer", "Looting", "Deer Meat", "Ilmari"),
        (3000, "leg-2", "Fallow Deer", "Looting", "Deer Meat", "Ilmari"),
        (4000, "leg-3", "Moon Bat", "Skinning", "Bat Wing", "Old Graveyard"),
        (5000, "leg-3", "Moon Bat", "Looting", "Bat Guano", "Old Graveyard"),
        (6000, "leg-4", "Moon Bat", "Skinning", "Bat Wing", "Old Graveyard"),
    ]
    for time_ms, enc, monster, act, item, zone in rows:
        writer.loot(LootEvent(time_ms=time_ms, item=item, amount=1))
        writer.drop(
            LootDrop(
                time_ms=time_ms,
                source=monster,
                encounter_uuid=enc,
                activity=act,
                item=item,
                amount=1,
                status="Linked",
                lag_ms=0,
                zone=zone,
            )
        )
    writer.close_encounters()
    writer.commit()
    return session_id


def test_backfill_derives_legacy_ledger(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        sid = _legacy_style_session(conn)
        results = backfill.backfill_all(conn)
        legacy = next(r for r in results if r["session_id"] == sid)
        assert legacy["encounters_created"] == 0
        assert legacy["encounters_matched"] == 0
        assert legacy["derived"] == 6
        assert legacy["activities"] == 6

        # Per-activity rates now work from the observed drop activities.
        rates = conn.execute(
            "SELECT monster, activity, item, drops, encounters, drop_rate FROM v_drop_rates"
            " ORDER BY monster, item"
        ).fetchall()
        skin = next(r for r in rates if r["item"] == "Crude Animal Skin" and r["monster"] == "Fallow Deer")
        assert skin["activity"] == "Skinning"
        assert skin["encounters"] == 1
        assert round(skin["drop_rate"], 4) == 1.0
        meat = next(r for r in rates if r["item"] == "Deer Meat")
        assert meat["activity"] == "Looting"
        assert meat["encounters"] == 2
        wing = next(r for r in rates if r["item"] == "Bat Wing" and r["monster"] == "Moon Bat")
        assert wing["activity"] == "Skinning"
        assert wing["encounters"] == 2

        # The encountered corpse kept its zone and end time from the drops.
        bat = conn.execute(
            "SELECT zone, ended_at FROM encounters WHERE encounter_uuid = 'leg-3'"
        ).fetchone()
        assert bat["zone"] == "Old Graveyard"
        assert bat["ended_at"] == 5000

        # Re-running adds nothing (idempotent).
        assert backfill.backfill_all(conn)[-1]["derived"] == 0
    finally:
        conn.close()


def test_backfill_mixed_sessions(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    try:
        replay_result = backfill.backfill_all(conn)[0]
        assert replay_result["derived"] == 0
        assert replay_result["encounters_created"] == 0  # fresh ledger already complete
        assert replay_result["encounters_matched"] == 5

        sid = _legacy_style_session(conn)
        results = backfill.backfill_all(conn)
        assert len(results) == 2
        by_id = {r["session_id"]: r for r in results}
        assert by_id[sid]["derived"] == 6
        assert by_id[replay_result["session_id"]]["encounters_matched"] == 5
        assert _activity_map(conn)["Looting"] == 5 + 3  # golden 5 + legacy 3
    finally:
        conn.close()