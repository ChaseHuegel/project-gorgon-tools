from pathlib import Path

from typer.testing import CliRunner

from gorgon_tracker import db
from gorgon_tracker.cli import app

runner = CliRunner()


def test_run_oneshot_creates_session(tmp_path: Path) -> None:
    db_path = str(tmp_path / "gorgon.db")
    result = runner.invoke(app, ["run", "--oneshot", "--db", db_path], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "Session 1 open" in result.output
    conn = db.connect(db_path)
    db.migrate(conn)
    assert db.open_session(conn) is None, "oneshot session should be closed"
    assert db.status_overview(conn)["sessions_total"] == 1
    conn.close()


def test_run_reuses_open_session(tmp_path: Path) -> None:
    db_path = str(tmp_path / "gorgon.db")
    assert runner.invoke(app, ["run", "--oneshot", "--db", db_path]).exit_code == 0
    assert runner.invoke(app, ["run", "--oneshot", "--db", db_path]).exit_code == 0
    conn = db.connect(db_path)
    db.migrate(conn)
    assert db.status_overview(conn)["sessions_total"] == 2
    conn.close()


def test_status_empty_database(tmp_path: Path) -> None:
    db_path = str(tmp_path / "gorgon.db")
    result = runner.invoke(app, ["status", "--db", db_path])
    assert result.exit_code == 0
    assert "Total sessions" in result.output
    assert "0" in result.output


def test_status_after_session(tmp_path: Path) -> None:
    db_path = str(tmp_path / "gorgon.db")
    runner.invoke(app, ["run", "--oneshot", "--db", db_path])
    result = runner.invoke(app, ["status", "--db", db_path])
    assert result.exit_code == 0
    assert "Total sessions" in result.output
    assert "No open session" in result.output


def test_config_command_prints_target(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "custom.db")
    result = runner.invoke(app, ["config", "--db", db_path])
    assert result.exit_code == 0
    assert "gorgon.db" not in result.output.replace(db_path, ""), "default db path should be overridden"
    assert db_path in result.output


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_stub_commands_report_pending() -> None:
    for command in ("serve",):
        result = runner.invoke(app, [command])
        assert result.exit_code == 0, command
        assert "not implemented yet" in result.output
    export = runner.invoke(app, ["export", "--since", "2026-01-01"])
    assert export.exit_code == 0
    assert "not implemented yet" in export.output


def test_stop_reports_not_running(tmp_path: Path) -> None:
    db_path = str(tmp_path / "nodb.db")
    result = runner.invoke(app, ["stop", "--db", db_path])
    assert result.exit_code == 0
    assert "not running" in result.output


def test_calibrate_command_runs(tmp_path: Path, monkeypatch) -> None:
    from gorgon_tracker import calibrate as calibrate_mod

    def fake_preview(cfg, region, watch, snapshot_path) -> None:  # noqa: ARG001
        print("OCR: Fairy Glen")

    monkeypatch.setattr(calibrate_mod, "preview", fake_preview)
    result = runner.invoke(
        app, ["calibrate", "--region", "10,20,30,40", "--snapshot", str(tmp_path / "shot.png")]
    )
    assert result.exit_code == 0, result.output
    assert "OCR: Fairy Glen" in result.output


def test_find_ports_reports_when_game_absent() -> None:
    result = runner.invoke(app, ["find-ports"])
    assert result.exit_code == 1
    assert "No Project Gorgon process found" in result.output


def test_replay_cli_end_to_end(tmp_path: Path) -> None:
    from . import scenario

    files = scenario.build(tmp_path)
    db_path = str(tmp_path / "cli.db")
    result = runner.invoke(
        app,
        [
            "replay",
            "--db",
            db_path,
            str(files.capture_json),
            str(files.chat_log),
            str(files.zones_csv),
            str(files.targets_csv),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "Replay summary" in result.output
    drops_line = [line for line in result.output.splitlines() if "drops" in line]
    assert drops_line and "4" in drops_line[0]
    conn = db.connect(db_path)
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 4
    conn.close()


def test_migrate_cli(tmp_path: Path) -> None:
    loot_csv = tmp_path / "loot.csv"
    loot_csv.write_text(
        "Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone\n"
        "2026-01-11 15:00:03,Rat,enc-a,Looting,Bone,1,Linked,0.5,Ilmari\n"
    )
    db_path = str(tmp_path / "cli.db")
    result = runner.invoke(app, ["migrate", "--db", db_path, str(loot_csv)], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert "Migration complete" in result.output
    conn = db.connect(db_path)
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 1
    conn.close()


def test_run_live_end_to_end_via_subprocess(tmp_path: Path) -> None:
    """Full CLI: start `run`, append a chat line, SIGTERM, verify graceful close."""
    import signal
    import subprocess
    import sys
    import time

    chats = tmp_path / "chats"
    chats.mkdir()
    log = chats / "session.log"
    log.write_text("")  # created before the tool starts -> tailed from offset 0

    config = tmp_path / "gorgon-tracker.toml"
    config.write_text(
        f'[db]\npath = "{tmp_path / "live.db"}"\n'
        "[capture]\nenabled = false\n"
        "[ocr]\nenabled = false\n"
        f"[chat]\nlog_dir = \"{chats}\"\ntail = true\n"
    )

    binary = Path(sys.executable).parent / "gorgon-tracker"
    proc = subprocess.Popen([str(binary), "--config", str(config), "run"])
    try:
        time.sleep(0.8)
        with log.open("a") as fh:
            fh.write("26-01-11 15:00:01 [Status] Live Bone x1 added to inventory.\n")
        time.sleep(0.6)
    finally:
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=15) == 0

    conn = db.connect(tmp_path / "live.db")
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 1
    assert db.open_session(conn) is None
    conn.close()