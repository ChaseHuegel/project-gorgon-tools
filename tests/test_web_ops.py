from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from gorgon_tracker import db
from gorgon_tracker.web import build_web_app

from . import scenario


def _client(tmp_path: Path, config_file: Path | None = None) -> TestClient:
    return TestClient(
        build_web_app(str(tmp_path / "data/gorgon.db"), str(config_file) if config_file else None)
    )


def _config_file(tmp_path: Path) -> Path:
    path = tmp_path / "gorgon-tracker.toml"
    path.write_text("[db]\npath = 'data/gorgon.db'\n")
    return path


# --- ports -------------------------------------------------------------------


def test_ports_discover_reports_not_found(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("gorgon_tracker.ports.discover_ports", lambda: (set(), set()))
    resp = _client(tmp_path).post("/api/ports/discover")
    assert resp.status_code == 200
    assert resp.json() == {"tcp": [], "udp": [], "bpf": "", "persisted": False, "found": False}


def test_ports_discover_and_persist(tmp_path: Path, monkeypatch) -> None:
    config_file = _config_file(tmp_path)
    monkeypatch.setattr("gorgon_tracker.ports.discover_ports", lambda: ({45000, 45002}, {54000}))
    client = _client(tmp_path, config_file)

    reported = client.post("/api/ports/discover").json()
    assert reported["found"] is True
    assert "tcp.port == 45000" in reported["bpf"]

    persisted = client.post("/api/ports/discover", json={"write_config": True}).json()
    assert persisted["persisted"] is True
    text = config_file.read_text()
    assert "45000" in text and "tcp.port" in text


# --- replay / migrate via upload --------------------------------------------


def test_replay_upload(tmp_path: Path) -> None:
    files = scenario.build(tmp_path)
    client = _client(tmp_path)
    uploads = [
        ("files", (files.capture_json.name, files.capture_json.open("rb"), "application/json")),
        ("files", (files.chat_log.name, files.chat_log.open("rb"), "text/plain")),
        ("files", (files.zones_csv.name, files.zones_csv.open("rb"), "text/csv")),
        ("files", (files.targets_csv.name, files.targets_csv.open("rb"), "text/csv")),
    ]
    resp = client.post("/api/replay", files=uploads)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["drops"] == 4
    assert len(body["inputs"]) == 4

    conn = db.connect(str(tmp_path / "data/gorgon.db"))
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 4
    conn.close()


def test_replay_server_paths_only(tmp_path: Path, monkeypatch) -> None:
    files = scenario.build(tmp_path)
    monkeypatch.chdir(tmp_path)
    resp = _client(tmp_path).post(
        "/api/replay",
        data={
            "paths": [
                str(files.capture_json),
                str(files.chat_log),
                str(files.zones_csv),
                str(files.targets_csv),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["drops"] == 4


def test_migrate_upload(tmp_path: Path) -> None:
    loot_csv = tmp_path / "loot.csv"
    loot_csv.write_text(
        "Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone\n"
        "2026-01-11 15:00:03,Rat,enc-a,Looting,Bone,1,Linked,0.5,Ilmari\n"
    )
    client = _client(tmp_path)
    resp = client.post(
        "/api/migrate",
        files=[("files", (loot_csv.name, loot_csv.open("rb"), "text/csv"))],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["imported"][0]["imported"] == 1

    conn = db.connect(str(tmp_path / "data/gorgon.db"))
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 1
    conn.close()


# --- export ------------------------------------------------------------------


def test_export_csv(tmp_path: Path) -> None:
    files = scenario.build(tmp_path)
    client = _client(tmp_path)
    client.post("/api/replay", data={"paths": [str(files.capture_json), str(files.chat_log)]})

    resp = client.get("/api/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.text.startswith("Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone")


# --- loot overrides ----------------------------------------------------------


def _replay_and_drops(tmp_path: Path) -> tuple[TestClient, list[dict]]:
    files = scenario.build(tmp_path)
    client = _client(tmp_path)
    resp = client.post(
        "/api/replay",
        data={
            "paths": [
                str(files.capture_json),
                str(files.chat_log),
                str(files.zones_csv),
                str(files.targets_csv),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    drops = client.get("/api/loot", params={"limit_rows": 100}).json()
    return client, drops


def test_loot_override_roundtrip(tmp_path: Path) -> None:
    client, drops = _replay_and_drops(tmp_path)
    target = next(r for r in drops if r["item"] == "Ground Twig")
    assert target["overridden"] is False

    resp = client.put(
        f"/api/loot/{target['id']}",
        json={"source": "Chest", "status": "Linked", "activity": "Looting", "note": "looks like a chest"},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["source"] == "Chest"
    assert updated["overridden"] is True
    assert updated["note"] == "looks like a chest"
    assert updated["linked_via"] == "target"  # evidence preserved

    # Partial update keeps previously overridden fields.
    partial = client.put(f"/api/loot/{target['id']}", json={"activity": "Harvesting"}).json()
    assert partial["source"] == "Chest"
    assert partial["activity"] == "Harvesting"

    # The list endpoint reflects the override.
    listing = {r["id"]: r for r in client.get("/api/loot", params={"limit_rows": 100}).json()}
    assert listing[target["id"]]["source"] == "Chest"

    # Revert restores the correlated values.
    reverted = client.delete(f"/api/loot/{target['id']}")
    assert reverted.status_code == 200
    listing = {r["id"]: r for r in client.get("/api/loot", params={"limit_rows": 100}).json()}
    assert listing[target["id"]]["overridden"] is False
    assert listing[target["id"]]["source"] == "Dire Wolf"


def test_loot_override_validates(tmp_path: Path) -> None:
    client, drops = _replay_and_drops(tmp_path)
    drop = drops[0]

    missing = client.put("/api/loot/99999", json={"source": "Rat"})
    assert missing.status_code == 404

    bad_status = client.put(f"/api/loot/{drop['id']}", json={"status": "Maybe"})
    assert bad_status.status_code == 422

    empty_source = client.put(f"/api/loot/{drop['id']}", json={"source": "  "})
    assert empty_source.status_code == 422


# --- loot deletion & data clear ----------------------------------------------


def test_delete_loot_rows(tmp_path: Path) -> None:
    conn = db.connect(str(tmp_path / "data/gorgon.db"))
    db.migrate(conn)
    client, drops = _replay_and_drops(tmp_path)

    single = client.post("/api/loot/rows/delete", json={"ids": [drops[0]["id"]]})
    assert single.status_code == 200, single.text
    assert single.json() == {"deleted": 1}
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == len(drops) - 1

    many = client.post("/api/loot/rows/delete", json={"ids": [drops[1]["id"], drops[2]["id"]]})
    assert many.status_code == 200
    assert many.json() == {"deleted": 2}
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == len(drops) - 3
    conn.close()


def test_delete_loot_rows_validates(tmp_path: Path) -> None:
    client, drops = _replay_and_drops(tmp_path)
    conn = db.connect(str(tmp_path / "data/gorgon.db"))
    db.migrate(conn)

    for bad in ([], ["x"], [0], [1, "a"], {}):
        resp = client.post("/api/loot/rows/delete", json={"ids": bad})
        assert resp.status_code == 422

    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == len(drops)
    conn.close()


def test_clear_data_wipes_all(tmp_path: Path) -> None:
    client, drops = _replay_and_drops(tmp_path)
    conn = db.connect(str(tmp_path / "data/gorgon.db"))
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == len(drops)
    assert conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"] >= 1

    resp = client.post("/api/data/clear")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["cleared"]["loot_drops"] == len(drops)

    for table in ("sessions", "raw_events", "sources", "loot", "loot_drops", "loot_overrides", "items"):
        assert conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM schema_migrations").fetchone()["c"] == 3
    conn.close()


# --- calibration -------------------------------------------------------------


def test_calibrate_snapshot_and_preview(tmp_path: Path, monkeypatch) -> None:
    import io

    import gorgon_tracker.parsers.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "grab_region", lambda region: Image.new("RGB", (20, 10), color=(120, 90, 60)))
    monkeypatch.setattr(ocr_mod, "raw_capture_text", lambda cfg, region: "Fairy Glen\n42\n")
    client = _client(tmp_path)

    snap_gray = client.get("/api/calibrate/snapshot", params={"x": 0, "y": 0, "w": 20, "h": 10})
    assert snap_gray.status_code == 200
    assert snap_gray.headers["content-type"] == "image/png"
    assert snap_gray.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(snap_gray.content)).mode == "L"

    snap_color = client.get("/api/calibrate/snapshot", params={"x": 0, "y": 0, "w": 20, "h": 10, "color": 1})
    assert snap_color.status_code == 200
    assert Image.open(io.BytesIO(snap_color.content)).mode == "RGB"

    prev = client.get("/api/calibrate/preview", params={"x": 0, "y": 0, "w": 20, "h": 10})
    assert prev.json() == {"text": "Fairy Glen", "raw": "Fairy Glen 42"}


def test_calibrate_screens_lists_monitors(tmp_path: Path, monkeypatch) -> None:
    import gorgon_tracker.parsers.ocr as ocr_mod

    monkeypatch.setattr(
        ocr_mod,
        "list_monitors",
        lambda: [
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 1920, "top": 0, "width": 1920, "height": 1080},
        ],
    )
    resp = _client(tmp_path).get("/api/calibrate/screens")
    assert resp.status_code == 200
    assert resp.json()["monitors"][1] == {"left": 0, "top": 0, "width": 1920, "height": 1080}


def test_calibrate_endpoints_surface_capture_failure(tmp_path: Path, monkeypatch) -> None:
    import gorgon_tracker.parsers.ocr as ocr_mod

    def boom(*args, **kwargs):
        raise ocr_mod.ScreenCaptureError("no interactive display available")

    monkeypatch.setattr(ocr_mod, "grab_region", boom)
    monkeypatch.setattr(ocr_mod, "raw_capture_text", boom)
    monkeypatch.setattr(ocr_mod, "list_monitors", boom)
    client = _client(tmp_path)

    snap = client.get("/api/calibrate/snapshot", params={"x": 0, "y": 0, "w": 20, "h": 10})
    assert snap.status_code == 502
    assert "display" in snap.json()["detail"]

    prev = client.get("/api/calibrate/preview", params={"x": 0, "y": 0, "w": 20, "h": 10})
    assert prev.status_code == 502

    screens = client.get("/api/calibrate/screens")
    assert screens.status_code == 502


def test_calibrate_region_persists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = _config_file(tmp_path)
    client = _client(tmp_path, config_file)

    resp = client.post("/api/calibrate/region", json={"kind": "zones", "region": [5, 6, 70, 80]})
    assert resp.status_code == 200
    assert resp.json()["config"]["ocr"]["zones"]["region"] == [5, 6, 70, 80]

    bad = client.post("/api/calibrate/region", json={"kind": "zones", "region": [1, 2]})
    assert bad.status_code == 422


# --- file browser ------------------------------------------------------------


def test_files_list(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    resp = _client(tmp_path).get("/api/files", params={"path": str(tmp_path)})
    assert resp.status_code == 200
    names = {e["name"]: e for e in resp.json()["entries"]}
    assert "a.txt" in names and names["a.txt"]["is_dir"] is False
    assert names["sub"]["is_dir"] is True


# --- name lists --------------------------------------------------------------


def test_names_status_reports_bundled_snapshot(tmp_path: Path) -> None:
    resp = _client(tmp_path).get("/api/names")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["zones_count"] >= 10
    assert body["monsters_count"] >= 10
    assert body["zones_source"] in ("user", "bundled")
    assert body["zones_path"].endswith("zones.txt")


def test_names_update_writes_user_dir(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "names"
    config_file = tmp_path / "gorgon-tracker.toml"
    config_file.write_text(f"[db]\npath = 'data/gorgon.db'\n[names]\ndata_dir = '{data_dir}'\n")
    client = _client(tmp_path, config_file)

    def fake_update(out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "zones.txt").write_text("Serbule\n", encoding="utf-8")
        (out_dir / "monsters.txt").write_text("Wolf\n", encoding="utf-8")
        return {"zones": 1, "monsters": 1, "path": str(out_dir)}

    monkeypatch.setattr("gorgon_tracker.names.update_names_files", fake_update)
    resp = client.post("/api/names/update")
    assert resp.status_code == 200
    assert resp.json() == {"zones": 1, "monsters": 1, "path": str(data_dir)}

    info = client.get("/api/names").json()
    assert info["zones_source"] == "user"
    assert info["zones_count"] == 1


def test_names_update_surfaces_fetch_failure(tmp_path: Path, monkeypatch) -> None:
    from urllib.error import URLError

    def boom(out_dir: Path):
        raise URLError("connection refused")

    monkeypatch.setattr("gorgon_tracker.names.update_names_files", boom)
    resp = _client(tmp_path).post("/api/names/update")
    assert resp.status_code == 502
    assert "wiki name fetch failed" in resp.json()["detail"]