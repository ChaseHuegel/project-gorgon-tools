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
gorgon-tracker web                    # full browser UI at http://127.0.0.1:8000
```

### Web UI

`gorgon-tracker web` opens a browser UI that configures the tool, starts/stops the
capture daemon, and lets you browse loot data — no terminal needed for everyday use:

- **Status** — start/stop the daemon, live per-source event counts, setup warnings, and a
  live **tailed chat log** panel (raw game chat, with loot/bury lines highlighted).
- **Dashboard** — drop-rate charts and summary tables (via Recharts).
- **Loot** — filter a stream of correlated drops; export to the legacy CSV.
- **Sessions** — browse capture sessions and their timing.
- **Config** — edit `gorgon-tracker.toml` from forms (only changed keys are written,
  so comments and formatting survive).
- **Calibrate** — drag a region on a live snapshot to tune OCR zones/targets.
- **Import / Export** — find ports, and replay/migrate historical captures by file
  upload or server path.

The UI is a Vite/React bundle that ships inside the pip package, so nothing extra is
needed at runtime (`--host --port --config --db` and OCR/capture prerequisites apply
as documented below).

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

### Name correction

OCR reads of zone and monster names are corrected against canonical lists of
known Project Gorgon names. The lists ship with the package (fetched from the
[Project Gorgon wiki](https://wiki.projectgorgon.com)) and can be refreshed:

```sh
# Fetch the latest zone/monster name lists from the wiki into the user data dir:
gorgon-tracker update-names
```

The web UI has an **Update names from wiki** button on the Import / Export page.
A running capture daemon picks up refreshed lists automatically. Correction is
conservative: text is only rewritten on a high-confidence fuzzy match, and
near-ties are left untouched. Override or extend the lists by dropping
`zones.txt` / `monsters.txt` (one name per line, `#` comments allowed) into the
user data dir (`~/.local/share/gorgon-tracker/names`), or point `[names] data_dir`
at your own directory:

```toml
[names]
enabled = true
# data_dir = "/path/to/my/name/lists"

[names.zones]        # fuzzy thresholds in percent (0-100)
ratio = 90.0
partial_ratio = 85.0

[names.monsters]
ratio = 90.0
partial_ratio = 85.0
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

### Frontend (Node)

The `web/` SPA is optional to develop — the built bundle already ships in the package
(`src/gorgon_tracker/static`). If you want to work on the UI, install Node 20/22:

```sh
cd web
npm install
npm run dev        # Vite dev server, proxies /api to a running `gorgon-tracker web/serve` (or `BACKEND=` to point elsewhere)
npm run typecheck  # tsc --noEmit
npm run test       # vitest
npm run build      # bundles into ../src/gorgon_tracker/static, served by FastAPI
```