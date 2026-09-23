import io
from pathlib import Path

from gorgon_tracker import db, export
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.replay import expand_inputs, run_replay

from . import scenario


def _populated(tmp_path: Path):
    files = scenario.build(tmp_path)
    conn = db.connect(tmp_path / "export.db")
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.capture_json, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    return conn


def test_export_matches_legacy_header_and_rows(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    buffer = io.StringIO()
    count = export.export_loot_csv(conn, buffer)
    assert count == 4
    lines = buffer.getvalue().splitlines()
    assert lines[0] == "Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone"
    assert all(len(line.split(",")) == 9 for line in lines[1:])
    assert "Giant Bat" in lines[1] and "Looting" in lines[1]
    conn.close()


def test_export_since_filters(tmp_path: Path) -> None:
    conn = _populated(tmp_path)
    later = scenario.at(10.0)
    buffer = io.StringIO()
    count = export.export_loot_csv(conn, buffer, since_ms=later)
    assert count == 2  # drops at rel 12.0 and 20.0
    conn.close()