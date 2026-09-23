"""Full web UI: read API + control endpoints + built SPA (served by FastAPI)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import ValidationError

from . import config_write as config_write_mod
from . import control, db
from .serve import build_read_router


def build_control_router(db_path: str, config_path: str | None = None) -> APIRouter:
    """Control endpoints for configuring, running/stopping the capture daemon."""
    router = APIRouter(prefix="/api")

    def _cfg() -> Any:
        return config_write_mod.load_config_path(config_path)

    @router.get("/status")
    def status() -> dict[str, Any]:
        cfg = _cfg()
        conn = db.connect(db_path)
        db.migrate(conn)
        try:
            overview = db.status_overview(conn)
        finally:
            conn.close()
        return {
            "db_path": str(Path(db_path).resolve()),
            "config_path": str(config_write_mod.active_config_path(config_path)),
            "config_db_path": cfg.db.path,
            "sessions_total": overview["sessions_total"],
            "open_session_id": overview["open_session_id"],
            "open_session_counts": overview["open_session_counts"],
            "daemon": control.daemon_status(db_path),
            "warnings": control.setup_warnings(cfg),
        }

    @router.get("/config")
    def get_config() -> dict[str, Any]:
        return {
            "path": str(config_write_mod.active_config_path(config_path)),
            "config": _cfg().model_dump(),
        }

    @router.put("/config")
    def put_config(payload: dict[str, Any]) -> dict[str, Any]:
        updates = payload.get("updates")
        if not isinstance(updates, dict):
            raise HTTPException(status_code=422, detail="'updates' must be an object of dotted-key changes")
        try:
            cfg = config_write_mod.write_updates(updates, config_path)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"path": str(config_write_mod.active_config_path(config_path)), "config": cfg.model_dump()}

    @router.post("/daemon/start")
    def start_daemon() -> dict[str, Any]:
        parent = Path(db_path).resolve().parent
        parent.mkdir(parents=True, exist_ok=True)
        log_path = str(parent / "gorgon-tracker.log")
        return control.daemon_start(db_path, config_path, log_path)

    @router.post("/daemon/stop")
    def stop_daemon() -> dict[str, Any]:
        return control.daemon_stop(db_path)

    return router


def build_web_app(db_path: str, config_path: str | None = None) -> FastAPI:
    """Build the full UI FastAPI app (read API + control endpoints)."""
    read_router, _ = build_read_router(db_path)
    app = FastAPI(title="gorgon-tracker UI", version="0.1.0", description="Project Gorgon loot data")
    app.include_router(read_router)
    app.include_router(build_control_router(db_path, config_path))
    _ensure_schema(db_path)
    return app


def _ensure_schema(db_path: str) -> None:
    conn = db.connect(db_path)
    try:
        db.migrate(conn)
    finally:
        conn.close()


def run_web(db_path: str, config_path: str | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_web_app(db_path, config_path), host=host, port=port)