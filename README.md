# gorgon-tracker

Cross-platform (Linux-first) loot and drop-rate tracker for **Project Gorgon**.

This is the Python successor to the PowerShell scripts in `loot-tracker/` (kept for
reference). It captures game data at runtime (packet inspection, chat-log tailing, and
screen OCR), correlates encounters with the loot they drop, and persists everything to a
single SQLite database — no post-processing, no CSV-as-database.

Design and phase tracking: [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md).

## Features

- One command (`run`) opens a capture session; capture happens passively in the background.
- Sources: live packet capture via `tshark`, incremental tailing of the Proton chat log,
  and OCR (tesseract) of the on-screen zone and target regions.
- Everything lands in SQLite (WAL): raw events + typed events + correlated `loot_drops`,
  grouped into sessions you can start and stop freely.
- Offline tools: `replay` historical `.pcapng`/JSON/chat/CSV bundles, `migrate` legacy
  PowerShell outputs, `export` a legacy-compatible CSV, and `serve` a read-only web API.
- `find-ports` auto-detects the game's ephemeral network ports; `calibrate` tunes OCR regions.

## Requirements

- Python 3.11+
- `tshark` (Wireshark) — packet capture
- `tesseract` — screen OCR
- Project Gorgon running via Steam Proton/Wine on the same host

## Install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                # or ".[serve]" for the web API, ".[dev]" for tests
```

Linux capture privileges (tshark needs raw sockets):

```sh
sudo setcap cap_net_raw,cap_net_admin=eip $(readlink -f "$(which tshark)")
# or: sudo usermod -a -G wireshark "$USER"   # and re-login
```

OCR: `sudo apt install tesseract-ocr` (add `tesseract-ocr-eng` if data is separate).

## Quickstart

```sh
gorgon-tracker config                 # show effective configuration
gorgon-tracker find-ports             # print the BPF filter for the running game
gorgon-tracker run                    # capture in the foreground; Ctrl-C to stop
gorgon-tracker run --daemon           # background; stop with `gorgon-tracker stop`
gorgon-tracker status                 # sessions + per-source event counts
gorgon-tracker serve                  # read-only API at http://127.0.0.1:8000
```

Create a `gorgon-tracker.toml` (see the sample in this repo) to set your Steam library's
chat log path automatically; the default probes common paths:

```toml
[db]
path = "data/gorgon.db"

[capture]
interface = "eth0"        # or "auto"; set after `find-ports`
bpf = "tcp.port == 45000 or tcp.port == 45001"

[chat]
# auto-detected when empty; set explicitly if the game is on a custom Steam library:
# log_dir = "/mnt/games/steamapps/compatdata/1118200/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"

[ocr.zones]
region = [1680, 0, 180, 50]

[ocr.targets]
region = [1021, 691, 213, 114]
```

### Migrating historical data

```sh
# Replay old packet captures (auto-discovers tshark JSON, chat logs, zone/target CSVs):
gorgon-tracker replay captures/*.pcapng chatsession.log zones.csv targets.csv

# Import legacy PowerShell outputs (loot.csv, zones.csv, targets.csv, parsed-*.txt):
gorgon-tracker migrate loot.csv zones.csv targets.csv

# Backwards-compatible CSV export whenever you still want a spreadsheet:
gorgon-tracker export --out loot.csv
```

Systemd (optional):

```sh
sudo install -m 0644 packaging/gorgon-tracker.service /etc/systemd/system/gorgon-tracker.service
sudo systemctl daemon-reload && sudo systemctl enable --now gorgon-tracker.service
```

## Development

```sh
pip install -e ".[dev,serve]"
pytest
ruff check src tests
mypy src/gorgon_tracker
```