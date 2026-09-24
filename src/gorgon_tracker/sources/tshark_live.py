"""Live packet capture: stream tshark `-T fields` output and decode source events.

Contrast with offline replay, which reads whole captures via `tshark -T json`.
Both paths funnel into the same ``decode_corpse_search`` logic so live parsing
must match replay parsing on identical packets.
"""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

from ..config import TrackerConfig
from ..correlator import SourceEvent
from ..parsers import packets
from ..ports import build_bpf, discover_bpf

FIELD_SEPARATOR = "/t"

_IFACE_RE = re.compile(r"^\s*\d+\.\s+(\S+)")


def build_bpf_filter(cfg: TrackerConfig) -> str:
    """Resolve the capture BPF from explicit config, ports, or auto-discovery."""
    if cfg.capture.bpf.strip():
        return cfg.capture.bpf.strip()
    if cfg.capture.ports:
        return build_bpf(tcp_ports=cfg.capture.ports, udp_ports=[])
    discovered = discover_bpf()
    if discovered:
        return discovered
    raise RuntimeError(
        "no BPF filter configured; run `gorgon-tracker find-ports` to discover the game's ports"
    )


def resolve_interface(cfg: TrackerConfig) -> str:
    """Return the capture interface, auto-detecting a default if 'auto'."""
    if cfg.capture.interface != "auto":
        return cfg.capture.interface
    for line in _tshark_interfaces(cfg.capture.tshark_path):
        match = _IFACE_RE.match(line)
        if match and match.group(1) != "lo":
            return match.group(1)
    raise RuntimeError("could not auto-detect a capture interface; set [capture] interface")


def _tshark_interfaces(tshark_path: str) -> list[str]:
    try:
        proc = subprocess.run([tshark_path, "-D"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def build_tshark_args(cfg: TrackerConfig, filter_expr: str, interface: str) -> list[str]:
    return [
        cfg.capture.tshark_path,
        "-i",
        interface,
        "-Y",
        filter_expr,
        "-T",
        "fields",
        "-E",
        f"separator={FIELD_SEPARATOR}",
        "-E",
        "occurrence=f",
        "-e",
        "frame.time_epoch",
        "-e",
        "tcp.payload",
        "-e",
        "data.data",
    ]


def parse_live_line(line: str) -> SourceEvent | None:
    """Parse one `-T fields` line into a SourceEvent (or None)."""
    line = line.rstrip("\n")
    if not line:
        return None
    fields = line.split("\t")
    if len(fields) < 3:
        return None
    epoch, tcp_payload, data_payload = fields[0], fields[1], fields[2]
    if not epoch:
        return None
    try:
        time_ms = round(float(epoch) * 1000)
    except ValueError:
        return None
    payload = tcp_payload or data_payload
    if not payload:
        return None
    search = packets.decode_corpse_search(payload)
    if search is None:
        return None
    return SourceEvent(
        time_ms=time_ms,
        monster=search.monster,
        can_skin=search.can_skin,
        can_butcher=search.can_butcher,
        can_extract=search.can_extract,
    )


def consume_tshark_output(lines: Iterator[str]) -> Iterator[SourceEvent]:
    """Decode a stream of `-T fields` lines into SourceEvents."""
    for line in lines:
        event = parse_live_line(line)
        if event is not None:
            yield event


DISCOVERY_RETRY_S = 2.0


def produce(
    cfg: TrackerConfig,
    emit: Callable[[SourceEvent], None],
    stop_event: threading.Event,
) -> None:
    """Run tshark until ``stop_event`` is set, decoding packets in real time.

    If no capture filter is configured and the game's ports are not yet
    discoverable (e.g. the game has not launched), this keeps retrying
    discovery on a short interval so ports are picked up as soon as the game
    comes online -- even mid-session.
    """
    while not stop_event.is_set():
        try:
            filter_expr = build_bpf_filter(cfg)
        except RuntimeError:
            stop_event.wait(DISCOVERY_RETRY_S)
            continue
        interface = resolve_interface(cfg)
        args = build_tshark_args(cfg, filter_expr, interface)
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
            stderr=subprocess.DEVNULL,
            preexec_fn=None,
        )
        try:
            assert process.stdout is not None
            for event in consume_tshark_output(iter(process.stdout.readline, "")):
                if stop_event.is_set():
                    break
                emit(event)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def can_run(cfg: TrackerConfig) -> bool:
    """Best-effort check that tshark is available and a filter is resolvable."""
    if not Path(cfg.capture.tshark_path).is_file():
        raise RuntimeError(f"tshark not found at {cfg.capture.tshark_path}")
    if cfg.capture.bpf.strip() or cfg.capture.ports:
        return True
    return discover_bpf() is not None