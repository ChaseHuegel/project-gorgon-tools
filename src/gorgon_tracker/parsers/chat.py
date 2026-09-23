"""Chat log parsing: loot and bury events from Project Gorgon status lines."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from ..correlator import BuryEvent, LootEvent
from ..timeutil import iso_to_ms

LOOT_RE = re.compile(
    r"^(?P<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+"
    r"(?P<item>.+?)(?:\s+x(?P<count>\d+))?\s+added to inventory\.$"
)
BURY_RE = re.compile(r"^(?P<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+You bury the corpse\.$")


ChatEvent = LootEvent | BuryEvent


def parse_chat_line(line: str) -> ChatEvent | None:
    """Parse a single chat log line into a LootEvent or BuryEvent (or None)."""
    line = line.strip()
    if not line:
        return None
    match = LOOT_RE.match(line)
    if match:
        count_text = match.group("count")
        amount = int(count_text) if count_text else 1
        return LootEvent(time_ms=iso_to_ms(match.group("timestamp")), item=match.group("item").strip(), amount=amount)
    match = BURY_RE.match(line)
    if match:
        return BuryEvent(time_ms=iso_to_ms(match.group("timestamp")))
    return None


def parse_chat_lines(lines: Iterator[str]) -> Iterator[ChatEvent]:
    """Parse streaming chat lines into events, skipping non-matching lines."""
    for line in lines:
        event = parse_chat_line(line)
        if event is not None:
            yield event


def parse_chat_file(path: Path) -> Iterator[ChatEvent]:
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        yield from parse_chat_lines(fh)