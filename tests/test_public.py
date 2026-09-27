"""The public surface (``gorgon-tracker serve``) is read-only by default.

It must never mount control endpoints; the only write is the token-protected
publish ingest, and only when ``[serve]`` configures it explicitly.
"""

from pathlib import Path

import pytest

from gorgon_tracker import db, public
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.replay import expand_inputs, run_replay

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from . import scenario  # noqa: E402


def _toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in value) + "]"
    return str(value)


def _write_cfg(path: Path, body: dict) -> None:
    lines = ["[db]", "path = 'data/x.db'"]
    for section, values in body.items():
        lines.append(f"[{section}]")
        for key, value in values.items():
            lines.append(f"{key} = {_toml(value)}")
    path.write_text("\n".join(lines) + "\n")


def _populated(tmp_path: Path) -> Path:
    files = scenario.build(tmp_path)
    conn = db.connect(tmp_path / "public.db")
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.capture_json, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    conn.close()
    return tmp_path / "public.db"


def _public_app(tmp_path: Path, *, ingest: bool = False, static_dir: Path | None = None):
    db_path = _populated(tmp_path)
    # Force an explicit (non-existent) SPA dir so behaviour is deterministic
    # whether or not the frontend was built in this checkout.
    spa = static_dir or tmp_path / "no-spa"
    if not ingest:
        return TestClient(public.build_public_app(str(db_path), None, static_dir=spa))
    cfg = tmp_path / "serve.toml"
    _write_cfg(cfg, {"serve": {"ingest_enabled": True, "ingest_token": "sekret"}})
    return TestClient(public.build_public_app(str(db_path), str(cfg), static_dir=spa))


def test_public_app_exposes_no_control_routes(tmp_path: Path) -> None:
    client = _public_app(tmp_path)
    paths = set(client.app.openapi()["paths"])

    for path in (
        "/api/status",
        "/api/chat/tail",
        "/api/config",
        "/api/daemon/start",
        "/api/daemon/stop",
        "/api/ports/discover",
        "/api/replay",
        "/api/migrate",
        "/api/export",
        "/api/export/analysis",
        "/api/loot/{loot_drop_id}",
        "/api/loot/rows/delete",
        "/api/data/clear",
        "/api/names",
        "/api/names/update",
        "/api/catalog",
        "/api/catalog/update",
        "/api/calibrate",
        "/api/calibrate/screens",
        "/api/calibrate/region",
        "/api/files",
        "/api/publish",
    ):
        assert path not in paths, f"control route leaked onto the public app: {path}"

    for path in (
        "/api/health",
        "/api/sessions",
        "/api/distinct",
        "/api/summary",
        "/api/drop-rates",
        "/api/loot",
        "/api/search",
        "/api/stats",
        "/api/stream/loot",
        "/api/stream/events",
        "/api/stream/status",
    ):
        assert path in paths, f"read route missing from the public app: {path}"


def test_public_app_read_only_serves_data(tmp_path: Path) -> None:
    client = _public_app(tmp_path)
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/summary").json()
    loot = client.get("/api/loot").json()
    assert loot and "id" in loot[0]


def test_ingest_is_disabled_by_default(tmp_path: Path) -> None:
    client = _public_app(tmp_path)
    assert client.post("/api/ingest/loot", json={"rows": []}).status_code == 404


def _valid_row(**overrides):
    row = {
        "captured_at": 1_700_000_000_000,
        "source": "Giant Bat",
        "item": "Bat Guano",
        "amount": 2,
        "activity": "Looting",
        "zone": "Old Graveyard",
        "status": "Linked",
        "lag_ms": 5,
        "linked_via": "monster",
        "monster_name": "Giant Bat",
        "monster_lag_ms": 1,
        "corroborated_by_search": False,
        "missed": False,
    }
    row.update(overrides)
    return row


def test_ingest_requires_token(tmp_path: Path) -> None:
    client = _public_app(tmp_path, ingest=True)

    no_auth = client.post("/api/ingest/loot", json={"rows": [_valid_row()]})
    assert no_auth.status_code == 401

    bad_token = client.post(
        "/api/ingest/loot",
        json={"rows": [_valid_row()]},
        headers={"Authorization": "Bearer nope"},
    )
    assert bad_token.status_code == 401


def test_ingest_validates_rows(tmp_path: Path) -> None:
    client = _public_app(tmp_path, ingest=True)
    headers = {"Authorization": "Bearer sekret"}

    missing = client.post("/api/ingest/loot", json={"rows": [{"source": "X"}]}, headers=headers)
    assert missing.status_code == 422

    bad_amount = client.post("/api/ingest/loot", json={"rows": [_valid_row(amount=0)]}, headers=headers)
    assert bad_amount.status_code == 422

    unknown = client.post("/api/ingest/loot", json={"rows": [_valid_row(bogus=1)]}, headers=headers)
    assert unknown.status_code == 422

    too_many = client.post("/api/ingest/loot", json={"rows": [_valid_row()] * 501}, headers=headers)
    assert too_many.status_code == 422


def test_ingest_creates_then_replaces_on_natural_key(tmp_path: Path) -> None:
    client = _public_app(tmp_path, ingest=True)
    headers = {"Authorization": "Bearer sekret"}

    first = client.post("/api/ingest/loot", json={"rows": [_valid_row()]}, headers=headers)
    assert first.status_code == 200
    assert first.json() == {"received": 1, "created": 1, "replaced": 0, "actions": ["created"]}

    # Re-publish with a corrected activity replaces the public copy (idempotent).
    second = client.post(
        "/api/ingest/loot",
        json={"rows": [_valid_row(activity="Skinning")]},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json() == {"received": 1, "created": 0, "replaced": 1, "actions": ["replaced"]}

    loot = client.get("/api/loot").json()
    published = [r for r in loot if r["captured_at"] == _valid_row()["captured_at"]]
    assert len(published) == 1
    assert published[0]["activity"] == "Skinning"


def test_ingest_carries_encounter_identity_for_rates(tmp_path: Path) -> None:
    client = _public_app(tmp_path, ingest=True)
    headers = {"Authorization": "Bearer sekret"}

    row = _valid_row(source="Test Goblin", item="Test Fang", amount=1, encounter_uuid="gob-1")
    resp = client.post(
        "/api/ingest/loot",
        json={
            "rows": [
                row,
                {**row, "item": "Test Pelt", "amount": 1},
            ]
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["created"] == 2

    rates = client.get("/api/drop-rates", params={"monster": "Test Goblin"}).json()
    assert len(rates) == 2
    assert all(r["encounters"] == 1 and r["drop_rate"] == 1.0 for r in rates)


def test_public_spa_served_with_fallback(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>public</html>")
    (static / "assets").mkdir()
    (static / "assets" / "app.js").write_text("console.log('public')")

    client = TestClient(public.build_public_app(str(tmp_path / "nope.db"), None, static_dir=static))

    assert client.get("/").text == "<html>public</html>"
    assert client.get("/loot").text == "<html>public</html>"
    assert client.get("/assets/app.js").text == "console.log('public')"
    assert client.get("/api/nope").status_code == 404


def test_public_app_index_when_spa_absent(tmp_path: Path) -> None:
    client = _public_app(tmp_path)
    body = client.get("/").json()
    assert body["service"] == "gorgon-tracker"
    assert "endpoints" in body


def test_build_public_app_requires_token_when_ingest_enabled(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    cfg = tmp_path / "serve.toml"
    _write_cfg(cfg, {"serve": {"ingest_enabled": True, "ingest_token": ""}})
    with pytest.raises(ValueError):
        public.build_public_app(str(db_path), str(cfg))


def test_read_only_serve_survives_duplicate_capture_drops(tmp_path: Path) -> None:
    """A local capture DB may hold duplicate natural keys. Read-only serve must launch."""
    db_path = tmp_path / "capture.db"
    conn = db.connect(db_path)
    db.migrate(conn)
    session_id = db.new_session(conn, platform="linux")
    import gorgon_tracker.db as db_mod

    db_mod.insert_loot_drop(
        conn, session_id, None, 1_000, "Giant Bat", "Bat Guano", 1, "Looting", "Old Graveyard", "Linked", 0
    )
    db_mod.insert_loot_drop(
        conn, session_id, None, 1_000, "Giant Bat", "Bat Guano", 1, "Looting", "Old Graveyard", "Linked", 0
    )
    conn.commit()
    conn.close()

    spa = tmp_path / "no-spa"
    app = TestClient(public.build_public_app(str(db_path), None, static_dir=spa))
    assert app.get("/api/health").json()["status"] == "ok"
    assert len(app.get("/api/loot").json()) == 2


def test_ingest_enabled_refuses_duplicate_capture_db(tmp_path: Path) -> None:
    db_path = tmp_path / "capture.db"
    conn = db.connect(db_path)
    db.migrate(conn)
    session_id = db.new_session(conn, platform="linux")
    import gorgon_tracker.db as db_mod

    db_mod.insert_loot_drop(
        conn, session_id, None, 1_000, "Giant Bat", "Bat Guano", 1, "Looting", "Old Graveyard", "Linked", 0
    )
    db_mod.insert_loot_drop(
        conn, session_id, None, 1_000, "Giant Bat", "Bat Guano", 1, "Looting", "Old Graveyard", "Linked", 0
    )
    conn.commit()
    conn.close()

    cfg = tmp_path / "serve.toml"
    _write_cfg(cfg, {"serve": {"ingest_enabled": True, "ingest_token": "sekret"}})
    with pytest.raises(ValueError, match="duplicate"):
        public.build_public_app(str(db_path), str(cfg), static_dir=tmp_path / "no-spa")