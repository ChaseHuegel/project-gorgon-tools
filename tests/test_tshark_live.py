import threading
import time

import pytest

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.parsers import packets
from gorgon_tracker.sources import tshark_live
from gorgon_tracker.sources.tshark_live import (
    build_bpf_filter,
    build_tshark_args,
    consume_tshark_output,
    parse_live_line,
    resolve_interface,
)

from . import scenario


def _live_lines() -> list[str]:
    lines = []
    for frame in scenario.CAPTURE_FRAMES:
        layers = frame["_source"]["layers"]
        epoch = layers["frame"]["frame.time_epoch"]
        payload = layers["tcp"]["tcp.payload"]
        lines.append(f"{epoch}\t{payload}\t")
    return lines


def _expected_from_json() -> list[dict]:
    doc = packets.parse_capture_doc(scenario.CAPTURE_FRAMES)
    return [
        {"time_ms": e.time_ms, "monster": e.monster, "skin": e.can_skin}
        for e in sorted(doc.events, key=lambda e: e.time_ms)
    ]


def test_live_parse_matches_replay_parse() -> None:
    live = [
        {"time_ms": e.time_ms, "monster": e.monster, "skin": e.can_skin}
        for e in sorted(consume_tshark_output(iter(_live_lines())), key=lambda e: e.time_ms)
    ]
    assert live == _expected_from_json()


def test_parse_live_line_skips_malformed() -> None:
    assert parse_live_line("") is None
    assert parse_live_line("garbage") is None
    assert parse_live_line("\t\t0a\t") is None


def test_parse_live_line_uses_data_payload_fallback() -> None:
    frame = scenario.CAPTURE_FRAMES[0]
    payload = frame["_source"]["layers"]["tcp"]["tcp.payload"]
    line = f"1768161602.0\t\t{payload}"
    event = parse_live_line(line)
    assert event is not None
    assert event.monster == "Giant Bat"


def test_build_tshark_args() -> None:
    cfg = TrackerConfig()
    args = build_tshark_args(cfg, "tcp.port == 123", "eth0")
    assert args[:4] == ["tshark", "-i", "eth0", "-Y"]
    assert "tcp.port == 123" in args
    assert "frame.time_epoch" in args
    assert "tcp.payload" in args
    assert "data.data" in args


def test_build_bpf_filter_explicit_wins(tmp_path, monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.capture.bpf = "tcp.port == 9"
    cfg.capture.ports = [1, 2, 3]
    assert build_bpf_filter(cfg) == "tcp.port == 9"


def test_build_bpf_filter_uses_ports(tmp_path, monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.capture.bpf = ""
    cfg.capture.ports = [80, 443]
    monkeypatch.setattr("gorgon_tracker.sources.tshark_live.discover_bpf", lambda: None)
    assert build_bpf_filter(cfg) == "tcp.port == 80 or tcp.port == 443"


def test_build_bpf_filter_discovery(tmp_path, monkeypatch) -> None:
    cfg = TrackerConfig()
    monkeypatch.setattr(
        "gorgon_tracker.sources.tshark_live.discover_bpf", lambda: "tcp.port == 999"
    )
    assert build_bpf_filter(cfg) == "tcp.port == 999"


def test_build_bpf_filter_raises_when_unknown(tmp_path, monkeypatch) -> None:
    cfg = TrackerConfig()
    monkeypatch.setattr("gorgon_tracker.sources.tshark_live.discover_bpf", lambda: None)
    with pytest.raises(RuntimeError):
        build_bpf_filter(cfg)


def test_resolve_interface_auto(monkeypatch) -> None:
    monkeypatch.setattr(
        tshark_live,
        "_tshark_interfaces",
        lambda _path: ["  1. lo  (Loopback)", "  2. eth0  (Ethernet)", "  3. wg0  (Wireguard)"],
    )
    assert resolve_interface(TrackerConfig()) == "eth0"


def test_resolve_interface_explicit() -> None:
    cfg = TrackerConfig()
    cfg.capture.interface = "wlp2s0"
    assert resolve_interface(cfg) == "wlp2s0"


class _Reader:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self._i = 0

    def readline(self) -> str:
        if self._i >= len(self._lines):
            return ""
        line = self._lines[self._i]
        self._i += 1
        return line


class _FakeProc:
    def __init__(self, reader: _Reader) -> None:
        self.stdout = reader

    def terminate(self) -> None:
        pass

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_produce_retries_discovery_until_available(monkeypatch) -> None:
    cfg = TrackerConfig()
    calls = {"n": 0}

    def flaky_filter(_cfg: TrackerConfig) -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("no filter")
        return "tcp.port == 999"

    monkeypatch.setattr(tshark_live, "build_bpf_filter", flaky_filter)
    monkeypatch.setattr(tshark_live, "resolve_interface", lambda _cfg: "eth0")
    monkeypatch.setattr(tshark_live, "DISCOVERY_RETRY_S", 0.02)

    payload = scenario.CAPTURE_FRAMES[0]["_source"]["layers"]["tcp"]["tcp.payload"]
    reader = _Reader([f"1768161602.0\t{payload}\t"])
    monkeypatch.setattr(tshark_live.subprocess, "Popen", lambda *a, **k: _FakeProc(reader))

    stop = threading.Event()
    events: list = []
    thread = threading.Thread(target=lambda: tshark_live.produce(cfg, events.append, stop), daemon=True)
    thread.start()
    time.sleep(0.2)
    stop.set()
    thread.join(timeout=5)

    assert calls["n"] >= 3  # discovery was retried until the filter became available
    assert len(events) == 1  # the single valid line was produced once
    assert events[0].monster == "Giant Bat"