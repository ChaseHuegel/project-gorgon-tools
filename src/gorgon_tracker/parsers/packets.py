"""Packet parsing: decode tshark payloads into monster source events."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# `tcp.payload contains "Search Corpse of "` in hex.
DISPLAY_FILTER = "tcp.payload contains 53:65:61:72:63:68:20:43:6f:72:70:73:65:20:6f:66:20"

_SEARCH_RE = re.compile(r"Search Corpse of (?P<name>[^\r\n]*)")
_NO_PERMISSION = "You do not have permission to loot this corpse."
_TIME_SUFFIX_RE = re.compile(r"\s+[A-Z].*$")

_STRIP_SEQUENCES = ("Autopsy", "Skin Corpse", "Butcher Corpse", "Extract Skull")


@dataclass(frozen=True)
class CorpseSearch:
    """Decoded corpse-search text extracted from a payload (timing unknown)."""

    monster: str
    can_skin: bool
    can_butcher: bool
    can_extract: bool
    raw_text: str


@dataclass(frozen=True)
class PacketEvent:
    """A decoded corpse-search frame that identifies a killable source."""

    time_ms: int
    monster: str
    can_skin: bool
    can_butcher: bool
    can_extract: bool
    raw_text: str


@dataclass(frozen=True)
class CaptureDoc:
    """A parsed capture document (frame window + source events)."""

    start_ms: int
    end_ms: int
    events: list[PacketEvent]


def hex_payload_to_text(payload_hex: str) -> str:
    """Decode a tshark `aa:bb:cc` payload into a latin-1 string (lossless byte map)."""
    if not payload_hex:
        return ""
    return bytes(int(b, 16) for b in payload_hex.split(":")).decode("latin-1")


def clean_ascii(text: str) -> str:
    """Keep only printable ASCII plus newline/carriage-return (matches legacy cleanup)."""
    return "".join(ch for ch in text if (32 <= ord(ch) <= 126) or ch in ("\n", "\r"))


def extract_payload(frame: dict[str, Any]) -> str | None:
    layers = frame.get("_source", {}).get("layers", {})
    tcp = layers.get("tcp") or {}
    if tcp.get("tcp.payload"):
        return str(tcp["tcp.payload"])
    data = layers.get("data") or {}
    if data.get("data.data"):
        return str(data["data.data"])
    return None


def frame_epoch_ms(frame: dict[str, Any]) -> int | None:
    layers = frame.get("_source", {}).get("layers", {})
    frame_layer = layers.get("frame") or {}
    epoch = frame_layer.get("frame.time_epoch")
    if epoch not in (None, ""):
        try:
            return round(float(str(epoch)) * 1000)
        except ValueError:
            pass
    time_str = frame_layer.get("frame.time")
    if time_str:
        return frame_time_to_ms(str(time_str))
    return None


def frame_time_to_ms(value: str) -> int | None:
    """Parse a tshark `frame.time` display string, treating it as local time."""
    cleaned = _TIME_SUFFIX_RE.sub("", value.strip())
    # tshark emits up to 9 fractional digits; datetime supports 6.
    if "." in cleaned:
        head, _, frac = cleaned.partition(".")
        cleaned = f"{head}.{frac[:6]}"
    for fmt in ("%b %d, %Y %H:%M:%S.%f", "%b %d %Y %H:%M:%S.%f", "%b %d, %Y %H:%M:%S"):
        try:
            dt = datetime.strptime(cleaned, fmt)
            return round(dt.astimezone().timestamp() * 1000)
        except ValueError:
            continue
    return None


def decode_corpse_search(payload: str) -> CorpseSearch | None:
    """Return a CorpseSearch if the payload is a corpse-search frame, else None."""
    raw_text = hex_payload_to_text(payload)
    clean = clean_ascii(raw_text)
    match = _SEARCH_RE.search(clean)
    if not match:
        return None
    if _NO_PERMISSION in clean:
        return None
    name = match.group("name")
    for seq in _STRIP_SEQUENCES:
        name = name.replace(seq, "")
    name = name.strip().strip("-")
    return CorpseSearch(
        monster=name,
        can_skin="Skin Corpse" in raw_text,
        can_butcher="Butcher Corpse" in raw_text,
        can_extract="Extract Skull" in raw_text,
        raw_text=raw_text,
    )


def iter_events_from_json_doc(doc: list[dict[str, Any]]) -> Iterator[PacketEvent]:
    """Yield PacketEvents from a tshark `-T json` document (list of frames)."""
    for frame in doc:
        payload = extract_payload(frame)
        if not payload:
            continue
        search = decode_corpse_search(payload)
        if search is None:
            continue
        time_ms = frame_epoch_ms(frame)
        if time_ms is None:
            continue
        yield PacketEvent(
            time_ms=time_ms,
            monster=search.monster,
            can_skin=search.can_skin,
            can_butcher=search.can_butcher,
            can_extract=search.can_extract,
            raw_text=search.raw_text,
        )


def parse_capture_doc(doc: list[dict[str, Any]]) -> CaptureDoc:
    """Parse a tshark JSON document into a CaptureDoc (events + first/last frame window)."""
    events = list(iter_events_from_json_doc(doc))
    if not doc:
        return CaptureDoc(start_ms=0, end_ms=0, events=[])
    times = [ms for ms in (frame_epoch_ms(f) for f in doc) if ms is not None]
    start = min(times) if times else 0
    end = max(times) if times else 0
    return CaptureDoc(start_ms=start, end_ms=end, events=events)


def load_json_doc(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        doc: list[dict[str, Any]] = json.load(fh)
    return doc


def extract_pcap(
    path: Path,
    tshark_path: str = "tshark",
    display_filter: str = DISPLAY_FILTER,
) -> CaptureDoc:
    """Run tshark to extract matching frames from a .pcap/.pcapng file and parse them."""
    cmd = [tshark_path, "-r", str(path), "-2", "-Y", display_filter, "-T", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"tshark failed on {path}: {proc.stderr.strip()}")
    doc = json.loads(proc.stdout) if proc.stdout.strip() else []
    return parse_capture_doc(doc)