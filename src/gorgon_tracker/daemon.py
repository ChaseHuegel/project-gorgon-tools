"""Daemonization and pidfile helpers for background runs."""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path


def pidfile_path(db_path: str) -> Path:
    """PID file lives next to the database (one instance per DB)."""
    return Path(db_path).expanduser().resolve().parent / "gorgon-tracker.pid"


def write_pidfile(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))


def remove_pidfile(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def read_pidfile(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def daemonize(log_path: str, workdir: str | None = None) -> None:
    """Detach the process into the background, redirecting stdio to ``log_path``.

    Returns only in the daemon child; the parent exits.
    """
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    if workdir:
        os.chdir(workdir)
    os.umask(0o022)

    sys.stdin.close()
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(log_fd, sys.stdout.fileno())
    os.dup2(log_fd, sys.stderr.fileno())


def wait_for_exit(pid: int, timeout_s: float = 10.0) -> bool:
    """Block until the process exits (or timeout); returns success."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return True
        time.sleep(0.1)
    return False