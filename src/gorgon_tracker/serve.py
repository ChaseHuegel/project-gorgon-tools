"""Read-only web API over the gorgon-tracker database.

:func:`build_app` returns the minimal read-only FastAPI used by the ``serve``
command. The shared router is also mounted by the full ``web`` UI app.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import StreamingResponse

from . import db as db_mod
from . import stream

_QUERIES: dict[str, str] = {
    "sessions": "SELECT id, uuid, started_at, ended_at, platform FROM sessions ORDER BY started_at DESC",
    "summary": "SELECT * FROM v_summary ORDER BY zone, monster, item",
    "drop_rates": "SELECT * FROM v_drop_rates",
    "loot": (
        "SELECT ld.id, ld.captured_at, ld.source, ld.activity, ld.item, ld.amount, ld.zone, ld.status, ld.lag_ms "
        "FROM loot_drops ld ORDER BY ld.captured_at DESC LIMIT ?"
    ),
}


class _DB:
    """Holds an open sqlite connection for read-only endpoint dependencies."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = self.connect()
        try:
            return [dict(r) for r in conn.execute(query, params)]
        finally:
            conn.close()

    def status(self) -> dict[str, Any]:
        conn = self.connect()
        try:
            return db_mod.status_overview(conn)
        finally:
            conn.close()


def build_read_router(db_path: str, include_index: bool = True) -> tuple[APIRouter, _DB]:
    """Create the shared read-only router plus its DB dependency handle."""
    db = _DB(db_path)
    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "db": db.db_path}

    @router.get("/sessions")
    def sessions() -> list[dict[str, Any]]:
        return db.rows(_QUERIES["sessions"])

    @router.get("/summary")
    def summary() -> list[dict[str, Any]]:
        return db.rows(_QUERIES["summary"])

    @router.get("/drop-rates")
    def drop_rates(monster: str | None = None, item: str | None = None) -> list[dict[str, Any]]:
        base = _QUERIES["drop_rates"]
        clauses, params = [], []
        if monster:
            clauses.append("monster = ?")
            params.append(monster)
        if item:
            clauses.append("item = ?")
            params.append(item)
        query = base + ((" WHERE " + " AND ".join(clauses)) if clauses else "")
        return db.rows(query, tuple(params))

    @router.get("/loot")
    def loot(limit_rows: int = 200) -> list[dict[str, Any]]:
        return db.rows(_QUERIES["loot"], (max(1, min(limit_rows, 5000)),))

    # --- live SSE streams ---------------------------------------------------

    def _stream(generator: Any) -> StreamingResponse:
        return StreamingResponse(
            generator,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/stream/loot")
    def stream_loot(request: Request, since: int | None = None, poll_s: float | None = None) -> StreamingResponse:
        return _stream(
            stream.loot_stream(
                db, since_id=since, poll_s=poll_s or stream._POLL_S, is_disconnected=request.is_disconnected
            )
        )

    @router.get("/stream/events")
    def stream_events(request: Request, since: int | None = None, poll_s: float | None = None) -> StreamingResponse:
        return _stream(
            stream.events_stream(
                db, since_id=since, poll_s=poll_s or stream._POLL_S, is_disconnected=request.is_disconnected
            )
        )

    @router.get("/stream/status")
    def stream_status(request: Request, since: int | None = None, poll_s: float | None = None) -> StreamingResponse:
        return _stream(
            stream.status_stream(
                db, since_id=since, poll_s=poll_s or stream._STATUS_POLL_S, is_disconnected=request.is_disconnected
            )
        )

    if include_index:

        @router.get("/")
        def index() -> dict[str, Any]:
            endpoints = [
                "/health",
                "/sessions",
                "/summary",
                "/drop-rates?monster=X&item=Y",
                "/loot?limit_rows=200",
            ]
            return {"service": "gorgon-tracker", "endpoints": endpoints}

    return router, db


def build_app(db_path: str) -> FastAPI:
    """Create the read-only FastAPI app (used by ``serve``)."""
    router, _ = build_read_router(db_path)
    app = FastAPI(title="gorgon-tracker", version="0.1.0", description="Project Gorgon loot data")
    app.include_router(router)
    return app


def run_serve(db_path: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_app(db_path), host=host, port=port)
