"""The local publish flow: plan the payload, push to a remote, audit locally."""

import json
from pathlib import Path

from gorgon_tracker import db, publish
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.replay import expand_inputs, run_replay

from . import scenario


def _populated(tmp_path: Path) -> Path:
    files = scenario.build(tmp_path)
    conn = db.connect(tmp_path / "local.db")
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.player_log, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    conn.close()
    return tmp_path / "local.db"


def _ids(conn) -> list[int]:
    rows = conn.execute("SELECT id FROM loot_drops ORDER BY id").fetchall()
    return [int(r["id"]) for r in rows]


def test_plan_payload_carries_effective_override(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    conn = db.connect(db_path)
    try:
        ids = _ids(conn)
        # The deer-skin row shares its encounter with the Skinning activity.
        skin_id = conn.execute(
            "SELECT id FROM loot_drops WHERE item = 'Crude Animal Skin'"
        ).fetchone()["id"]
        db.upsert_loot_override(conn, skin_id, status="Orphaned", activity="Harvesting")

        planned = publish.plan_payload(conn, ids)
        assert len(planned) == len(ids)
        assert all("payload" in item and "loot_drop_id" in item for item in planned)

        first = next(p for p in planned if p["loot_drop_id"] == skin_id)
        assert first["payload"]["status"] == "Orphaned"
        assert first["payload"]["activity"] == "Harvesting"
        assert first["payload"]["captured_at"] > 0
        # Encounter identity rides along so remote drop rates keep working.
        assert "encounter_uuid" in first["payload"]
        # The encounter's activity ledger rides along for remote rate denominators.
        acts = first["payload"]["encounter_activities"]
        assert {"Looting", "Skinning"}.issubset({a["activity"] for a in acts})
    finally:
        conn.close()


def test_publish_rows_records_audit_and_results(tmp_path: Path, monkeypatch) -> None:
    db_path = _populated(tmp_path)
    conn = db.connect(db_path)
    try:
        ids = _ids(conn)

        def fake_push(url, token, rows):
            return {
                "received": len(rows),
                "created": len(rows),
                "replaced": 0,
                "actions": ["created"] * len(rows),
            }

        monkeypatch.setattr(publish, "push_batch", fake_push)
        results = publish.publish_rows(conn, "https://example.test", "tok", ids)

        assert len(results) == len(ids)
        assert all(r["status"] == "ok" and r["remote_action"] == "created" for r in results)

        for r in results:
            rc = conn.execute(
                "SELECT * FROM loot_publications WHERE loot_drop_id = ?", (r["loot_drop_id"],)
            ).fetchone()
            assert rc is not None and rc["status"] == "ok"
            payload = json.loads(rc["payload_json"])
            assert payload["item"]
    finally:
        conn.close()


def test_publish_rows_records_failures(tmp_path: Path, monkeypatch) -> None:
    db_path = _populated(tmp_path)
    conn = db.connect(db_path)
    try:
        ids = _ids(conn)

        def boom(url, token, rows):
            raise RuntimeError("publish server unreachable")

        monkeypatch.setattr(publish, "push_batch", boom)
        results = publish.publish_rows(conn, "https://example.test", "tok", ids)

        assert all(r["status"] == "failed" for r in results)
        rc = conn.execute(
            "SELECT status, message FROM loot_publications WHERE loot_drop_id = ?", (ids[0],)
        ).fetchone()
        assert rc["status"] == "failed" and "unreachable" in rc["message"]
    finally:
        conn.close()


def test_web_publish_endpoint_gated_and_run(tmp_path: Path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from gorgon_tracker.web import build_web_app

    db_path = _populated(tmp_path)
    cfg_path = tmp_path / "gorgon-tracker.toml"
    cfg_path.write_text(
        "[db]\npath = 'data/gorgon.db'\n"
        "[publish]\nenabled = true\nurl = 'https://loot.example.test'\ntoken = 'tok'\n"
    )
    client = TestClient(build_web_app(str(db_path), str(cfg_path)))

    conn = db.connect(db_path)
    try:
        ids = _ids(conn)
    finally:
        conn.close()

    # Not configured (defaults) -> 403.
    nodb_cfg = tmp_path / "nodbi.toml"
    nodb_cfg.write_text("[db]\npath = 'data/gorgon.db'\n")
    plain = TestClient(build_web_app(str(db_path), str(nodb_cfg)))
    assert plain.post("/api/publish", json={"ids": ids}).status_code == 403

    def fake_push(url, token, rows):
        return {
            "received": len(rows),
            "created": len(rows),
            "replaced": 0,
            "actions": ["created"] * len(rows),
        }

    monkeypatch.setattr("gorgon_tracker.publish.push_batch", fake_push)
    bad_id = client.post("/api/publish", json={"ids": [0]})
    assert bad_id.status_code == 422

    resp = client.post("/api/publish", json={"ids": ids})
    assert resp.status_code == 200
    body = resp.json()
    assert body["published"] == len(ids)
    assert body["created"] == len(ids)
    assert body["failed"] == 0

    # Status reports the publish target as configured without leaking the token.
    status = client.get("/api/status").json()
    assert status["publish"]["configured"] is True
    assert status["publish"]["url"] == "https://loot.example.test"
    assert "token" not in status["publish"]

    # Loot rows now carry the published badge.
    loot = client.get("/api/loot").json()
    assert all(r["published"] is True and r["published_at"] for r in loot)