"""Daemon/process control and setup checks for the web UI."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import daemon
from .config import TrackerConfig


def daemon_status(db_path: str) -> dict[str, Any]:
    """Return running state of the capture daemon for ``db_path``."""
    pid_path = daemon.pidfile_path(db_path)
    pid = daemon.read_pidfile(pid_path)
    running = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            running = True
        except (ProcessLookupError, PermissionError):
            running = False
    return {"pid": pid, "running": running, "pidfile": str(pid_path)}


def _binary() -> Path:
    binary = Path(sys.executable).parent / "gorgon-tracker"
    return binary if binary.exists() else Path("gorgon-tracker")


def daemon_start(db_path: str, config_path: str | None = None, log_path: str | None = None) -> dict[str, Any]:
    """Start the capture daemon as a background process; return its status."""
    state = daemon_status(db_path)
    if state["running"]:
        return state

    pid_path = daemon.pidfile_path(db_path)
    log = log_path or str(pid_path.with_suffix(".log"))
    args = [str(_binary())]
    if config_path:
        args += ["--config", config_path]
    args += ["run", "--daemon", "--db", db_path]

    try:
        with open(log, "a", encoding="utf-8") as log_fh:
            subprocess.Popen(  # noqa: S603 - user-invoked control of our own CLI
                args,
                cwd=str(Path(db_path).parent),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except (FileNotFoundError, PermissionError) as exc:
        return {"pid": None, "running": False, "pidfile": str(pid_path), "error": str(exc)}

    for _ in range(50):
        if pid_path.is_file():
            break
        time.sleep(0.1)
    return daemon_status(db_path)


def daemon_stop(db_path: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Stop a running capture daemon via its pidfile; return final status."""
    pid_path = daemon.pidfile_path(db_path)
    pid = daemon.read_pidfile(pid_path)
    if pid is None:
        return daemon_status(db_path)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    stopped = daemon.wait_for_exit(pid, timeout_s)
    if stopped:
        daemon.remove_pidfile(pid_path)
    return daemon_status(db_path)


def setup_warnings(cfg: TrackerConfig) -> list[str]:
    """Return actionable warnings for missing capture prerequisites."""
    from .pipeline import has_capture_ok

    warnings: list[str] = []
    capture_ok = cfg.capture.enabled and has_capture_ok(cfg)
    chat_ok = cfg.chat.tail and bool(cfg.chat.log_dir)
    ocr_ok = cfg.ocr.enabled

    if cfg.capture.enabled and not capture_ok:
        warnings.append(
            "Packet capture will start but can't detect the game yet; launch Project Gorgon so "
            "its ports can be auto-discovered (capture.ports/bpf may also be set explicitly)."
        )
    if cfg.chat.tail and not chat_ok:
        warnings.append(
            "Chat tailing has no log directory; set chat.log_dir or ensure the game ran once."
        )
    if not capture_ok and not chat_ok and not ocr_ok:
        warnings.append("No capture sources are enabled; a run would idle until stopped.")
    return warnings