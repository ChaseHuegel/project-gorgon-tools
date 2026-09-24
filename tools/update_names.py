#!/usr/bin/env python3
"""Regenerate the bundled name snapshots from the Project Gorgon wiki.

Run from the repository root:

    python tools/update_names.py

Writes ``src/gorgon_tracker/data/zones.txt`` and ``monsters.txt``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from gorgon_tracker import names  # noqa: E402


def main() -> int:
    out_dir = _REPO_ROOT / "src" / "gorgon_tracker" / "data"
    stats = names.update_names_files(out_dir)
    print(f"wrote {stats['zones']} zones and {stats['monsters']} monsters to {stats['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())