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
    for command in ("stop", "find-ports", "calibrate", "serve"):
        result = runner.invoke(app, [command])
        assert result.exit_code == 0, command
        assert "not implemented yet" in result.output
    replay = runner.invoke(app, ["replay", "a.pcapng", "b.pcapng"])
    assert replay.exit_code == 0
    assert "Received 2 capture path(s)" in replay.output
    migrate = runner.invoke(app, ["migrate", "out.csv"])
    assert migrate.exit_code == 0
    assert "Received 1 file(s)" in migrate.output
    export = runner.invoke(app, ["export", "--since", "2026-01-01"])
    assert export.exit_code == 0
    assert "not implemented yet" in export.output