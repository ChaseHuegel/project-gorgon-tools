"""Live tailing tests for the Unity ``Player.log`` source."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.sources import player_log

LOGIN = (
    "[20:00:00] Logged in as character Tester. Time UTC=01/11/2026 20:00:00. "
    "Timezone Offset -01:00:00."
)


def _pickup(seconds: float, item: str, iid: int) -> str:
    sec = int(seconds) % 60
    return f"[20:00:{sec:02d}] LocalPlayer: ProcessAddItem({item}({iid}), -1, True)"


def _cfg(tmp_path: Path) -> TrackerConfig:
    cfg = TrackerConfig()
    cfg.playerlog.path = str(tmp_path / "Player.log")
    cfg.playerlog.poll_interval_s = 0.05
    return cfg


def _capture(cfg: TrackerConfig, duration_s: float = 0.15) -> tuple[list, threading.Event, threading.Thread]:
    collected: list = []
    stop = threading.Event()
    thread = threading.Thread(target=player_log.produce, args=(cfg, collected.append, stop), daemon=True)
    thread.start()
    time.sleep(duration_s)
    return collected, stop, thread


def test_produce_tails_from_end(tmp_path: Path) -> None:
    log = tmp_path / "Player.log"
    log.write_text(LOGIN + "\n" + _pickup(1.0, "OldBone", -1) + "\n")

    collected, stop, thread = _capture(_cfg(tmp_path))
    with log.open("a") as fh:
        fh.write(_pickup(2.0, "BatWing", -2) + "\n")
        fh.write("noise line\n")
    time.sleep(0.2)

    stop.set()
    thread.join(timeout=3)
    items = [e.item for e in collected if hasattr(e, "item")]
    assert items == ["BatWing"]


def test_rotation_reparses_new_file(tmp_path: Path) -> None:
    log = tmp_path / "Player.log"
    log.write_text(LOGIN + "\n" + _pickup(1.0, "OldBone", -1) + "\n")

    collected, stop, thread = _capture(_cfg(tmp_path))
    time.sleep(0.1)

    # Simulate a game relaunch: the file is replaced by a fresh, smaller one.
    log.write_text(LOGIN + "\n" + _pickup(3.0, "RatJaw", -3) + "\n")

    time.sleep(0.3)
    stop.set()
    thread.join(timeout=3)
    items = [e.item for e in collected if hasattr(e, "item")]
    assert items == ["RatJaw"]


def test_backfill_prev_once(tmp_path: Path) -> None:
    prev = tmp_path / "Player-prev.log"
    prev.write_text(LOGIN + "\n" + _pickup(9.0, "PrevSoul", -9) + "\n")
    log = tmp_path / "Player.log"
    log.write_text(LOGIN + "\n" + _pickup(1.0, "NowSoul", -1) + "\n")

    cfg = _cfg(tmp_path)
    cfg.playerlog.backfill_prev = True
    collected: list = []
    stop = threading.Event()
    thread = threading.Thread(target=player_log.produce, args=(cfg, collected.append, stop), daemon=True)
    thread.start()
    time.sleep(0.1)
    with log.open("a") as fh:
        fh.write(_pickup(2.0, "FreshSoul", -2) + "\n")
    time.sleep(0.2)
    stop.set()
    thread.join(timeout=3)
    items = [getattr(e, "item", None) for e in collected]
    assert "PrevSoul" in items
    assert "FreshSoul" in items
    # Backfill must happen exactly once: its already-emitted events never re-surface.
    assert items.count("PrevSoul") == 1


def test_default_player_log_path_roundtrip(monkeypatch, tmp_path: Path) -> None:
    from gorgon_tracker import config as config_mod

    chat = (
        tmp_path
        / ".local/share/Steam"
        / "steamapps/compatdata/342940/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
    )
    chat.mkdir(parents=True)
    plog = chat.parent / "Player.log"
    plog.write_text("x\n")
    monkeypatch.setattr("gorgon_tracker.config.Path.home", lambda: tmp_path)
    assert config_mod.default_player_log_path(platform="linux") == str(plog)