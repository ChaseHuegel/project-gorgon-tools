import threading
import time
from pathlib import Path

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.sources import chat_tail

from . import scenario


def _loot_line(seconds: float, item: str, amount: int = 1) -> str:
    return f"{scenario.local_wall(seconds)} [Status] {item} x{amount} added to inventory."


def _cfg(tmp_path: Path) -> TrackerConfig:
    cfg = TrackerConfig()
    cfg.chat.log_dir = str(tmp_path / "chats")
    cfg.chat.poll_interval_s = 0.05
    return cfg


def _capture(cfg: TrackerConfig, duration_s: float = 0.15) -> tuple[list, threading.Event, threading.Thread]:
    collected: list = []
    stop = threading.Event()
    thread = threading.Thread(target=chat_tail.produce, args=(cfg, collected.append, stop), daemon=True)
    thread.start()
    _settle(duration_s)
    return collected, stop, thread


def _settle(duration_s: float) -> None:
    time.sleep(duration_s)


def test_newest_log_none_in_empty_dir(tmp_path: Path) -> None:
    (tmp_path / "chats").mkdir()
    assert chat_tail.newest_log(tmp_path / "chats") is None


def test_tail_starts_at_end_and_emits_appends_only(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    log = chats / "session.log"
    log.write_text(_loot_line(1.0, "Old Bone") + "\ngarbage\n")

    collected, stop, thread = _capture(_cfg(tmp_path))
    with log.open("a") as fh:
        fh.write(_loot_line(5.0, "Bat Wing", 2) + "\n")
        fh.write("noise\n")
        fh.write(_loot_line(5.0, "Rat Jaw") + "\n")
    _settle(0.2)

    stop.set()
    thread.join(timeout=3)
    items = [e.item for e in collected]
    assert items == ["Bat Wing", "Rat Jaw"]
    assert all(hasattr(e, "amount") and e.amount >= 1 for e in collected)


def test_rotation_parses_new_file_in_full(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    first = chats / "a.log"
    first.write_text("x\n")
    collected, stop, thread = _capture(_cfg(tmp_path))

    time.sleep(0.1)
    second = chats / "b.log"
    second.write_text(_loot_line(3.0, "Wolf Pelt") + "\n" + _loot_line(3.0, "Bacon") + "\n")

    _settle(0.3)
    stop.set()
    thread.join(timeout=3)
    items = [e.item for e in collected]
    assert items == ["Wolf Pelt", "Bacon"]


def test_rotation_does_not_reemit_old_file(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    first = chats / "a.log"
    first.write_text(_loot_line(1.0, "Old Bone") + "\n")
    collected, stop, thread = _capture(_cfg(tmp_path))

    # Replace a.log in place (same name, new inode) with fresh content.
    replaced = chats / "a.log.new"
    replaced.write_text(_loot_line(6.0, "Fresh Meat") + "\n")
    replaced.replace(chats / "a.log")

    _settle(0.3)
    stop.set()
    thread.join(timeout=3)
    items = [e.item for e in collected]
    # Old content was skipped (tail-from-end on initial file); rotated file fully parsed.
    assert "Old Bone" not in items
    assert "Fresh Meat" in items


def test_tail_from_start_reads_entire_file(tmp_path: Path) -> None:
    chats = tmp_path / "chats"
    chats.mkdir()
    log = chats / "session.log"
    log.write_text(_loot_line(1.0, "Old Bone") + "\n" + _loot_line(2.0, "More Bone") + "\n")
    cfg = _cfg(tmp_path)
    cfg.chat.tail_from_start = True
    collected, stop, thread = _capture(cfg)
    stop.set()
    thread.join(timeout=3)
    assert [e.item for e in collected] == ["Old Bone", "More Bone"]