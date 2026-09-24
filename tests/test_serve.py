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

    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/").json()["service"] == "gorgon-tracker"

    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 1

    summary = client.get("/api/summary").json()
    assert len(summary) == 4

    rates = client.get("/api/drop-rates").json()
    assert len(rates) == 4
    filtered = client.get("/api/drop-rates", params={"monster": "Dire Wolf"}).json()
    assert len(filtered) == 2
    assert all(r["monster"] == "Dire Wolf" for r in filtered)

    loot = client.get("/api/loot", params={"limit_rows": 2}).json()
    assert len(loot) == 2
    assert loot[0]["item"] in {"Bat Wing", "Bat Guano", "Wolf Pelt", "Ground Twig"}
    assert "id" in loot[0]


def test_analysis_endpoints_and_filters(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    distinct = client.get("/api/distinct").json()
    assert "Giant Bat" in distinct["sources"]
    assert "Dire Wolf" in distinct["sources"]
    assert "Bat Guano" in distinct["items"]
    assert "Looting" in distinct["activities"]
    assert any(z in distinct["zones"] for z in ("Old Graveyard", "Fairy Glen"))

    search = client.get("/api/search", params={"q": "Bat"}).json()
    assert any(s["name"] == "Giant Bat" for s in search["sources"])
    assert any(i["name"] == "Bat Guano" for i in search["items"])
    activity_hits = client.get("/api/search", params={"q": "Loot"}).json()
    assert any(a["name"] == "Looting" for a in activity_hits["activities"])

    source = client.get("/api/source/Giant Bat").json()
    assert source["source"] == "Giant Bat"
    assert any(i["item"] == "Bat Guano" for i in source["items"])
    assert source["zones"]

    item = client.get("/api/item/Bat Guano").json()
    assert item["item"] == "Bat Guano"
    assert any(s["monster"] == "Giant Bat" for s in item["sources"])

    activity = client.get("/api/activity/Looting").json()
    assert activity["activity"] == "Looting"
    assert activity["sources"] and activity["items"] and activity["zones"]

    sources = client.get("/api/analysis/sources").json()
    assert any(m["monster"] == "Giant Bat" for m in sources)
    zones = client.get("/api/analysis/zones").json()
    assert any(z["zone"] == "Old Graveyard" for z in zones)
    items = client.get("/api/analysis/items").json()
    assert any(i["item"] == "Bat Guano" for i in items)

    zoned_sources = client.get(
        "/api/analysis/sources", params={"zone": "Old Graveyard", "status": "Linked"}
    ).json()
    assert zoned_sources and all(m["monster"] == "Giant Bat" for m in zoned_sources)
    zoned_items = client.get(
        "/api/analysis/items", params={"zone": "Fairy Glen", "item": "Ground Twig", "status": "Linked"}
    ).json()
    assert zoned_items and all(i["item"] == "Ground Twig" for i in zoned_items)
    filtered_zones = client.get(
        "/api/analysis/zones", params={"source": "Dire Wolf", "status": "Linked"}
    ).json()
    assert filtered_zones and any(z["zone"] == "Fairy Glen" for z in filtered_zones)

    zoned = client.get("/api/drop-rates", params={"zone": "Old Graveyard"}).json()
    assert zoned and all(r["monster"] == "Giant Bat" for r in zoned)
    ranked = client.get("/api/drop-rates", params={"sort": "drops", "order": "desc", "limit": 2}).json()
    assert len(ranked) == 2
    assert ranked[0]["drops"] >= ranked[1]["drops"]
    assert len(client.get("/api/summary", params={"source": "Dire"}).json()) > 0


def test_zone_and_stats_endpoints(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    zone = client.get("/api/zone/Old Graveyard").json()
    assert zone["zone"] == "Old Graveyard"
    assert any(s["monster"] == "Giant Bat" for s in zone["sources"])
    assert any(i["item"] == "Bat Guano" for i in zone["items"])
    assert zone["activities"]

    other = client.get("/api/zone/Unknown").json()
    assert other["zone"] == "Unknown"
    assert other["sources"] == []

    stats = client.get("/api/stats").json()
    assert stats["drops"] == 4
    assert stats["quantity"] >= 4
    assert stats["sources"] >= 2
    assert stats["items"] >= 4
    assert stats["zones"] == 2
    assert stats["encounters"] > 0
    assert stats["linked"] == 4
    assert stats["orphaned"] == 0

    filtered = client.get("/api/stats", params={"zone": "Old Graveyard"}).json()
    assert filtered["items"] == 1
    assert filtered["sources"] == 1


def test_drop_rates_since_offset_and_multi(tmp_path: Path) -> None:
    from .scenario import at

    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    all_rates = client.get("/api/drop-rates").json()
    assert all("last_seen" in r for r in all_rates)
    assert all("last_seen" in r for r in client.get("/api/summary").json())

    late = client.get("/api/drop-rates", params={"since": at(25)}).json()
    assert late == []

    mid = client.get("/api/drop-rates", params={"since": at(14)}).json()
    assert 0 < len(mid) < len(all_rates)
    assert all(r["last_seen"] >= at(14) for r in mid)

    multi = client.get("/api/drop-rates", params={"monsters": "Giant Bat, Dire Wolf"}).json()
    assert len(multi) == len(all_rates)
    assert all(r["monster"] in {"Giant Bat", "Dire Wolf"} for r in multi)

    only_bat = client.get("/api/drop-rates", params={"monsters": "Giant Bat"}).json()
    assert len(only_bat) == 2 and all(r["monster"] == "Giant Bat" for r in only_bat)
    assert len(client.get("/api/drop-rates", params={"items": "Bat Guano"}).json()) == 1
    assert len(client.get("/api/drop-rates", params={"monsters": "Giant Bat", "items": "Bat Guano"}).json()) == 1

    page1 = client.get("/api/drop-rates", params={"limit": 2, "offset": 0}).json()
    page2 = client.get("/api/drop-rates", params={"limit": 2, "offset": 2}).json()
    assert len(page1) == 2 and len(page2) == 2
    assert {r["item"] for r in page1} | {r["item"] for r in page2} == {r["item"] for r in all_rates}

    hits = client.get("/api/search", params={"q": "Bat"}).json()
    assert any("last_seen" in s for s in hits["sources"])
    assert any("last_seen" in i for i in hits["items"])


def test_loot_endpoint_exposes_evidence_and_filters(tmp_path: Path) -> None:
    db_path = _populated(tmp_path)
    client = TestClient(serve.build_app(str(db_path)))

    all_rows = client.get("/api/loot", params={"limit_rows": 100}).json()
    assert len(all_rows) == 4
    by_item = {r["item"]: r for r in all_rows}
    for key in ("linked_via", "monster_name", "monster_lag_ms", "target_name", "target_lag_ms", "overridden"):
        assert key in by_item["Bat Guano"]

    # The Ground Twig is target-linked and corroborated by a same-name corpse search.
    twig = by_item["Ground Twig"]
    assert twig["linked_via"] == "target"
    assert twig["corroborated_by_search"] is True
    assert twig["activity"] == "Looting"

    assert len(client.get("/api/loot", params={"linked_via": "monster"}).json()) == 3
    assert len(client.get("/api/loot", params={"confidence": "high"}).json()) == 3
    assert len(client.get("/api/loot", params={"confidence": "uncertain"}).json()) == 1


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