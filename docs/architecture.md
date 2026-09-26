# Architecture

This doc describes gorgon-tracker as built. It is the canonical as-built architecture reference. The development plans that describe how the project got here live in `docs/MIGRATION_PLAN.md` and `docs/FRONTEND-PLAN.md` (historical tracker docs).

## Overview

gorgon-tracker captures Project Gorgon game data at runtime, correlates loot pickups with the monsters that dropped them, and stores everything in one SQLite database. The reverse-engineered formats it reads are specified in `docs/specs/`.

```text
sources (producer threads)              pipeline thread (single SQLite writer)
   packet  (tshark -T fields)    ─┐
   chat    (ChatLogs tail)      ───┤
   playerlog (Player.log tail) ────┼─► queue(10000) ─► parser ─► Correlator ─► DbWriter
   ocr zone (tesseract)        ────┤                                          │
   ocr target (tesseract)      ─┘                                          SQLite (WAL)
                                                                               │
read side:  serve / web (FastAPI) ─ blend read API + SSE over the same DB ─────┘
offline:    replay / migrate feed the same parser + correlator into the DB
```

Every event keeps `time_ms` in UTC epoch milliseconds; SQLite stores the same (`src/gorgon_tracker/schema.sql:2`).

## Process model

- **Capture daemon** (`gorgon-tracker run`): the only writer. Runs the pipeline; owns the SQLite connection on its own thread. Started with `run --daemon` (double-fork + `setsid`, `daemon.py:34-52`) or from the web UI. One instance per DB, tracked by a pidfile at `<db parent>/gorgon-tracker.pid`.
- **Web server** (`gorgon-tracker web`) and **serve** (`gorgon-tracker serve`): read from the same DB in WAL mode. The web process does config writes, replay, migrate, export, port discovery, and calibration inline; it never runs the capture pipeline.
- **Offline commands** (`replay`, `migrate`): open their own session and feed the same parsers + correlator, then close the session as retrospective.

Single-writer rule: only the pipeline thread touches the SQLite connection during capture. Everything else opens short-lived read connections (`serve.py:229-254`).

## Module map

All modules in `src/gorgon_tracker/`.

### Entry and CLI

| Module | Role |
|---|---|
| `__init__.py`, `__main__.py` | Package version; `python -m gorgon_tracker` entry. |
| `cli.py` | Typer app; one command per function. See CLI commands table below. |
| `config.py` | Pydantic `TrackerConfig`; load, validate, auto-discover chat/playerlog paths. Full schema in `docs/development.md`. |
| `config_write.py` | tomlkit partial write-back that preserves comments; used by the web UI. |
| `daemon.py` | Double-fork daemonize; pidfile helpers. |
| `control.py` | Daemon start/stop/status; setup warnings. |
| `timeutil.py` | Timestamp parsing/formatting (see `docs/specs/csv-formats.md`). |

### Capture and offline ingest

| Module | Role | Spec |
|---|---|---|
| `pipeline.py` | Wires producers → bounded queue → dispatch. Single SQLite connection, 1 s commit cadence, graceful drain on stop. | — |
| `sources/tshark_live.py` | Live packet frames (`tshark -T fields`). | `docs/specs/packets.md` |
| `sources/chat_tail.py` | Tails the newest chat log; handles rotation by dev+inode. | `docs/specs/chat-log.md` |
| `sources/player_log.py` | Tails `Player.log`; one persistent parser spans polls; optional `Player-prev.log` backfill. | `docs/specs/player-log.md` |
| `sources/ocr.py` | Zone/target OCR producers; change detection + heartbeat. | `docs/specs/ocr.md` |
| `parsers/chat.py` | Chat line → `LootEvent`/`BuryEvent`/`ActivityEvent`. | `docs/specs/chat-log.md` |
| `parsers/packets.py` | tshark JSON frames → `SourceEvent`; hex decode + cleanup. | `docs/specs/packets.md` |
| `parsers/playerlog.py` | `Player.log` lines → correlation events; missed-loot window. | `docs/specs/player-log.md` |
| `parsers/ocr.py` | mss/portal grab, grayscale, tesseract, sanitize. | `docs/specs/ocr.md` |
| `parsers/csvs.py` | Legacy zones/targets/loot CSV readers. | `docs/specs/csv-formats.md` |
| `ports.py` | Game port discovery via `ss`; builds `tcp.port == X or ...` filter. | `docs/specs/packets.md` |
| `replay.py` | Offline ingest of pcaps/JSON/chat/Player.log/CSV through the same parsers + correlator. | `docs/specs/correlation.md` |
| `migrate.py` | Import legacy PowerShell outputs (CSV + parsed JSON). | `docs/specs/csv-formats.md` |
| `sniff_inspect.py` | Packet investigation; inventories plaintext strings; raw pcap retained. | `docs/specs/packets.md` |

### Correlation and persistence

| Module | Role | Spec |
|---|---|---|
| `correlator.py` | Streaming correlation: links loot to monsters, assigns activity. | `docs/specs/correlation.md` |
| `ingest.py` | `DbWriter`: raw events + typed tables; loud dedup hash; item learning. | `docs/api.md` (payload shapes) |
| `db.py` | Connect (WAL), migrations, session lifecycle, typed inserts, overrides, clear. | Schema below |
| `schema.sql` | Baseline DDL (migration v1). | Schema below |
| `export.py` | Legacy-compatible CSV export (base + evidence columns). | `docs/specs/csv-formats.md` |

### Reference data

| Module | Role | Spec |
|---|---|---|
| `catalog.py` | Item/zone catalogs from the game CDN; slug → display name; zone id → friendly name. | `docs/specs/cdn-catalog.md` |
| `itemdb.py` | Unity slug `(base, code)` split; display-name inference. | `docs/specs/cdn-catalog.md` |
| `names.py` | OCR name correction (conservative fuzzy) + wiki fetch; hot reload. | `docs/specs/cdn-catalog.md` |
| `calibrate.py` | Interactive OCR region tuning. | `docs/specs/ocr.md` |

### Web

| Module | Role | Spec |
|---|---|---|
| `serve.py` | Read-only FastAPI router (shared by `serve` and `web`); index banner. | `docs/api.md` |
| `web.py` | Control endpoints + SPA serving; full UI app. | `docs/api.md` |
| `stream.py` | SSE generators over the DB. | `docs/api.md` |

## Database

- Connection: WAL, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000` (`db.py:114-123`).
- Migrations: `schema_migrations` table + `PRAGMA user_version`; each migration is `executescript` then a recorded version bump (`db.py:126-143`).
- Migration history (`MIGRATIONS`, `db.py:93-99`):
  - v1 `schema.sql`: baseline tables + views.
  - v2: `loot_drops` evidence columns (`linked_via`, `monster_*`, `target_*`, `corroborated_by_search`); `loot_overrides` (manual corrections).
  - v3: Unity provenance (`instance_id`, `entity_id`, `item_code_id`, `item_display`, `missed`, `killer_json`); `corpse_searches`; `items` (learned names).
  - v4: catalog metadata on `items` (`item_value`, `max_stack`, `keywords_json`, `icon_id`, `data_version`).
  - v5: `corpse_searches.extractions_json` (corpse-description audit).
- Tables: `sessions`, `raw_events`, `sources`, `loot`, `burials`, `target_sightings`, `zone_changes`, `encounters`, `loot_drops`, `loot_overrides`, `corpse_searches`, `items`, `schema_migrations`.
- Views: `v_sessions`, `v_summary`, `v_drop_rates` (see `docs/specs/correlation.md` for rates semantics).
- `items` is preseeded from the catalog when empty (`seed_from_catalog`); canonical names never overwrite learned ones.

## CLI commands

Mapper: each `@app.command()` in `src/gorgon_tracker/cli.py` is a `gorgon-tracker <name>` command.

| Command | Purpose |
|---|---|
| `run` | Live capture pipeline (foreground or `--daemon`). |
| `status` | Session table + per-source event counts. |
| `stop` | SIGTERM a running daemon by pidfile. |
| `find-ports` | Detect game ports → BPF filter. |
| `calibrate` | Tune an OCR region interactively. |
| `sniff-inspect` | Capture game traffic; inventory plaintext strings. |
| `replay` | Offline-ingest historical captures into a retrospective session. |
| `migrate` | Import legacy PowerShell outputs. |
| `update-names` | Fetch name lists from the wiki. |
| `update-catalog` | Fetch item/zone catalogs from the CDN; re-seed the DB. |
| `export` | Legacy-compatible CSV export. |
| `serve` | Read-only API server. |
| `web` | Full UI (read + control API + SPA). |
| `config` | Print effective config as JSON. |
| `version` | Print package version. |

## Frontend structure

`web/` is a Vite + React + TypeScript SPA. Key files (`web/src/`):

| Path | Role |
|---|---|
| `App.tsx`, `main.tsx` | Router shell (sidebar layout). |
| `api/client.ts`, `api/types.ts` | Typed fetch wrapper + backend JSON types. |
| `hooks/useApi.ts`, `hooks/useSse.ts` | Data fetch (debounced, filterable) and SSE subscription. |
| `pages/Status.tsx` | Daemon toggle, live counters, chat tail, warnings. |
| `pages/Dashboard.tsx` | Overview / Rates / Find / Matrix tabs (Recharts). |
| `pages/Loot.tsx` | Correlated-drop table with filters, overrides, SSE live rows. |
| `pages/Sessions.tsx` | Session list + counts. |
| `pages/Config.tsx` | Sectioned config forms via dotted-key diff. |
| `pages/Calibrate.tsx` | Snapshot, drag region, OCR preview, save. |
| `pages/ImportExport.tsx` | Replay/migrate upload, find-ports, export, catalog/names update. |
| `components/` | `DataTable`, `StatusBadge`, `FormField`, `FilePicker`, `RegionPicker`, `ConfirmDialog`, `Page`. |

The Vite build outputs to `src/gorgon_tracker/static/` (shipped in the pip package). Dev uses a Vite proxy to `http://127.0.0.1:8000` (or `BACKEND=`).

## Conventions across the codebase

- All timestamps are UTC epoch milliseconds (schema.sql:2, timeutil).
- Event payloads flow as frozen dataclasses from `correlator.py`; parsers return them, `_dispatch` routes by type (`pipeline.py:46-84`).
- Sources are `Callable[[threading.Event], None]` producer functions registered in `build_producers` (`pipeline.py:96-122`).
- Secrets: none. Configuration is TOML via pydantic; user data lives under `~/.local/share/gorgon-tracker/` (names, catalog) unless overridden.