from pathlib import Path

import pytest

from gorgon_tracker import db
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.replay import expand_inputs, run_replay

from . import scenario

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

serve = pytest.importorskip("gorgon_tracker.serve")


def _populated(tmp_path: Path):
    files = scenario.build(tmp_path)
    conn = db.connect(tmp_path / "web.db")
    db.migrate(conn)
    run_replay(
        conn,
        TrackerConfig(),
        expand_inputs([files.capture_json, files.chat_log, files.zones_csv, files.targets_csv]),
    )
    conn.close()
    return tmp_path / "web.db"


def test_endpoints_serve_read_only(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").json()["service"] == "gorgon-tracker"

    sessions = client.get("/sessions").json()
    assert len(sessions) == 1

    summary = client.get("/summary").json()
    assert len(summary) == 4

    rates = client.get("/drop-rates").json()
    assert len(rates) == 4
    filtered = client.get("/drop-rates", params={"monster": "Dire Wolf"}).json()
    assert len(filtered) == 2
    assert all(r["monster"] == "Dire Wolf" for r in filtered)

    loot = client.get("/loot", params={"limit_rows": 2}).json()
    assert len(loot) == 2
    assert loot[0]["item"] in {"Bat Wing", "Bat Guano", "Wolf Pelt", "Ground Twig"}