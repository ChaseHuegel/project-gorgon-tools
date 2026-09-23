"""Full web UI: read API + control endpoints + built SPA (served by FastAPI).

Phase 0 is a thin wrapper over the read-only app; control endpoints are added
in later phases of ``FRONTEND-PLAN.md``.
"""

from __future__ import annotations

from typing import Any


def build_web_app(db_path: str, config_path: str | None = None) -> Any:
    """Build the full UI FastAPI app."""
    from .serve import build_app

    return build_app(db_path)


def run_web(db_path: str, config_path: str | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(build_web_app(db_path, config_path), host=host, port=port)