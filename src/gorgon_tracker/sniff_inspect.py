"""Packet investigation: capture game traffic and inventory its plaintext strings.

The live capture pipeline only ever looks for ``Search Corpse of`` packets. This
tool answers the broader question of *what else* the game sends in plaintext —
e.g. whether "added to inventory" or other status/loot messages cross the wire.
It runs either live (a short capture over the game's ports, raw pcap retained)
or offline (the same analysis over an existing capture).

Artifacts written to the output directory:

* ``capture-<ts>.pcapng`` — raw capture (live mode) for arbitrary re-analysis;
* ``strings.csv`` — unique printable-ASCII tokens with counts and first/last
  first/last-seen times and the TCP streams that carried them;
* ``streams/<stream>_<dir>.txt`` — per-TCP-stream, per-direction payload text.
"""

from __future__ import annotations

import csv
import re
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import TrackerConfig
from .sources import tshark_live

FILED_SEP = "\t"

_TOKEN_RE = re.compile(r"[ -~]{4,}")

FIELD_ARGS = [
    "-e",
    "frame.number",
    "-e",
    "frame.time_epoch",
    "-e",
    "tcp.stream",
    "-e",
    "ip.src",
    "-e",
    "ip.dst",
    "-e",
    "tcp.srcport",
    "-e",
    "tcp.dstport",
    "-e",
    "tcp.payload",
    "-e",
    "data.data",
]


@dataclass(frozen=True)
class PayloadRecord:
    """One tshark ``-T fields`` line (an Ethernet packet), not yet decoded."""

    frame_number: int | None
    time_ms: int | None
    stream: str | None
    src: str | None
    dst: str | None
    srcport: str | None
    dstport: str | None
    payload_hex: str


@dataclass
class TokenStat:
    count: int = 0
    first_ms: int | None = None
    last_ms: int | None = None
    streams: set[str] = field(default_factory=set)
    directions: set[str] = field(default_factory=set)


def build_field_args() -> list[str]:
    return list(FIELD_ARGS)


def parse_field_line(line: str, game_tcp_ports: set[int] | None = None) -> PayloadRecord | None:
    """Parse one ``-T fields`` line (9 tab-separated fields) into a record."""
    line = line.rstrip("\n")
    if not line:
        return None
    parts = line.split(FILED_SEP)
    if len(parts) < 9:
        return None
    frame_number = None
    if parts[0].isdigit():
        frame_number = int(parts[0])
    time_ms = None
    if parts[1]:
        try:
            time_ms = round(float(parts[1]) * 1000)
        except ValueError:
            time_ms = None
    payload = parts[7] or parts[8]
    if not payload:
        return None
    return PayloadRecord(
        frame_number=frame_number,
        time_ms=time_ms,
        stream=parts[2] or "0",
        src=parts[3] or None,
        dst=parts[4] or None,
        srcport=parts[5] or None,
        dstport=parts[6] or None,
        payload_hex=payload,
    )


def direction_of(record: PayloadRecord, game_tcp_ports: set[int] | None) -> str:
    """Classify client→server vs server→client when the game ports are known."""
    if game_tcp_ports:
        src_port = _port(record.srcport)
        dst_port = _port(record.dstport)
        if src_port in game_tcp_ports:
            return "c>s"
        if dst_port in game_tcp_ports:
            return "s>c"
    return "unknown"


def _port(value: str | None) -> int | None:
    if value and value.isdigit():
        return int(value)
    return None


def decode_payload(payload_hex: str) -> str:
    """Decode a tshark ``aa:bb:cc`` payload into a latin-1 string (lossless byte map)."""
    if not payload_hex:
        return ""
    return bytes(int(b, 16) for b in payload_hex.split(":")).decode("latin-1")


def tokenize(text: str) -> list[str]:
    """Return printable-ASCII runs (length >= 4) found in the decoded payload."""
    return _TOKEN_RE.findall(text)


def analyze(records: list[PayloadRecord], game_tcp_ports: set[int] | None = None) -> dict[str, Any]:
    """Aggregate decoded payloads into a token inventory plus per-stream text."""
    tokens: dict[str, TokenStat] = defaultdict(TokenStat)
    stream_text: dict[tuple[str, str], list[int]] = defaultdict(list)  # (stream, dir) -> ms list per frame
    decoded: dict[int, str] = {}  # frame_number -> payload text (dedup within a stream frame)
    frame_stream: dict[int, tuple[str, str]] = {}

    for record in records:
        direction = direction_of(record, game_tcp_ports)
        key = (record.stream or "?", direction)
        text = decode_payload(record.payload_hex)
        stream_text[key].append(record.time_ms or 0)
        if record.frame_number is not None:
            decoded[record.frame_number] = text
            frame_stream[record.frame_number] = key
        for token in dict.fromkeys(tokenize(text)):
            stat = tokens[token]
            stat.count += 1
            stat.streams.add(key[0])
            stat.directions.add(direction)
            if stat.first_ms is None or (record.time_ms is not None and record.time_ms < stat.first_ms):
                stat.first_ms = record.time_ms
            if stat.last_ms is None or (record.time_ms is not None and record.time_ms > stat.last_ms):
                stat.last_ms = record.time_ms

    return {"tokens": tokens, "stream_text": stream_text, "decoded": decoded, "frame_stream": frame_stream}


def write_report(out_dir: Path, tokens: dict[str, TokenStat]) -> Path:
    """Write ``strings.csv`` (token, count, first/last ms, streams, directions)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "strings.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["token", "count", "first_ms", "last_ms", "streams", "directions"])
        for token, stat in sorted(tokens.items(), key=lambda kv: kv[1].count, reverse=True):
            writer.writerow(
                [
                    token,
                    stat.count,
                    stat.first_ms if stat.first_ms is not None else "",
                    stat.last_ms if stat.last_ms is not None else "",
                    ",".join(sorted(stat.streams)),
                    ",".join(sorted(stat.directions)),
                ]
            )
    return path


def write_stream_dumps(out_dir: Path, analysis: dict[str, Any]) -> Path:
    """Write ``streams/<stream>_<dir>.txt`` payload text in frame order."""
    stream_dir = out_dir / "streams"
    stream_dir.mkdir(parents=True, exist_ok=True)
    decoded = analysis["decoded"]
    frame_stream = analysis["frame_stream"]
    ordered_frames = [(int(fn), fs) for fn, fs in frame_stream.items()]
    ordered_frames.sort()
    buffers: dict[tuple[str, str], list[str]] = {}
    for frame_number, key in ordered_frames:
        buffers.setdefault(key, []).append(decoded[frame_number])
    for (stream, direction), chunks in buffers.items():
        name = f"{stream}_{direction}.txt"
        with (stream_dir / name).open("w", encoding="utf-8") as fh:
            fh.write(f"# stream {stream} direction {direction}\n")
            fh.write("\n".join(chunks))
            fh.write("\n")
    return stream_dir


def _resolve_filter(cfg: TrackerConfig, bpf: str | None) -> str:
    if bpf:
        return bpf
    return tshark_live.build_bpf_filter(cfg)


def _common_tshark_args(tshark_path: str) -> list[str]:
    return [
        tshark_path,
        "-T",
        "fields",
        "-E",
        f"separator={FILED_SEP}",
        "-E",
        "occurrence=f",
        *FIELD_ARGS,
    ]


def capture_live(
    cfg: TrackerConfig,
    out_dir: Path,
    stop_event: threading.Event,
    bpf: str | None = None,
    duration_s: float | None = None,
    game_tcp_ports: set[int] | None = None,
) -> dict[str, Any]:
    """Capture game traffic live, saving the raw pcap and returning analysis stats."""
    filter_expr = _resolve_filter(cfg, bpf)
    interface = tshark_live.resolve_interface(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    capture_file = out_dir / f"capture-{int(time.time())}.pcapng"
    args = [
        cfg.capture.tshark_path,
        "-i",
        interface,
        "-Y",
        filter_expr,
        "-w",
        str(capture_file),
        *_common_tshark_args(cfg.capture.tshark_path)[1:],
    ]
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
        stderr=subprocess.DEVNULL,
    )
    records: list[PayloadRecord] = []
    assert process.stdout is not None
    started = time.monotonic()
    try:
        for line in iter(process.stdout.readline, ""):
            if stop_event.is_set() or (
                duration_s is not None and time.monotonic() - started >= duration_s
            ):
                break
            record = parse_field_line(line, game_tcp_ports)
            if record is not None:
                records.append(record)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    return finalize_analysis(out_dir, records, capture_file, game_tcp_ports)


def analyze_pcap(
    cfg: TrackerConfig,
    pcap: Path,
    out_dir: Path,
    bpf: str | None = None,
    game_tcp_ports: set[int] | None = None,
) -> dict[str, Any]:
    """Run the same analysis offline over an existing capture file."""
    args = [
        *(_common_tshark_args(cfg.capture.tshark_path)),
        "-r",
        str(pcap),
    ]
    if bpf:
        args += ["-Y", bpf]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tshark failed on {pcap}: {proc.stderr.strip()}")
    records = [
        record
        for record in (parse_field_line(line, game_tcp_ports) for line in proc.stdout.splitlines())
        if record is not None
    ]
    return finalize_analysis(out_dir, records, pcap, game_tcp_ports)


def finalize_analysis(
    out_dir: Path, records: list[PayloadRecord], source_file: Path, game_tcp_ports: set[int] | None
) -> dict[str, Any]:
    """Write the report artifacts and return a summary of the analysis."""
    analysis = analyze(records, game_tcp_ports)
    strings_path = write_report(out_dir, analysis["tokens"])
    streams_dir = write_stream_dumps(out_dir, analysis)
    top = sorted(analysis["tokens"].items(), key=lambda kv: kv[1].count, reverse=True)[:15]
    return {
        "source_file": str(source_file),
        "frames": len(records),
        "unique_tokens": len(analysis["tokens"]),
        "streams": len(analysis["stream_text"]),
        "strings_file": str(strings_path),
        "streams_dir": str(streams_dir),
        "top_strings": [{"token": token, "count": stat.count} for token, stat in top],
    }