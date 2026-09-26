"""Static SPA mount helper shared by the local and public FastAPI apps.

Both ``web`` (full local UI) and ``serve`` (public read-only UI) serve a Vite
build with SPA history fallback: exact static files win, anything else under a
client route returns ``index.html``, and unknown ``/api`` paths 404 instead of
falling through to the shell. See ``docs/api.md``.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve a Vite build from ``static_dir`` with history fallback."""
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
    return mimetypes.guess_type(path)[0] or "application/octet-stream"