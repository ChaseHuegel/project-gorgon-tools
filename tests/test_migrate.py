import json
import sqlite3
from pathlib import Path

from gorgon_tracker import db
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.migrate import import_bundle

from . import scenario


def _connect(tmp_path: Path) -> sqlite3.Connection:
    conn = db.connect(tmp_path / "migrate.db")
    db.migrate(conn)
    return conn


def test_migrate_legacy_loot_csv(tmp_path: Path) -> None:
    loot_csv = tmp_path / "loot.csv"
    loot_csv.write_text(
        "Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone\n"
        f"{scenario.local_wall(3.5)},Rat,enc-a,Skinning,Bone,1,Linked,0.5,Ilmari\n"
        "1/24/2026 5:49:21 PM,Wolf,enc-b,Looting,Pelt,2,Linked,1.2,Fairy Glen\n"
        f"{scenario.local_wall(5.0)},Ground/Unknown,enc-c,Looting,Dirt,1,Orphaned,1.79769313486232E+308,Phantom Ilmari Desert\n"
        f"{scenario.local_wall(6.0)},Ground/Unknown,enc-d,Looting,Grass,1,Orphaned,nonsense,Fairy Glen\n"
    )
    conn = _connect(tmp_path)
    stats = import_bundle(conn, TrackerConfig(), loot_csv)
    assert stats["kind"] == "loot"
    assert stats["imported"] == 4

    rows = conn.execute(
        "SELECT source, item, encounter_id, lag_ms FROM loot_drops ORDER BY captured_at"
    ).fetchall()
    assert len(rows) == 4
    assert rows[0]["source"] == "Rat"
    assert rows[0]["item"] == "Bone"
    assert rows[0]["encounter_id"] != rows[1]["encounter_id"]
    by_source = {r["source"]: r["lag_ms"] for r in rows}
    assert by_source["Ground/Unknown"] == 0
    assert by_source["Wolf"] == 1200
    assert conn.execute("SELECT COUNT(*) c FROM encounters").fetchone()["c"] == 4
    assert conn.execute("SELECT COUNT(*) c FROM loot").fetchone()["c"] == 4
    conn.close()


def test_migrate_zones_and_targets(tmp_path: Path) -> None:
    conn = _connect(tmp_path)
    cfg = TrackerConfig()

    zones = tmp_path / "zones.csv"
    zones.write_text("Time,Text\n" + f"{scenario.utc_wall(1.0)},Old Graveyard\n")
    zones_stats = import_bundle(conn, cfg, zones)
    assert zones_stats["kind"] == "zones"
    assert zones_stats["imported"] == 1

    targets = tmp_path / "targets.csv"
    targets.write_text("Time,Text\n" + f"{scenario.utc_wall(1.5)},Rat\n")
    targets_stats = import_bundle(conn, cfg, targets)
    assert targets_stats["kind"] == "targets"
    assert targets_stats["imported"] == 1

    assert conn.execute("SELECT COUNT(*) c FROM zone_changes").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM target_sightings").fetchone()["c"] == 1
    conn.close()


def test_migrate_parsed_chat_json(tmp_path: Path) -> None:
    chat_json = tmp_path / "parsed-chat.txt"
    payload = [
        {"Time": "/Date(1768161600000)/", "EventType": "Loot", "ItemName": "Bone", "Amount": 1},
        {"Time": "/Date(1768161600000)/", "EventType": "Bury"},
    ]
    chat_json.write_text(json.dumps(payload))

    conn = _connect(tmp_path)
    stats = import_bundle(conn, TrackerConfig(), chat_json)
    assert stats["kind"] == "chat-json"
    assert stats["imported"] == 2
    assert conn.execute("SELECT COUNT(*) c FROM loot").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM burials").fetchone()["c"] == 1
    conn.close()


def test_migrate_parsed_packets_json(tmp_path: Path) -> None:
    packets_json = tmp_path / "parsed-packets.txt"
    payload = [
        {"Time": "/Date(1768161600000)/", "Monster": "Rat", "CanSkin": True, "CanButcher": False, "CanExtract": False}
    ]
    packets_json.write_text(json.dumps(payload))

    conn = _connect(tmp_path)
    stats = import_bundle(conn, TrackerConfig(), packets_json)
    assert stats["kind"] == "packets-json"
    assert stats["imported"] == 1
    row = conn.execute("SELECT monster, can_skin FROM sources").fetchone()
    assert row["monster"] == "Rat"
    assert row["can_skin"] == 1
    conn.close()