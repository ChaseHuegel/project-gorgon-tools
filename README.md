# gorgon-tracker

Cross-platform (Linux-first) loot and drop-rate tracker for **Project Gorgon**.

This is the Python successor to the PowerShell scripts in `loot-tracker/`. It captures
game data at runtime (packet inspection, chat-log tailing, and screen OCR), correlates
encounters with the loot they drop, and persists everything to a single SQLite database —
no post-processing, no CSV-as-database.

## Status

Active migration from the `loot-tracker/` PowerShell scripts. Full design and phase
tracking live in [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md).

## Requirements

- Python 3.11+
- `tshark` (Wireshark) — packet capture
- `tesseract` — screen OCR
- Project Gorgon running via Steam Proton/Wine (chat logs under the compatdata prefix)

## Quickstart (development)

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

gorgon-tracker config        # show effective configuration
gorgon-tracker run           # open a capture session, Ctrl-C to stop
gorgon-tracker status        # show sessions and event counts
```

See `gorgon-tracker.toml` for configuration and `gorgon-tracker --help` for commands.