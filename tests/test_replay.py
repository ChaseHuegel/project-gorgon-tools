import csv
import sqlite3
from pathlib import Path

from gorgon_tracker import db
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.replay import expand_inputs, run_replay

from . import scenario

FIXTURE_EXPECTED = Path(__file__).parent / "fixtures" / "phase1" / "expected_loot.csv"


def _connect(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "golden.db")
    db.migrate(conn)
    return conn


def _read_golden() -> list[dict]:
    rows = []
    with FIXTURE_EXPECTED.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            rows.append(
                {
                    "rel_ms": float(row["rel_ms"]),
                    "source": row["source"],
                    "encounter": int(row["encounter"]),
                    "activity": row["activity"],
                    "item": row["item"],
                    "amount": int(row["amount"]),
                    "status": row["status"],
                    "lag_ms": int(row["lag_ms"]),
                    "zone": row["zone"],
                }
            )
    return rows


def _normalized_drops(conn: sqlite3.Connection, base_ms: int) -> list[dict]:
    rows = conn.execute(
        "SELECT captured_at, source, encounter_id, activity, item, amount, status, lag_ms, zone "
        "FROM loot_drops ORDER BY captured_at"
    ).fetchall()
    encounter_nums: dict[int, int] = {}
    next_num = 1
    normalized = []
    for row in rows:
        if row["encounter_id"] not in encounter_nums:
            encounter_nums[row["encounter_id"]] = next_num
            next_num += 1
        normalized.append(
            {
                "rel_ms": round((row["captured_at"] - base_ms) / 1000.0, 1),
                "source": row["source"],
                "encounter": encounter_nums[row["encounter_id"]],
                "activity": row["activity"],
                "item": row["item"],
                "amount": row["amount"],
                "status": row["status"],
                "lag_ms": row["lag_ms"],
                "zone": row["zone"],
            }
        )
    return normalized


def test_replay_matches_committed_golden_output(tmp_path: Path) -> None:
    files = scenario.build(tmp_path)
    cfg = TrackerConfig()
    conn = _connect(tmp_path)

    stats = run_replay(
        conn,
        cfg,
        expand_inputs([files.capture_json, files.chat_log, files.zones_csv, files.targets_csv]),
    )

    assert stats["windows"] == 1
    assert stats["sources"] == 7
    assert stats["zones"] == 2
    assert stats["targets"] == 2
    assert stats["burials"] == 2
    assert stats["loot_kept"] == 4
    assert stats["loot_filtered"] == 2
    assert stats["drops"] == 4

    expected = _read_golden()
    actual = _normalized_drops(conn, files.base_ms)
    assert {tuple(e.items()) for e in expected} == {tuple(a.items()) for a in actual}


def test_replay_populates_typed_tables_and_views(tmp_path: Path) -> None:
    files = scenario.build(tmp_path)
    cfg = TrackerConfig()
    conn = _connect(tmp_path)
    run_replay(conn, cfg, expand_inputs([files.capture_json, files.chat_log, files.zones_csv, files.targets_csv]))

    assert conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"] == 7
    assert conn.execute("SELECT COUNT(*) c FROM loot").fetchone()["c"] == 4
    assert conn.execute("SELECT COUNT(*) c FROM encounters").fetchone()["c"] == 4
    assert conn.execute("SELECT COUNT(*) c FROM zone_changes").fetchone()["c"] == 2

    # Every encounter is closed with a plausible window.
    bad = conn.execute(
        "SELECT COUNT(*) c FROM encounters WHERE ended_at IS NULL OR ended_at < started_at"
    ).fetchone()
    assert bad["c"] == 0

    # Aggregation views materialize.
    rows = conn.execute("SELECT monster, item FROM v_drop_rates ORDER BY monster, item").fetchall()
    assert len(rows) == 4
    conn.close()


def test_replay_builds_consolidated_session(tmp_path: Path) -> None:
    files = scenario.build(tmp_path / "nested" / "deep")
    cfg = TrackerConfig()
    conn = _connect(tmp_path)
    stats = run_replay(conn, cfg, expand_inputs([files.capture_json, files.chat_log]))
    overview = db.status_overview(conn)
    assert overview["sessions_total"] == 1
    assert overview["open_session_id"] is None  # replay sessions are retrospective
    assert stats["session_id"] is not None
    conn.close()