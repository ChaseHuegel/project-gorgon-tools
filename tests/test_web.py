from pathlib import Path

import fastapi  # noqa: F401
from fastapi.testclient import TestClient

import gorgon_tracker  # noqa: F401
from gorgon_tracker.config_write import write_updates
from gorgon_tracker.web import build_web_app


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
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/status").status_code == 200


def test_build_read_router_api_health_isolation(tmp_path: Path) -> None:
    client = TestClient(build_web_app(str(tmp_path / "data/gorgon.db"), None))
    assert client.get("/loot").json() == []


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