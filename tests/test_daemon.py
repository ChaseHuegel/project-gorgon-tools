import os
from pathlib import Path

from gorgon_tracker import daemon


def test_pidfile_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "gorgon-tracker.pid"
    assert daemon.read_pidfile(path) is None
    daemon.write_pidfile(path)
    assert daemon.read_pidfile(path) == os.getpid()
    daemon.remove_pidfile(path)
    assert daemon.read_pidfile(path) is None


def test_pidfile_path_derived_from_db(tmp_path: Path) -> None:
    assert daemon.pidfile_path(str(tmp_path / "gorgon.db")) == tmp_path / "gorgon-tracker.pid"


def test_wait_for_exit_dead_pid() -> None:
    assert daemon.wait_for_exit(2**24, timeout_s=1.0) is True