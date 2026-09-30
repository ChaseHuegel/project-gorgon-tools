"""Locate external binaries that gorgon-tracker shells out to.

tesseract is not bundled with the executable. The config key ``ocr.tesseract_path``
holds either a bare command name (resolved on PATH) or an explicit path. This module
resolves that value to a path a subprocess can run, and reports a per-OS install hint
when the binary is missing. See docs/packaging.md.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_TESSERACT_HINTS = {
    "linux": "install tesseract-ocr (apt): `sudo apt install tesseract-ocr`",
    "win32": "install Tesseract and set [ocr] tesseract_path to the full tesseract.exe path",
}


def _platform_hint(hints: dict[str, str]) -> str:
    return hints.get(sys.platform, hints["linux"])


def resolve_binary(configured: str) -> Path | None:
    """Return the usable path for ``configured``, or None when unavailable.

    A bare command name resolves through PATH. An explicit path is returned
    only when the file exists. This matches how a packaged executable finds
    separately-installed tooling.
    """
    candidate = Path(configured)
    if candidate.name == configured and candidate.parent == Path("."):
        found = shutil.which(configured)
        return Path(found) if found else None
    return candidate if candidate.is_file() else None


def resolve_tesseract(configured: str) -> Path | None:
    """Resolve the tesseract binary, returning None when missing."""
    return resolve_binary(configured)


def tesseract_hint() -> str:
    """Return the platform-specific install hint for tesseract."""
    return _platform_hint(_TESSERACT_HINTS)