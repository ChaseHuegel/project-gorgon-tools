"""Live tailing of Project Gorgon's Unity ``Player.log``.

The game appends loot/corpse events to ``Player.log`` as it runs and rotates the
file to ``Player-prev.log`` at every launch, so this source:

* tails the current ``Player.log`` from the end on first sight (a restart
  mid-session never re-emits already-seen events);
* optionally backfills ``Player-prev.log`` once at startup;
* detects rotation/truncation by file identity and starts a fresh parse session,
  which also re-anchors the UTC clock from the new session's login line.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from ..config import PlayerLogConfig, TrackerConfig, default_player_log_path
from ..parsers import playerlog as playerlog_parser


def _read_append(path: Path, offset: int) -> tuple[str, int]:
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
        new_offset = fh.tell()
    return data.decode("utf-8", errors="replace"), new_offset


def _backfill_prev(dir_path: Path, emit: Callable[[object], None]) -> bool:
    prev = dir_path / "Player-prev.log"
    if not prev.is_file():
        return False
    for event in playerlog_parser.parse_player_log_file(prev):
        emit(event)
    return True


def produce(
    cfg: TrackerConfig,
    emit: Callable[[object], None],
    stop_event: threading.Event,
    poll_interval_s: float | None = None,
) -> None:
    """Tail the game's ``Player.log`` until ``stop_event`` is set."""
    pcfg: PlayerLogConfig = cfg.playerlog
    log_path = Path(pcfg.path or default_player_log_path())
    log_dir = log_path.parent
    if not log_path.is_file():
        raise RuntimeError(
            f"Player.log not found at {log_path}. "
            "Set [playerlog] path in gorgon-tracker.toml or launch the game through Proton."
        )
    interval = poll_interval_s if poll_interval_s is not None else pcfg.poll_interval_s

    parser = playerlog_parser.PlayerLogParser()
    tracked: Path | None = None
    tracked_key: tuple[int, int] | None = None
    offset = 0
    backfilled = False

    while not stop_event.is_set():
        try:
            stat = log_path.stat()
        except OSError:
            stop_event.wait(interval)
            continue
        current_key = (stat.st_dev, stat.st_ino)

        if not backfilled and pcfg.backfill_prev:
            _backfill_prev(log_dir, emit)
            backfilled = True

        is_initial = tracked is None
        is_rotation = tracked is not None and (tracked != log_path or current_key != tracked_key)

        if is_initial or is_rotation:
            tracked = log_path
            tracked_key = current_key
            parser = playerlog_parser.PlayerLogParser()
            offset = stat.st_size if is_initial and not pcfg.tail_from_start else 0

        if stat.st_size < offset:
            offset = 0

        if log_path.exists():
            text, offset = _read_append(log_path, offset)
            for event in playerlog_parser.parse_player_log_lines(iter(text.splitlines()), parser):
                if stop_event.is_set():
                    break
                emit(event)

        stop_event.wait(interval)