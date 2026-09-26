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


def test_replay_attributes_corpse_description_skinning(tmp_path: Path) -> None:
    """A corpse description gaining a ``skinned`` line labels the loot as Skinning."""
    playerlog = tmp_path / "Player.log"
    playerlog.write_text(
        "\n".join(
            [
                "[20:00:00] Logged in as character Tester. Time UTC=01/11/2026 20:00:00. "
                "Timezone Offset -01:00:00.",
                '[20:00:01] LocalPlayer: ProcessStartInteraction(501, 13.5, 0, False, "")',
                "[20:00:02] LocalPlayer: ProcessAddItem(BatWing(-1), -1, True)",
                '[20:00:03] LocalPlayer: ProcessTalkScreen(501, "Search Corpse of Giant Bat", '
                '"\\n<em>Killer:</em> Tester\\n", "", [], System.String[], 1, Corpse)',
                "[20:00:04] LocalPlayer: ProcessAddItem(GiantBatWing(-2), -1, True)",
                '[20:00:05] LocalPlayer: ProcessTalkScreen(501, "Search Corpse of Giant Bat", '
                '"\\n<em>Killer:</em> Tester\\n\\nTester skinned a Pelt from the corpse.", '
                '"", [], System.String[], 1, Corpse)',
                '[20:00:06] LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")',
            ]
        )
        + "\n"
    )
    conn = _connect(tmp_path)
    stats = run_replay(conn, TrackerConfig(), expand_inputs([playerlog]))
    assert stats["loot_kept"] == 2
    rows = conn.execute("SELECT captured_at, activity FROM loot_drops ORDER BY captured_at").fetchall()
    assert [r["activity"] for r in rows] == ["Looting", "Skinning"]
    conn.close()


def test_replay_chat_activity_markers_label_drops(tmp_path: Path) -> None:
    """A ``You butcher the corpse.`` status line labels the nearby pickup."""
    chat = tmp_path / "chatsession.log"
    chat.write_text(
        "\n".join(
            [
                f"{scenario.local_wall(1.0)} [Status] Pork added to inventory.",
                f"{scenario.local_wall(2.0)} [Status] You butcher the corpse.",
                f"{scenario.local_wall(3.0)} [Status] You bury the corpse.",
            ]
        )
        + "\n"
    )
    conn = _connect(tmp_path)
    stats = run_replay(conn, TrackerConfig(), expand_inputs([chat]))
    assert stats["activities"] == 1
    row = conn.execute("SELECT item, activity FROM loot_drops ORDER BY captured_at").fetchone()
    assert row["item"] == "Pork"
    assert row["activity"] == "Butchering"
    conn.close()