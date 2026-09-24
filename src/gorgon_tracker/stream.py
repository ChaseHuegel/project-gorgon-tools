"""Server-sent event (SSE) streams over the gorgon-tracker database.

The capture daemon writes loot, raw events, and counts into SQLite as it runs;
these generators tail that database and push new rows to the browser so the UI
updates live during a capture. Each poll opens a fresh read-only connection
(matching the read API) so writes by the daemon are always observed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.concurrency import run_in_threadpool

_LOOT_POLL_SQL = (
    "SELECT id, captured_at, source, activity, item, amount, zone, status, lag_ms "
    "FROM loot_drops WHERE id > ? ORDER BY id ASC"
)

_EVENT_POLL_SQL = (
    "SELECT id, session_id, source, captured_at, payload_json FROM raw_events WHERE id > ? ORDER BY id ASC"
)

_STREAM_EVENT = "loot"
_EVENTS_EVENT = "event"
_STATUS_EVENT = "status"

_POLL_S = 0.5
_STATUS_POLL_S = 1.5


def _sse(cursor: int, event: str, data: Any) -> str:
    """Render one SSE frame: id + event + data, and a fast reconnect hint."""
    return "\n".join(
        [
            "retry: 2500",
            f"id: {cursor}",
            f"event: {event}",
            "data: " + json.dumps(data, separators=(",", ":")),
            "",
            "",
        ]
    )


def _heartbeat() -> str:
    return "retry: 2500\n: ping\n\n"


async def _polls_remaining(once: bool, is_disconnected: Callable[[], Awaitable[bool]] | None) -> bool:
    if is_disconnected is not None and await is_disconnected():
        return False
    return not once


async def loot_stream(
    db: Any,
    since_id: int | None = None,
    poll_s: float = _POLL_S,
    once: bool = False,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    """Yield SSE frames for new ``loot_drops`` rows after ``since_id``."""
    cursor = int(since_id or 0)
    while True:
        rows = await run_in_threadpool(db.rows, _LOOT_POLL_SQL, (cursor,))
        for row in rows:
            cursor = row["id"]
            yield _sse(cursor, _STREAM_EVENT, row)
        if not await _polls_remaining(once, is_disconnected):
            break
        yield _heartbeat()
        await asyncio.sleep(poll_s)


async def events_stream(
    db: Any,
    since_id: int | None = None,
    poll_s: float = _POLL_S,
    once: bool = False,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    """Yield SSE frames for new ``raw_events`` rows after ``since_id``."""
    cursor = int(since_id or 0)
    while True:
        rows = await run_in_threadpool(db.rows, _EVENT_POLL_SQL, (cursor,))
        for row in rows:
            cursor = row["id"]
            payload = json.loads(row["payload_json"])
            data = {k: v for k, v in row.items() if k != "payload_json"}
            data["payload"] = payload
            yield _sse(cursor, _EVENTS_EVENT, data)
        if not await _polls_remaining(once, is_disconnected):
            break
        yield _heartbeat()
        await asyncio.sleep(poll_s)


async def status_stream(
    db: Any,
    since_id: int | None = None,
    poll_s: float = _STATUS_POLL_S,
    once: bool = False,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
) -> Any:
    """Yield SSE frames with the current open-session event counts."""
    cursor = int(since_id or 0)
    while True:
        overview = await run_in_threadpool(db.status)
        payload = {
            "open_session_id": overview["open_session_id"],
            "open_session_counts": overview["open_session_counts"],
        }
        cursor += 1
        yield _sse(cursor, _STATUS_EVENT, payload)
        if not await _polls_remaining(once, is_disconnected):
            break
        await asyncio.sleep(poll_s)
