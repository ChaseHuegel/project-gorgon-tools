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


def test_analysis_endpoints_and_filters(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    distinct = client.get("/distinct").json()
    assert "Giant Bat" in distinct["sources"]
    assert "Dire Wolf" in distinct["sources"]
    assert "Bat Guano" in distinct["items"]
    assert "Looting" in distinct["activities"]
    assert any(z in distinct["zones"] for z in ("Old Graveyard", "Fairy Glen"))

    search = client.get("/search", params={"q": "Bat"}).json()
    assert any(s["name"] == "Giant Bat" for s in search["sources"])
    assert any(i["name"] == "Bat Guano" for i in search["items"])
    activity_hits = client.get("/search", params={"q": "Loot"}).json()
    assert any(a["name"] == "Looting" for a in activity_hits["activities"])

    source = client.get("/source/Giant Bat").json()
    assert source["source"] == "Giant Bat"
    assert any(i["item"] == "Bat Guano" for i in source["items"])
    assert source["zones"]

    item = client.get("/item/Bat Guano").json()
    assert item["item"] == "Bat Guano"
    assert any(s["monster"] == "Giant Bat" for s in item["sources"])

    activity = client.get("/activity/Looting").json()
    assert activity["activity"] == "Looting"
    assert activity["sources"] and activity["items"] and activity["zones"]

    sources = client.get("/analysis/sources").json()
    assert any(m["monster"] == "Giant Bat" for m in sources)
    zones = client.get("/analysis/zones").json()
    assert any(z["zone"] == "Old Graveyard" for z in zones)
    items = client.get("/analysis/items").json()
    assert any(i["item"] == "Bat Guano" for i in items)

    zoned = client.get("/drop-rates", params={"zone": "Old Graveyard"}).json()
    assert zoned and all(r["monster"] == "Giant Bat" for r in zoned)
    ranked = client.get("/drop-rates", params={"sort": "drops", "order": "desc", "limit": 2}).json()
    assert len(ranked) == 2
    assert ranked[0]["drops"] >= ranked[1]["drops"]
    assert len(client.get("/summary", params={"source": "Dire"}).json()) > 0


def test_loot_endpoint_exposes_evidence_and_filters(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    all_rows = client.get("/loot", params={"limit_rows": 100}).json()
    assert len(all_rows) == 4
    by_item = {r["item"]: r for r in all_rows}
    for key in ("linked_via", "monster_name", "monster_lag_ms", "target_name", "target_lag_ms", "overridden"):
        assert key in by_item["Bat Guano"]

    # The Ground Twig is target-linked and corroborated by a same-name corpse search.
    twig = by_item["Ground Twig"]
    assert twig["linked_via"] == "target"
    assert twig["corroborated_by_search"] is True
    assert twig["activity"] == "Looting"

    assert len(client.get("/loot", params={"linked_via": "monster"}).json()) == 3
    assert len(client.get("/loot", params={"confidence": "high"}).json()) == 3
    assert len(client.get("/loot", params={"confidence": "uncertain"}).json()) == 1


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


def test_stream_endpoints_served_under_api_prefix(tmp_path: Path) -> None:
    """Regression: SSE routes must live at /api/stream/* (as the SPA calls them)."""
    app = serve.build_app(_populated(tmp_path))
    paths = set(app.openapi()["paths"])

    for path in ("/api/stream/loot", "/api/stream/events", "/api/stream/status"):
        assert path in paths, f"{path} is not a registered route"

    assert not any(p in paths for p in ("/stream/loot", "/stream/status"))


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