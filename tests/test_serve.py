import json
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
    assert "id" in loot[0]


@pytest.mark.anyio
async def test_stream_loot_yields_new_rows(tmp_path: Path) -> None:
    from gorgon_tracker.serve import _DB
    from gorgon_tracker.stream import loot_stream

    db_path = _populated(tmp_path)
    db = _DB(str(db_path))

    frames = [f async for f in loot_stream(db, once=True, poll_s=0)]
    assert frames, "expected at least one loot frame"
    import json

    payload = json.loads(_data_of(frames[0]))
    assert "id" in payload
    assert "item" in payload
    assert "event: loot" in frames[0]


@pytest.mark.anyio
async def test_stream_status_yields_counts(tmp_path: Path) -> None:
    from gorgon_tracker.serve import _DB
    from gorgon_tracker.stream import status_stream

    db_path = _populated(tmp_path)
    db = _DB(str(db_path))

    frames = [f async for f in status_stream(db, once=True, poll_s=0)]
    assert frames
    payload = json.loads(_data_of(frames[0]))
    assert "open_session_id" in payload
    assert "open_session_counts" in payload
    assert payload["open_session_counts"] is None or isinstance(payload["open_session_counts"], dict)


@pytest.mark.anyio
async def test_stream_resumes_after_since(tmp_path: Path) -> None:
    from gorgon_tracker.serve import _DB
    from gorgon_tracker.stream import loot_stream

    db_path = _populated(tmp_path)
    db = _DB(str(db_path))
    first = [f async for f in loot_stream(db, once=True, poll_s=0)]
    assert first and any("event: loot" in f for f in first)

    newest = int(_id_of(first[-1]))
    resumed = [f async for f in loot_stream(db, since_id=newest, once=True, poll_s=0)]
    assert resumed == []


def _id_of(frame: str) -> str:
    for line in frame.split("\n"):
        if line.startswith("id: "):
            return line[len("id: "):]
    raise AssertionError("no id: line in frame")


def _data_of(frame: str) -> str:
    for line in frame.split("\n"):
        if line.startswith("data: "):
            return line[len("data: "):]
    raise AssertionError("no data: line in frame")