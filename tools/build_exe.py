#!/usr/bin/env python3
"""Build a standalone one-file executable with Nuitka.

Run from the repository root. The build must run on the target OS: a Linux
binary builds on Linux, a Windows executable on Windows. See docs/packaging.md.

    python tools/build_exe.py

Writes the executable to ``dist/bundle/gorgon-tracker`` (a ``.exe`` suffix is
added automatically on Windows).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
_ENTRY = _REPO_ROOT / "src" / "gorgon_tracker" / "__main__.py"
_OUTPUT_DIR = _REPO_ROOT / "dist" / "bundle"

_INCLUDE_MODULES = [
    "fastapi",
    "uvicorn",
    "starlette",
    "pydantic",
    "httpx",
    "multipart",
]


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        "--include-package=gorgon_tracker",
        "--include-package-data=gorgon_tracker",
    ]
    for module in _INCLUDE_MODULES:
        cmd += [f"--include-module={module}"]
    cmd += [
        f"--output-dir={_OUTPUT_DIR}",
        "--output-filename=gorgon-tracker",
        str(_ENTRY),
    ]
    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())