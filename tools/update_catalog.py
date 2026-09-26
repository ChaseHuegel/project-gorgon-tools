#!/usr/bin/env python3
"""Regenerate the bundled catalog snapshots from the official game data CDN.

Run from the repository root:

    python tools/update_catalog.py

Writes the compact ``src/gorgon_tracker/data/items.json``, ``areas.json``, and
``version.txt`` snapshots (canonical item slug -> display metadata, and internal
area id -> friendly name).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from gorgon_tracker import catalog  # noqa: E402

_OUT_DIR = Path(__file__).resolve().parent.parent / "src/gorgon_tracker/data"


def main() -> None:
    stats = catalog.update_catalog_files(_OUT_DIR)
    print(
        f"Updated: v{stats['version']} items={stats['items']} areas={stats['areas']}\n"
        f"  {stats['path']}"
    )


if __name__ == "__main__":
    main()