import threading
import time
from pathlib import Path

from gorgon_tracker import db, pipeline
from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.sources import tshark_live

from . import scenario


def _live_cfg(tmp_path: Path) -> TrackerConfig:
    cfg = TrackerConfig()
    cfg.db.path = str(tmp_path / "live.db")
    cfg.capture.enabled = False
    cfg.ocr.enabled = False
    cfg.chat.tail = True
    cfg.chat.log_dir = str(tmp_path / "chats")
    cfg.chat.tail_from_start = True
    cfg.chat.poll_interval_s = 0.02
    return cfg


def _line(seconds: float, item: str, amount: int = 1) -> str:
    return f"{scenario.local_wall(seconds)} [Status] {item} x{amount} added to inventory."


def test_pipeline_chat_only_end_to_end(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    log = chats / "session.log"
    log.write_text("garbage\n")

    cfg = _live_cfg(tmp_path)
    stop = threading.Event()
    result: dict = {}

    def on_session(session_id: int) -> None:
        result["session_id"] = session_id

    thread = threading.Thread(
        target=lambda: result.update(
            session=(
                pipeline.run_pipeline(cfg, "linux", stop, on_session=on_session)[0]
            )
        ),
        daemon=True,
    )
    thread.start()
    time.sleep(0.15)

    with log.open("a") as fh:
        fh.write(_line(1.0, "Bat Wing", 2) + "\n")
        fh.write(_line(1.0, "Rat Jaw") + "\n")
    time.sleep(0.3)

    stop.set()
    thread.join(timeout=5)

    conn = db.connect(cfg.db.path)
    db.migrate(conn)
    row = conn.execute("SELECT COUNT(*) c FROM loot_drops WHERE status='Linked'").fetchone()
    assert row["c"] == 2
    amounts = conn.execute("SELECT amount FROM loot_drops ORDER BY item").fetchall()
    assert [r["amount"] for r in amounts] == [2, 1]
    assert conn.execute("SELECT COUNT(*) c FROM loot").fetchone()["c"] == 2
    encounters = conn.execute("SELECT COUNT(*) c FROM encounters").fetchone()["c"]
    assert encounters == 1
    # Pipeline-owned session is closed when the run finishes.
    assert db.open_session(conn) is None
    conn.close()


def test_pipeline_commits_drops_live_before_stop(tmp_path: Path) -> None:
    """A bury flush must be committed so a second connection sees it pre-stop."""
    chats = tmp_path / "chats"
    chats.mkdir()
    log = chats / "session.log"
    log.write_text("garbage\n")

    cfg = _live_cfg(tmp_path)
    stop = threading.Event()
    thread = threading.Thread(target=lambda: pipeline.run_pipeline(cfg, "linux", stop), daemon=True)
    thread.start()
    time.sleep(0.15)

    with log.open("a") as fh:
        fh.write(_line(1.0, "Bat Wing", 2) + "\n")
        fh.write(f"{scenario.local_wall(1.1)} [Status] You bury the corpse.\n")
    time.sleep(1.6)  # > the 1s commit interval so the bury-flushed drop lands

    conn = db.connect(cfg.db.path)
    db.migrate(conn)
    live_count = conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"]
    conn.close()
    assert live_count == 1, "loot_drops should be committed and visible before stop"

    stop.set()
    thread.join(timeout=5)

    conn = db.connect(cfg.db.path)
    db.migrate(conn)
    assert conn.execute("SELECT COUNT(*) c FROM loot_drops").fetchone()["c"] == 1
    conn.close()


def test_pipeline_reports_no_empty_producers(tmp_path: Path, monkeypatch) -> None:
    cfg = _live_cfg(tmp_path)
    emitted: list = []

    def fake_emit(event: object) -> None:
        emitted.append(event)

    producers = pipeline.build_producers(cfg, fake_emit)
    names = [name for name, _ in producers]
    assert "chat" in names
    assert "packet" not in names  # capture disabled
    assert "zone" not in names and "target" not in names  # ocr disabled


def test_pipeline_registers_packet_when_filter_not_yet_resolvable(monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.capture.enabled = True
    cfg.chat.tail = False
    cfg.ocr.enabled = False

    def no_filter(_cfg: TrackerConfig) -> str:
        raise RuntimeError("no filter")

    monkeypatch.setattr(tshark_live, "build_bpf_filter", no_filter)

    emitted: list = []
    names = [name for name, _ in pipeline.build_producers(cfg, emitted.append)]
    # Packet capture must still be registered so discovery can retry at produce time.
    assert "packet" in names