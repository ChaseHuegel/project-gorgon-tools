from pathlib import Path

import fastapi  # noqa: F401
from fastapi.testclient import TestClient

import gorgon_tracker  # noqa: F401
from gorgon_tracker.config_write import write_updates
from gorgon_tracker.web import build_web_app

from . import scenario


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "gorgon-tracker.toml"
    path.write_text("[db]\npath = 'data/gorgon.db'\n")
    return path


def test_status_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = _config_file(tmp_path)
    # Disable sources so warnings stay deterministic; daemon stopped.
    write_updates({"capture.enabled": False, "chat.tail": False, "ocr.enabled": False}, str(config_file))
    cfg_path = str(config_file)

    monkeypatch.setattr("gorgon_tracker.web.control.daemon_status", lambda dbp: {"pid": None, "running": False})
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), cfg_path))

    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["config_path"] == cfg_path
    assert body["sessions_total"] >= 0
    assert body["open_session_id"] is None
    assert body["daemon"]["running"] is False


def test_get_config_round_trips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = _config_file(tmp_path)
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), str(config_file)))

    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == str(config_file)
    assert body["config"]["db"]["path"] == str((tmp_path / "data/gorgon.db").resolve())


def test_put_config_validates_and_persists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = _config_file(tmp_path)
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), str(config_file)))

    ok = client.put("/api/config", json={"updates": {"capture.interface": "eth0"}})
    assert ok.status_code == 200
    assert ok.json()["config"]["capture"]["interface"] == "eth0"

    bad = client.put("/api/config", json={"updates": {"ocr.zones.region": [1, 2]}})
    assert bad.status_code == 422

    assert "eth0" in config_file.read_text()


def test_daemon_endpoints_mock() -> None:
    from gorgon_tracker import control

    started = {"pid": 1234, "running": True}

    def fake_start(*a, **k):
        return started

    def fake_stop(*a, **k):
        return {"pid": None, "running": False}

    control.daemon_start = fake_start
    control.daemon_stop = fake_stop

    client = TestClient(build_web_app("/tmp/x/data/gorgon.db", None))
    assert client.post("/api/daemon/start").json() == started
    assert client.post("/api/daemon/stop").json() == {"pid": None, "running": False}


def test_web_app_mounts_read_endpoints(tmp_path: Path) -> None:
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), None))
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/status").status_code == 200


def test_build_read_router_api_health_isolation(tmp_path: Path) -> None:
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), None))
    assert client.get("/api/loot").json() == []


def test_spa_served_with_fallback_and_api_404(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>UI</html>")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("console.log('x')")

    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), None, static_dir=static))

    root = client.get("/")
    assert root.status_code == 200 and root.text == "<html>UI</html>"

    fallback = client.get("/sessions/view")
    assert fallback.status_code == 200 and fallback.text == "<html>UI</html>"

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200 and asset.text == "console.log('x')"

    api = client.get("/api/nope")
    assert api.status_code == 404


def _chat_config(tmp_path: Path, log_dir: str) -> Path:
    path = tmp_path / "gorgon-tracker.toml"
    path.write_text(f"[db]\npath = 'data/gorgon.db'\n[chat]\nlog_dir = '{log_dir}'\n")
    return path


def _match_line(seconds: float, item: str | None) -> str:
    if item is None:
        return f"{scenario.local_wall(seconds)} [Status] You bury the corpse."
    return f"{scenario.local_wall(seconds)} [Status] {item} added to inventory."


def _chat_client(tmp_path: Path, log_dir: str) -> TestClient:
    return TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), str(_chat_config(tmp_path, log_dir))))


def test_chat_tail_happy_path(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    (chats / "session.log").write_text(
        "\n".join([_match_line(1.0, "Bat Guano"), "player says hello", _match_line(2.0, None)]) + "\n"
    )

    resp = _chat_client(tmp_path, str(chats)).get("/api/chat/tail")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["file"] == "session.log"
    assert body["log_dir"] == str(chats)
    assert [line["kind"] for line in body["lines"]] == ["loot", None, "bury"]
    assert body["lines"][0]["text"].endswith("Bat Guano added to inventory.")


def test_chat_tail_limit_returns_last_lines_oldest_first(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    (chats / "session.log").write_text(
        "\n".join(_match_line(float(i), str(i)) for i in range(1, 11)) + "\n"
    )

    body = _chat_client(tmp_path, str(chats)).get("/api/chat/tail?limit=3").json()
    assert body["found"] is True
    assert [line["text"].split("] ", 1)[1] for line in body["lines"]] == [
        "8 added to inventory.",
        "9 added to inventory.",
        "10 added to inventory.",
    ]


def test_chat_tail_missing_log_dir(tmp_path: Path) -> None:
    body = _chat_client(tmp_path, str(tmp_path / "nope")).get("/api/chat/tail").json()
    assert body["found"] is False
    assert body["reason"] == "chat log directory not found"
    assert body["log_dir"] == str(tmp_path / "nope")


def test_chat_tail_no_logs_in_dir(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    body = _chat_client(tmp_path, str(chats)).get("/api/chat/tail").json()
    assert body["found"] is False
    assert body["reason"] == "no chat logs in directory"


def test_chat_tail_unreadable_log(tmp_path: Path, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr("gorgon_tracker.sources.chat_tail.newest_log", boom)
    chats = tmp_path / "chats"
    chats.mkdir()
    (chats / "session.log").write_text(_match_line(1.0, "Bone") + "\n")

    body = _chat_client(tmp_path, str(chats)).get("/api/chat/tail").json()
    assert body["found"] is False
    assert body["reason"] == "chat log unreadable"