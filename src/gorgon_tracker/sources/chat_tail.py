"""Live chat log tailing: watch the newest Project Gorgon chat log and emit events."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from ..config import TrackerConfig, default_chat_log_dir
from ..parsers import chat as chat_parser
from ..parsers.chat import ChatEvent

_CHAT_SUFFIXES = ("*.log", "*.txt")

_READ_CHUNK = 8192


def newest_log(log_dir: Path) -> Path | None:
    """Return the most recently modified chat log in the directory, or None."""
    candidates: list[Path] = []
    for pattern in _CHAT_SUFFIXES:
        candidates.extend(log_dir.glob(pattern))
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_tail(path: Path, max_lines: int = 500) -> tuple[int, list[str]]:
    """Return ``(start_offset, lines)`` for the last ``max_lines`` lines of ``path``.

    Reads backward from EOF so a large log stays cheap to poll. ``start_offset``
    is the byte offset where the returned block begins; ``lines`` are the raw
    lines oldest-first, decoded with ``errors="replace"``.
    """
    buffer = b""
    with path.open("rb") as fh:
        size = path.stat().st_size
        position = size
        while position > 0:
            step = min(_READ_CHUNK, position)
            position -= step
            fh.seek(position)
            buffer = fh.read(step) + buffer
            if buffer.count(b"\n") >= max_lines:
                break
    lines = buffer.decode("utf-8", errors="replace").splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return size - len(buffer), lines


def _read_append(path: Path, offset: int) -> tuple[str, int]:
    with path.open("rb") as fh:
        fh.seek(offset)
        data = fh.read()
        new_offset = fh.tell()
    return data.decode("utf-8", errors="replace"), new_offset


def produce(
    cfg: TrackerConfig,
    emit: Callable[[ChatEvent], None],
    stop_event: threading.Event,
    poll_interval_s: float | None = None,
) -> None:
    """Tail the newest chat log until ``stop_event`` is set, emitting parsed events.

    The initial file (present when the tool starts) is tailed from the end so a
    restart mid-session never re-emits already-captured drops. Any subsequently
    rotated-in file (a new gaming session) is parsed in full.
    """
    log_dir_path = Path(cfg.chat.log_dir or default_chat_log_dir())
    if not log_dir_path.is_dir():
        raise RuntimeError(
            f"chat log directory not found: {log_dir_path}. "
            "Set [chat] log_dir in gorgon-tracker.toml or launch the game through Proton."
        )
    interval = poll_interval_s if poll_interval_s is not None else cfg.chat.poll_interval_s
    start_from_beginning = cfg.chat.tail_from_start

    tracked_file: Path | None = None
    tracked_key: tuple[int, int] | None = None
    offset = 0

    while not stop_event.is_set():
        current = newest_log(log_dir_path)
        if current is None:
            stop_event.wait(interval)
            continue

        try:
            stat = current.stat()
        except OSError:
            stop_event.wait(interval)
            continue

        current_key = (stat.st_dev, stat.st_ino)
        is_initial = tracked_file is None
        is_rotation = tracked_file is not None and (
            current != tracked_file or (tracked_key is not None and current_key != tracked_key)
        )

        if is_initial or is_rotation:
            tracked_file = current
            tracked_key = current_key
            offset = stat.st_size if is_initial and not start_from_beginning else 0

        if stat.st_size < offset:
            offset = 0

        if current.exists():
            text, offset = _read_append(current, offset)
            for event in chat_parser.parse_chat_lines(iter(text.splitlines())):
                if stop_event.is_set():
                    break
                emit(event)

        stop_event.wait(interval)