"""Full web UI: read API + control endpoints + built SPA (served by FastAPI)."""

from __future__ import annotations

import io
import shutil
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import config_write as config_write_mod
from . import control, db
from .serve import build_read_router

_APP_ROOT = Path(__file__).resolve().parent
_STATIC_DIR = _APP_ROOT / "static"


def _upload_dir(db_path: str) -> Path:
    directory = Path(db_path).resolve().parent / "uploads"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _save_uploads(files: list[UploadFile], target_dir: Path) -> list[Path]:
    saved: list[Path] = []
    for upload in files:
        name = Path(upload.filename or "upload").name
        dest = target_dir / name
        with dest.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        saved.append(dest)
    return saved


def _chat_line_kind(text: str) -> str | None:
    """Classify a raw chat line for the UI: 'loot', 'bury', or None (other chat)."""
    from .correlator import BuryEvent, LootEvent
    from .parsers import chat as chat_parser

    event = chat_parser.parse_chat_line(text)
    if isinstance(event, LootEvent):
        return "loot"
    if isinstance(event, BuryEvent):
        return "bury"
    return None


def build_control_router(db_path: str, config_path: str | None = None) -> APIRouter:
    """Control endpoints for configuring, running/stopping the capture daemon."""
    from . import export as export_mod
    from . import migrate as migrate_mod
    from . import names as names_mod
    from . import ports as ports_mod
    from . import replay as replay_mod

    router = APIRouter(prefix="/api")

    def _cfg() -> Any:
        return config_write_mod.load_config_path(config_path)

    # --- daemon & status ----------------------------------------------------

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

    # --- chat log tail ------------------------------------------------------

    @router.get("/chat/tail")
    def chat_tail(limit: int = 500) -> dict[str, Any]:
        from .config import default_chat_log_dir
        from .sources import chat_tail as chat_tail_mod

        cfg = _cfg()
        raw_dir = cfg.chat.log_dir.strip() or default_chat_log_dir()
        result: dict[str, Any] = {
            "found": False,
            "log_dir": str(Path(raw_dir)) if raw_dir else None,
            "file": None,
            "mtime_ms": None,
            "start_offset": 0,
            "reason": "",
            "lines": [],
        }
        if not raw_dir:
            result["reason"] = "chat log directory not configured"
            return result
        log_dir_path = Path(raw_dir)
        if not log_dir_path.is_dir():
            result["reason"] = "chat log directory not found"
            return result
        try:
            log = chat_tail_mod.newest_log(log_dir_path)
            if log is None:
                result["reason"] = "no chat logs in directory"
                return result
            stat = log.stat()
            start_offset, chat_lines = chat_tail_mod.read_tail(log, max(1, min(limit, 5000)))
        except OSError:
            result["reason"] = "chat log unreadable"
            return result
        result["found"] = True
        result["file"] = log.name
        result["mtime_ms"] = stat.st_mtime_ns // 1_000_000
        result["start_offset"] = start_offset
        result["lines"] = [{"text": text, "kind": _chat_line_kind(text)} for text in chat_lines]
        return result

    # --- config -------------------------------------------------------------

    @router.get("/config")
    def get_config() -> dict[str, Any]:
        return {
            "path": str(config_write_mod.active_config_path(config_path)),
            "config": _cfg().model_dump(),
        }

    @router.put("/config")
    def put_config(payload: dict[str, Any]) -> dict[str, Any]:
        updates = payload.get("updates")
        if not isinstance(updates, dict) or not updates:
            raise HTTPException(status_code=422, detail="'updates' must be a non-empty object of dotted-key changes")
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

    # --- ports --------------------------------------------------------------

    @router.post("/ports/discover")
    def discover_ports(write_config: bool = Body(default=False, embed=True)) -> dict[str, Any]:
        tcp, udp = ports_mod.discover_ports()
        if not tcp and not udp:
            return {"tcp": [], "udp": [], "bpf": "", "persisted": False, "found": False}
        bpf = ports_mod.build_bpf(sorted(tcp), sorted(udp))
        persisted = False
        if write_config:
            config_write_mod.write_updates(
                {"capture.ports": sorted(tcp | udp), "capture.bpf": bpf}, config_path
            )
            persisted = True
        return {"tcp": sorted(tcp), "udp": sorted(udp), "bpf": bpf, "persisted": persisted, "found": True}

    # --- offline operations (upload + server paths) -------------------------

    @router.post("/replay")
    def replay(
        paths: list[str] = Form(default=[]),  # noqa: B008 - FastAPI dependency
        chat_dir: str | None = Form(default=None),
        files: list[UploadFile] = File(default=[]),  # noqa: B008 - FastAPI dependency
    ) -> dict[str, Any]:
        input_paths = [Path(p) for p in paths] + _save_uploads(files, _upload_dir(db_path))
        inputs = replay_mod.expand_inputs(input_paths)
        if not inputs:
            raise HTTPException(status_code=422, detail="no input files provided")
        cfg = _cfg()
        conn = db.connect(db_path)
        db.migrate(conn)
        try:
            stats = replay_mod.run_replay(
                conn, cfg, inputs, Path(chat_dir) if chat_dir else None, sys.platform
            )
        finally:
            conn.close()
        return {"inputs": [str(p) for p in inputs], **stats}

    @router.post("/migrate")
    def migrate(
        paths: list[str] = Form(default=[]),  # noqa: B008 - FastAPI dependency
        kind: str | None = Form(default=None),
        files: list[UploadFile] = File(default=[]),  # noqa: B008 - FastAPI dependency
    ) -> dict[str, Any]:
        input_paths = [Path(p) for p in paths] + _save_uploads(files, _upload_dir(db_path))
        if not input_paths:
            raise HTTPException(status_code=422, detail="no input files provided")
        cfg = _cfg()
        conn = db.connect(db_path)
        db.migrate(conn)
        try:
            results = [
                {"file": str(p), **migrate_mod.import_bundle(conn, cfg, p, kind, sys.platform)}
                for p in input_paths
            ]
        finally:
            conn.close()
        return {"imported": results}

    @router.get("/export")
    def export(since: str | None = None) -> Response:
        from .timeutil import iso_to_ms

        since_ms = iso_to_ms(since) if since else None
        conn = db.connect(db_path)
        db.migrate(conn)
        try:
            text = export_mod.export_loot_csv_text(conn, since_ms)
        finally:
            conn.close()
        return Response(
            text,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="gorgon-loot.csv"'},
        )

    # --- name lists ----------------------------------------------------------

    @router.get("/names")
    def names_status() -> dict[str, Any]:
        return names_mod.names_info(_cfg().names)

    @router.post("/names/update")
    def names_update() -> dict[str, Any]:
        from urllib.error import URLError

        cfg = _cfg()
        out_dir = Path(cfg.names.data_dir) if cfg.names.data_dir else names_mod.default_names_dir()
        try:
            return names_mod.update_names_files(out_dir)
        except (URLError, OSError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"wiki name fetch failed: {exc}") from exc

    # --- calibration --------------------------------------------------------

    @router.get("/calibrate/screens")
    def calibrate_screens() -> dict[str, Any]:
        from .parsers import ocr as ocr_mod

        try:
            return {"monitors": ocr_mod.list_monitors()}
        except ocr_mod.ScreenCaptureError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/calibrate/snapshot")
    def calibrate_snapshot(x: int, y: int, w: int, h: int, color: bool = False) -> Response:
        from .parsers import ocr as ocr_mod

        try:
            image = ocr_mod.grab_region([x, y, w, h])
        except ocr_mod.ScreenCaptureError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not color:
            image = ocr_mod.grayscale(image)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png")

    @router.get("/calibrate/preview")
    def calibrate_preview(x: int, y: int, w: int, h: int) -> dict[str, str]:
        from .parsers import ocr as ocr_mod

        cfg = _cfg()
        try:
            raw = ocr_mod.raw_capture_text(cfg, [x, y, w, h])
        except ocr_mod.ScreenCaptureError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"text": ocr_mod.sanitize_text(raw), "raw": " ".join(raw.split())}

    @router.post("/calibrate/region")
    def calibrate_region(payload: dict[str, Any]) -> dict[str, Any]:
        kind = payload.get("kind")
        region = payload.get("region")
        if kind not in ("zones", "targets"):
            raise HTTPException(status_code=422, detail="kind must be 'zones' or 'targets'")
        if not isinstance(region, list) or len(region) != 4:
            raise HTTPException(status_code=422, detail="region must be [x, y, width, height]")
        try:
            cfg = config_write_mod.write_updates({f"ocr.{kind}.region": region}, config_path)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"path": str(config_write_mod.active_config_path(config_path)), "config": cfg.model_dump()}

    # --- file browser -------------------------------------------------------

    @router.get("/files")
    def files_list(path: str = "", _limit: int = 500) -> dict[str, Any]:
        base = Path(path).expanduser() if path else Path.home()
        if not base.is_dir():
            raise HTTPException(status_code=404, detail=f"not a directory: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(base.iterdir())[:max(1, min(_limit, 2000))]:
            entries.append({"name": child.name, "path": str(child), "is_dir": child.is_dir()})
        return {"path": str(base), "entries": entries}

    return router


def build_web_app(db_path: str, config_path: str | None = None, static_dir: Path | None = None) -> FastAPI:
    """Build the full UI FastAPI app (read API + control endpoints + SPA)."""
    read_router, _ = build_read_router(db_path, include_index=False)
    app = FastAPI(title="gorgon-tracker UI", version="0.1.0", description="Project Gorgon loot data")
    app.include_router(read_router)
    app.include_router(build_control_router(db_path, config_path))
    _ensure_schema(db_path)
    static = static_dir or _STATIC_DIR
    if static.is_dir():
        _mount_spa(app, static)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the Vite build and fall back to ``index.html`` for client routes."""
    index_html = (static_dir / "index.html").read_bytes()
    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Response:
        if full_path.split("/")[0] == "api":
            raise HTTPException(status_code=404, detail="unknown API route")
        if full_path and (static_dir / full_path).is_file():
            return Response((static_dir / full_path).read_bytes(), media_type=_guess_media(full_path))
        return Response(index_html, media_type="text/html")


def _guess_media(path: str) -> str:
    import mimetypes

    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _ensure_schema(db_path: str) -> None:
    conn = db.connect(db_path)
    try:
        db.migrate(conn)
    finally:
        conn.close()


def run_web(db_path: str, config_path: str | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_web_app(db_path, config_path), host=host, port=port)