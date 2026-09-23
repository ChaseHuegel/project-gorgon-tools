"""Read-only web UI over the gorgon-tracker database."""

from __future__ import annotations

import sqlite3
from typing import Any

_QUERIES: dict[str, str] = {
    "sessions": "SELECT id, uuid, started_at, ended_at, platform FROM sessions ORDER BY started_at DESC",
    "summary": "SELECT * FROM v_summary ORDER BY zone, monster, item",
    "drop_rates": "SELECT * FROM v_drop_rates",
    "loot": (
        "SELECT ld.captured_at, ld.source, ld.activity, ld.item, ld.amount, ld.zone, ld.status, ld.lag_ms "
        "FROM loot_drops ld ORDER BY ld.captured_at DESC LIMIT ?"
    ),
}


def build_app(db_path: str) -> Any:
    """Create the FastAPI app (read-only); callers run uvicorn over it."""
    from fastapi import FastAPI

    app = FastAPI(title="gorgon-tracker", version="0.1.0", description="Project Gorgon loot data")

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = connect()
        try:
            return [dict(r) for r in conn.execute(query, params)]
        finally:
            conn.close()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "db": db_path}

    @app.get("/sessions")
    def sessions() -> list[dict[str, Any]]:
        return rows(_QUERIES["sessions"])

    @app.get("/summary")
    def summary() -> list[dict[str, Any]]:
        return rows(_QUERIES["summary"])

    @app.get("/drop-rates")
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
        return rows(query, tuple(params))

    @app.get("/loot")
    def loot(limit_rows: int = 200) -> list[dict[str, Any]]:
        return rows(_QUERIES["loot"], (max(1, min(limit_rows, 5000)),))

    @app.get("/")
    def index() -> dict[str, Any]:
        endpoints = [
            "/health",
            "/sessions",
            "/summary",
            "/drop-rates?monster=X&item=Y",
            "/loot?limit_rows=200",
        ]
        return {"service": "gorgon-tracker", "endpoints": endpoints}

    return app


def run_serve(db_path: str, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_app(db_path), host=host, port=port)