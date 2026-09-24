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
       ROUND(CAST(COUNT(*) AS REAL) / NULLIF(COALESCE(e.encounter_count, 0), 0), 4) AS drop_rate,
       MAX(ld.captured_at) AS last_seen
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
    since: int | None = None,
    until: int | None = None,
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
    if since is not None:
        clauses.append("ld.captured_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ld.captured_at <= ?")
        params.append(until)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _time_clause(
    *,
    since: int | None = None,
    until: int | None = None,
) -> tuple[str, list[Any]]:
    """Time filter for queries that use the table alias ``ld``."""
    clauses: list[str] = []
    params: list[Any] = []
    if since is not None:
        clauses.append("ld.captured_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("ld.captured_at <= ?")
        params.append(until)
    return ((" AND " if clauses else "") + " AND ".join(clauses)), params


def _orders(sort: str | None, order: str | None) -> str:
    if not sort or sort not in _SORT_COLUMNS:
        return ""
    direction = "ASC" if str(order or "asc").lower() == "asc" else "DESC"
    return f"ORDER BY {_SORT_COLUMNS[sort]} {direction}"


def _drop_rates(
    db: _DB,
    *,
    monster: str | None = None,
    monsters: list[str] | None = None,
    item: str | None = None,
    items: list[str] | None = None,
    zone: str | None = None,
    activity: str | None = None,
    status: str | None = "Linked",
    since: int | None = None,
    until: int | None = None,
    sort: str | None = None,
    order: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    where, params = _drop_rates_where(
        monster=monster, item=item, zone=zone, activity=activity, status=status, since=since, until=until
    )
    list_clauses: list[str] = []
    if monsters:
        list_clauses.append("ld.source IN (" + ",".join("?" * len(monsters)) + ")")
        params.extend(monsters)
    if items:
        list_clauses.append("ld.item IN (" + ",".join("?" * len(items)) + ")")
        params.extend(items)
    if list_clauses:
        where = (where + " AND " if where else "WHERE ") + " AND ".join(list_clauses)
    query = _DROP_RATES_BASE.format(where=where, order=_orders(sort, order), limit="")
    if offset is not None and limit is None:
        query += " LIMIT -1"
    elif limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    if offset is not None:
        query += " OFFSET ?"
        params.append(offset)
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
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = ["ld.status = 'Linked'"]
        params: list[Any] = []
        if source_like := source:
            clauses.append("ld.source LIKE ?")
            params.append(f"%{source_like}%")
        if item_like := item:
            clauses.append("ld.item LIKE ?")
            params.append(f"%{item_like}%")
        if zone:
            clauses.append("ld.zone = ?")
            params.append(zone)
        if activity:
            clauses.append("ld.activity = ?")
            params.append(activity)
        time_clause, time_params = _time_clause(since=since, until=until)
        params.extend(time_params)
        query = (
            "SELECT ld.zone, ld.source AS monster, ld.activity, ld.item,"
            " SUM(ld.amount) AS total_quantity, COUNT(*) AS drop_count,"
            " MAX(ld.captured_at) AS last_seen"
            " FROM loot_drops ld WHERE " + " AND ".join(clauses) + time_clause
        )
        query += " GROUP BY ld.zone, ld.source, ld.activity, ld.item ORDER BY zone, monster, item"
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
        offset: int | None = None,
        since: int | None = None,
        until: int | None = None,
        monsters: str | None = None,
        items: str | None = None,
    ) -> list[dict[str, Any]]:
        def split_csv(s: str | None) -> list[str] | None:
            return [p for p in (part.strip() for part in s.split(",")) if p] if s else None

        return _drop_rates(
            db,
            monster=monster,
            monsters=split_csv(monsters),
            item=item,
            items=split_csv(items),
            zone=zone,
            activity=activity,
            status=status,
            since=since,
            until=until,
            sort=sort,
            order=order,
            limit=max(1, min(limit, 5000)) if limit else None,
            offset=max(0, offset) if offset is not None else None,
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
    def search(
        q: str,
        limit: int = 20,
        since: int | None = None,
        until: int | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        if not q:
            return {"sources": [], "items": [], "activities": []}
        like = f"%{q}%"
        cap = max(1, min(limit, 100))

        def time_sql() -> tuple[str, list[int]]:
            clauses: list[str] = []
            params: list[int] = []
            if since is not None:
                clauses.append("captured_at >= ?")
                params.append(since)
            if until is not None:
                clauses.append("captured_at <= ?")
                params.append(until)
            return (" AND " + " AND ".join(clauses)) if clauses else "", params

        time_clause, time_params = time_sql()
        sources = db.rows(
            "SELECT source AS name, COUNT(*) AS drops, "
            "COUNT(DISTINCT encounter_id) AS encounters, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE source LIKE ?" + time_clause
            + " GROUP BY source ORDER BY drops DESC LIMIT ?",
            (like, *time_params, cap),
        )
        items = db.rows(
            "SELECT item AS name, COUNT(*) AS drops, COUNT(DISTINCT source) AS sources, "
            "MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE item LIKE ?" + time_clause
            + " GROUP BY item ORDER BY drops DESC LIMIT ?",
            (like, *time_params, cap),
        )
        activities = db.rows(
            "SELECT activity AS name, COUNT(*) AS drops "
            "FROM loot_drops WHERE activity LIKE ?" + time_clause
            + " GROUP BY activity ORDER BY drops DESC LIMIT ?",
            (like, *time_params, cap),
        )
        return {"sources": sources, "items": items, "activities": activities}

    @router.get("/api/source/{name:path}")
    def source_detail(name: str, since: int | None = None) -> dict[str, Any] | None:
        time_clause, time_params = _time_clause(since=since)
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE source = ?" + time_clause
            + " GROUP BY zone ORDER BY drops DESC",
            (name, *time_params),
        )
        items = _drop_rates(db, monster=name, status=None, since=since)
        return {"source": name, "zones": zones, "items": items}

    @router.get("/api/item/{name:path}")
    def item_detail(name: str, since: int | None = None) -> dict[str, Any] | None:
        sources = _drop_rates(db, item=name, status=None, since=since)
        time_clause, time_params = _time_clause(since=since)
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE item = ?" + time_clause
            + " GROUP BY zone ORDER BY drops DESC",
            (name, *time_params),
        )
        return {"item": name, "sources": sources, "zones": zones}

    @router.get("/api/activity/{name:path}")
    def activity_detail(name: str, since: int | None = None) -> dict[str, Any] | None:
        time_clause, time_params = _time_clause(since=since)
        sources = db.rows(
            "SELECT source AS monster, COUNT(*) AS drops, "
            "COUNT(DISTINCT encounter_id) AS encounters, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE activity = ?" + time_clause
            + " GROUP BY source ORDER BY encounters DESC, drops DESC",
            (name, *time_params),
        )
        items = db.rows(
            "SELECT item, COUNT(*) AS drops, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE activity = ?" + time_clause
            + " GROUP BY item ORDER BY drops DESC",
            (name, *time_params),
        )
        zones = db.rows(
            "SELECT zone, COUNT(*) AS drops, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE activity = ?" + time_clause
            + " GROUP BY zone ORDER BY drops DESC",
            (name, *time_params),
        )
        return {"activity": name, "sources": sources, "items": items, "zones": zones}

    @router.get("/api/zone/{name:path}")
    def zone_detail(name: str, since: int | None = None) -> dict[str, Any] | None:
        sources = _drop_rates(db, zone=name, status=None, since=since)
        time_clause, time_params = _time_clause(since=since)
        items = db.rows(
            "SELECT item, COUNT(*) AS drops, MAX(captured_at) AS last_seen "
            "FROM loot_drops WHERE zone = ?" + time_clause
            + " GROUP BY item ORDER BY drops DESC",
            (name, *time_params),
        )
        activities = db.rows(
            "SELECT activity, COUNT(*) AS drops FROM loot_drops WHERE zone = ?" + time_clause
            + " GROUP BY activity ORDER BY drops DESC",
            (name, *time_params),
        )
        return {"zone": name, "sources": sources, "items": items, "activities": activities}

    # --- chart aggregations --------------------------------------------------

    def _axis_filter(
        source: str | None,
        item: str | None,
        zone: str | None,
        activity: str | None,
        since: int | None = None,
        until: int | None = None,
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
        if since is not None:
            clauses.append("ld.captured_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("ld.captured_at <= ?")
            params.append(until)
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
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, item, zone, activity, since=since, until=until)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.append(status)
        encounters = "COUNT(DISTINCT ld.encounter_id)"
        rate = f"ROUND(CAST(COUNT(*) AS REAL) / NULLIF({encounters}, 0), 4)"
        rows = db.rows(
            "SELECT ld.source AS monster, COUNT(*) AS drops, SUM(ld.amount) AS quantity, "
            f"{encounters} AS encounters, "
            f"{rate} AS drop_rate, MAX(ld.captured_at) AS last_seen "
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
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, item, None, activity, since=since, until=until)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.append(status)
        rows = db.rows(
            f"SELECT ld.zone, COUNT(*) AS drops, COUNT(DISTINCT ld.source) AS sources, "
            f"MAX(ld.captured_at) AS last_seen FROM loot_drops ld "
            f"{where} GROUP BY ld.zone ORDER BY drops DESC LIMIT ?",
            tuple(params) + (max(1, min(limit, 500)),),
        )
        return rows

    @router.get("/api/analysis/items")
    def analysis_items(
        source: str | None = None,
        item: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
        status: str | None = "Linked",
        limit: int = 50,
        since: int | None = None,
        until: int | None = None,
    ) -> list[dict[str, Any]]:
        where, params = _axis_filter(source, item, zone, activity, since=since, until=until)
        if status:
            status_clause = "ld.status = ?"
            where = where + " AND " + status_clause if where else "WHERE " + status_clause
            params.append(status)
        rows = db.rows(
            f"SELECT ld.item, COUNT(*) AS drops, COUNT(DISTINCT ld.source) AS sources, "
            f"MAX(ld.captured_at) AS last_seen FROM loot_drops ld "
            f"{where} GROUP BY ld.item ORDER BY drops DESC LIMIT ?",
            tuple(params) + (max(1, min(limit, 500)),),
        )
        return rows

    @router.get("/api/stats")
    def stats(
        source: str | None = None,
        item: str | None = None,
        zone: str | None = None,
        activity: str | None = None,
        since: int | None = None,
        until: int | None = None,
    ) -> dict[str, Any]:
        where, params = _axis_filter(source, item, zone, activity, since=since, until=until)
        row = db.rows(
            f"SELECT COUNT(*) AS drops,"
            " COUNT(DISTINCT ld.encounter_id) AS encounters,"
            " COALESCE(SUM(ld.amount), 0) AS quantity,"
            " COUNT(DISTINCT ld.source) AS sources,"
            " COUNT(DISTINCT ld.item) AS items,"
            " COUNT(DISTINCT ld.zone) AS zones,"
            " SUM(CASE WHEN ld.status = 'Linked' THEN 1 ELSE 0 END) AS linked,"
            " SUM(CASE WHEN ld.status = 'Orphaned' THEN 1 ELSE 0 END) AS orphaned,"
            " COALESCE(MAX(ld.captured_at), 0) AS newest_at"
            f" FROM loot_drops ld {where}",
            tuple(params),
        )
        return row[0] if row else {}

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
                "/api/stats",
                "/api/source/{name}",
                "/api/item/{name}",
                "/api/activity/{name}",
                "/api/zone/{name}",
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