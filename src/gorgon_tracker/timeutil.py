"""Datetime parsing helpers shared across parsers and storage."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

_MS_EPOCH_RE = re.compile(r"^/Date\((\-?\d+)\)/$")
_TWO_DIGIT_YEAR_RE = re.compile(r"^\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?$")


def utc_now_ms() -> int:
    return round(time.time() * 1000)


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def iso_to_ms(value: str) -> int:
    """Parse a timestamp string into UTC epoch milliseconds (best effort)."""
    value = value.strip()
    match = _MS_EPOCH_RE.match(value)
    if match:
        return int(match.group(1))

    if _TWO_DIGIT_YEAR_RE.match(value):
        # Chat log format `yy-MM-dd HH:mm:ss[.fff]`; two-digit year, assumed local.
        fmt = "%y-%m-%d %H:%M:%S" if "." not in value else "%y-%m-%d %H:%M:%S.%f"
        dt = datetime.strptime(value, fmt)
        return round(dt.astimezone().timestamp() * 1000)

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Naive: assume local time (matches historical script behavior).
        dt = dt.astimezone()
    return round(dt.timestamp() * 1000)