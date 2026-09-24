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
    "loot": (
        "SELECT ld.id, ld.captured_at, ld.source, ld.activity, ld.item, ld.amount, ld.zone,"
        " ld.status, ld.lag_ms, ld.linked_via, ld.monster_name, ld.monster_lag_ms,"
        " ld.target_name, ld.target_lag_ms, ld.corroborated_by_search,"
        " ov.source AS ov_source, ov.status AS ov_status, ov.activity AS ov_activity,"
        " ov.note AS ov_note "
        "FROM loot_drops ld LEFT JOIN loot_overrides ov ON ov.loot_drop_id = ld.id"
        " ORDER BY ld.captured_at DESC LIMIT ?"
    ),
}

_LOOT_EFFECTIVE_FIELDS = (
    "id",
    "captured_at",
    "item",
    "amount",
    "zone",
    "lag_ms",
    "linked_via",
    "monster_name",
    "monster_lag_ms",
    "target_name",
    "target_lag_ms",
    "corroborated_by_search",
)


def _effective_loot_row(row: dict[str, Any]) -> dict[str, Any]:
    """Merge a manual override over the correlated values of one loot row."""
    cleaned = {k: row.get(k) for k in _LOOT_EFFECTIVE_FIELDS}
    cleaned["corroborated_by_search"] = bool(cleaned["corroborated_by_search"])
    overridden = any(row.get(f"ov_{field}") is not None for field in ("source", "status", "activity"))
    cleaned["source"] = row.get("ov_source") or row.get("source")
    cleaned["status"] = row.get("ov_status") or row.get("status")
    cleaned["activity"] = row.get("ov_activity") or row.get("activity")
    cleaned["note"] = row.get("ov_note")
    cleaned["overridden"] = overridden
    return cleaned

# Whitelisted sort keys -> SQL expression. Used to prevent injection via the sort param.
_SORT_COLUMNS: dict[str, str] = {
    "monster": "ld.source",
    "item": "ld.item",
    "drops": "COUNT(*)",
    "quantity": "SUM(ld.amount)",
    "encounters": "encounters",
    "rate": "drop_rate",
    "zone": "ld.zone",
    "activity": "ld.activity",
}

_DROP_RATES_BASE = """
WITH encounter_counts AS (
    SELECT source AS monster, COUNT(DISTINCT encounter_id) AS encounter_count
    FROM loot_drops
    WHERE status = 'Linked' AND encounter_id IS NOT NULL
    GROUP BY source
)
SELECT ld.source AS monster,
       ld.item,
       COUNT(*) AS drops,
       SUM(ld.amount) AS quantity,
       COALESCE(e.encounter_count, 0) AS encounters,
       ROUND(CAST(COUNT(*) AS REAL) / NULLIF(COALESCE(e.encounter_count, 0), 0), 4) AS drop_rate
FROM loot_drops ld
LEFT JOIN encounter_counts e ON e.monster = ld.source
{where}
GROUP BY ld.source, ld.item
{order}
{limit}
"""


def _drop_rates_where(
    *,
    monster: str | None = None,
    item: str | None = None,
    zone: str | None = None,
    activity: str | None = None,
    status: str | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("ld.status = ?")
        params.append(status)
    if monster:
        clauses.append("ld.source = ?")
        params.append(monster)
    if item:
        clauses.append("ld.item = ?")
        params.append(item)
    if zone:
        clauses.append("ld.zone = ?")
        params.append(zone)
    if activity:
        clauses.append("ld.activity = ?")
        params.append(activity)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _orders(sort: str | None, order: str | None) -> str:
    if not sort or sort not in _SORT_COLUMNS:
        return ""
    direction = "ASC" if str(order or "asc").lower() == "asc" else "DESC"
    return f"ORDER BY {_SORT_COLUMNS[sort]} {direction}"


def _drop_rates(
    db: _DB,
    *,
    monster: str | None = None,
    item: str | None = None,
    zone: str | None = None,
    activity: str | None = None,
    status: str | None = "Linked",
    sort: str | None = None,
    order: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where, params = _drop_rates_where(
        monster=monster, item=item, zone=zone, activity=activity, status=status
    )
    query = _DROP_RATES_BASE.format(where=where, order=_orders(sort, order), limit="")
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return db.rows(query, tuple(params))


class _DB:
    """Holds an open sqlite connection for read-only endpoint dependencies."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        db_mod.migrate(conn)  # ensure the schema (incl. evidence columns) is current
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

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "db": db.db_path}

    @router.get("/api/sessions")
    def sessions() -> list[dict[str, Any]]:
        return db.rows(_QUERIES["sessions"])

    @router.get("/api/distinct")
    def distinct() -> dict[str, list[str]]:
        """Distinct axis values for filter dropdowns and the search autocomplete."""
        axes = {
            "sources": "source",
            "zones": "zone",
            "items": "item",
            "activities": "activity",
        }
        result: dict[str, list[str]] = {}
        for key, column in axes.items():
            result[key] = [
                str(r["v"])
                for r in db.rows(
                    f"SELECT DISTINCT {column} AS v FROM loot_drops "
                    f"WHERE {column} IS NOT NULL AND {column} != '' ORDER BY {column} COLLATE NOCASE"
                )
            ]
        return result

    @router.get("/api/summary")
    def summary(
        source: str | None = None,
        item: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if monster_like := source:
            clauses.append("monster LIKE ?")
            params.append(f"%{monster_like}%")
        if item_like := item:
            clauses.append("item LIKE ?")
            params.append(f"%{item_like}%")
        if zone:
            clauses.append("zone = ?")
            params.append(zone)
        if activity:
            clauses.append("activity = ?")
            params.append(activity)
        query = "SELECT * FROM v_summary"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY zone, monster, item"
        return db.rows(query, tuple(params))

    @router.get("/api/drop-rates")
    def drop_rates(
        monster: str | None = None,
        item: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
        status: str | None = "Linked",
        sort: str | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _drop_rates(
            db,
            monster=monster,
            item=item,
            zone=zone,
            activity=activity,
            status=status,
            sort=sort,
            order=order,
            limit=max(1, min(limit, 5000)) if limit else None,
        )

    @router.get("/api/loot")
    def loot(
        limit_rows: int = 200,
        linked_via: str | None = None,
        confidence: str | None = None,
    ) -> list[dict[str, Any]]:
        query = _QUERIES["loot"]
        params: list[Any] = [max(1, min(limit_rows, 5000))]
        if linked_via:
            query = query.replace(" ORDER BY", " WHERE ld.linked_via = ? ORDER BY", 1)
            params.insert(0, linked_via)
        elif confidence == "uncertain":
            query = query.replace(" ORDER BY", " WHERE ld.linked_via != 'monster' ORDER BY", 1)
        elif confidence == "high":
            query = query.replace(" ORDER BY", " WHERE ld.linked_via = 'monster' ORDER BY", 1)
        return [_effective_loot_row(r) for r in db.rows(query, tuple(params))]

    # --- search + drill-down -------------------------------------------------

    @router.get("/api/search")
    def search(q: str, limit: int = 20) -> dict[str, list[dict[str, Any]]]:
        if not q:
            return {"sources": [], "items": [], "activities": []}
        like = f"%{q}%"
        cap = max(1, min(limit, 100))
        sources = db.rows(
            "SELECT source AS name, COUNT(*) AS drops, "
            "COUNT(DISTINCT encounter_id) AS encounters "
            "FROM loot_drops WHERE source LIKE ? GROUP BY source ORDER BY drops DESC LIMIT ?",
            (like, cap),
        )
        items = db.rows(
            "SELECT item AS name, COUNT(*) AS drops, COUNT(DISTINCT source) AS sources "
            "FROM loot_drops WHERE item LIKE ? GROUP BY item ORDER BY drops DESC LIMIT ?",
            (like, cap),
        )
        activities = db.rows(
            "SELECT activity AS name, COUNT(*) AS drops "
            "FROM loot_drops WHERE activity LIKE ? GROUP BY activity ORDER BY drops DESC LIMIT ?",
            (like, cap),
        )
        return {"sources": sources, "items": items, "activities": activities}

    @router.get("/api/source/{name:path}")
    def source_detail(name: str) -> dict[str, Any] | None:
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops FROM loot_drops WHERE source = ? "
            "GROUP BY zone ORDER BY drops DESC",
            (name,),
        )
        items = _drop_rates(db, monster=name, status=None)
        return {"source": name, "zones": zones, "items": items}

    @router.get("/api/item/{name:path}")
    def item_detail(name: str) -> dict[str, Any] | None:
        sources = _drop_rates(db, item=name, status=None)
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops FROM loot_drops WHERE item = ? "
            "GROUP BY zone ORDER BY drops DESC",
            (name,),
        )
        return {"item": name, "sources": sources, "zones": zones}

    @router.get("/api/activity/{name:path}")
    def activity_detail(name: str) -> dict[str, Any] | None:
        sources = db.rows(
            "SELECT source AS monster, COUNT(*) AS drops, "
            "COUNT(DISTINCT encounter_id) AS encounters "
            "FROM loot_drops WHERE activity = ? GROUP BY source ORDER BY encounters DESC, drops DESC",
            (name,),
        )
        items = db.rows(
            "SELECT item, COUNT(*) AS drops FROM loot_drops WHERE activity = ? "
            "GROUP BY item ORDER BY drops DESC",
            (name,),
        )
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops FROM loot_drops WHERE activity = ? "
            "GROUP BY zone ORDER BY drops DESC",
            (name,),
        )
        return {"activity": name, "sources": sources, "items": items, "zones": zones}

    # --- chart aggregations --------------------------------------------------

    def _axis_filter(
        source: str | None, item: str | None, zone: str | None, activity: str | None
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source:
            clauses.append("ld.source = ?")
            params.append(source)
        if item:
            clauses.append("ld.item = ?")
            params.append(item)
        if zone:
            clauses.append("ld.zone = ?")
            params.append(zone)
        if activity:
            clauses.append("ld.activity = ?")
            params.append(activity)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where, params

    @router.get("/api/analysis/sources")
    def analysis_sources(
        source: str | None = None,
        item: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
        status: str | None = "Linked",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, item, zone, activity)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.insert(0, status)
        encounters = "COUNT(DISTINCT ld.encounter_id)"
        rate = f"ROUND(CAST(COUNT(*) AS REAL) / NULLIF({encounters}, 0), 4)"
        rows = db.rows(
            "SELECT ld.source AS monster, COUNT(*) AS drops, SUM(ld.amount) AS quantity, "
            f"{encounters} AS encounters, "
            f"{rate} AS drop_rate "
            f"FROM loot_drops ld {where} GROUP BY ld.source ORDER BY drops DESC LIMIT ?",
            tuple(params) + (max(1, min(limit, 500)),),
        )
        return rows

    @router.get("/api/analysis/zones")
    def analysis_zones(
        source: str | None = None,
        item: str | None = None,
        activity: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, item, None, activity)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.insert(0, status)
        rows = db.rows(
            f"SELECT ld.zone, COUNT(*) AS drops, COUNT(DISTINCT ld.source) AS sources FROM loot_drops ld "
            f"{where} GROUP BY ld.zone ORDER BY drops DESC LIMIT ?",
            tuple(params) + (max(1, min(limit, 500)),),
        )
        return rows

    @router.get("/api/analysis/items")
    def analysis_items(
        source: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
        status: str | None = "Linked",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, None, zone, activity)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.insert(0, status)
        rows = db.rows(
            f"SELECT ld.item, COUNT(*) AS drops, COUNT(DISTINCT ld.source) AS sources FROM loot_drops ld "
            f"{where} GROUP BY ld.item ORDER BY drops DESC LIMIT ?",
            tuple(params) + (max(1, min(limit, 500)),),
        )
        return rows

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

    @router.get("/api/stream/loot")
    def stream_loot(request: Request, since: int | None = None, poll_s: float | None = None) -> StreamingResponse:
        return _stream(
            stream.loot_stream(
                db, since_id=since, poll_s=poll_s or stream._POLL_S, is_disconnected=request.is_disconnected
            )
        )

    @router.get("/api/stream/events")
    def stream_events(request: Request, since: int | None = None, poll_s: float | None = None) -> StreamingResponse:
        return _stream(
            stream.events_stream(
                db, since_id=since, poll_s=poll_s or stream._POLL_S, is_disconnected=request.is_disconnected
            )
        )

    @router.get("/api/stream/status")
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
                "/api/health",
                "/api/sessions",
                "/api/distinct",
                "/api/summary",
                "/api/drop-rates",
                "/api/search?q=X",
                "/api/source/{name}",
                "/api/item/{name}",
                "/api/activity/{name}",
                "/api/analysis/sources|zones|items",
                "/api/loot?limit_rows=200",
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