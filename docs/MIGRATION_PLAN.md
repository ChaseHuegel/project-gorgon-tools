# gorgon-tracker — Migration Plan & Development Tracker

Persistent development plan for evolving the PowerShell loot-collection scripts into a single-entrypoint, cross-platform (Linux-first) background tool that writes directly to SQLite.

The port is complete. The canonical reference docs have moved:

- As-built architecture, module map, DB, and CLI table: `docs/architecture.md`.
- Reverse-engineered formats and correlation behavior: `docs/specs/` (chat-log, player-log, packets, correlation, cdn-catalog, csv-formats, ocr). The port specifics that once lived in the numbered sections of this file now live there.
- Web UI that configures/runs/browses this tool is tracked separately in [`FRONTEND-PLAN.md`](FRONTEND-PLAN.md).

**Status legend:** `[ ]` = not started, `[/]` = in progress, `[x]` = done. Agents must update the tracker section ("Development Tracker") at the bottom of this file as work progresses.

---

## 1. Context

This repo currently contains a set of Windows PowerShell scripts that collect loot and drop-rate information from the game Project Gorgon. The scripts are run manually per gaming session and post-processed into a CSV that is manually copied into Google Sheets, which acts as the "database."

That process is fragile and high-maintenance. The goal is to replace it with one unified tool that:

- Runs cross-platform with a primary target of **Linux**.
- Runs in the background and is started/stopped freely between gaming sessions with little setup (passive collection).
- Evaluates data **at runtime** (real-time streaming pipeline) rather than in a separate post-processing step.
- Persists all data (raw capture + processed results) to **SQLite** instead of CSV.
- Can later grow a **web frontend** for browsing loot data.

### 1.1 Locked decisions (do not revisit without the user)

| Decision | Choice | Rationale |
|---|---|---|
| Language | **Python 3.11+** | Best cross-platform OCR/capture story, stdlib `sqlite3`, `asyncio`, fast iteration, trivial FastAPI future. (C#/.NET 8 was the evaluated alternative; rejected for weaker Linux OCR/screen-capture ergonomics.) |
| Game environment | **Steam Proton/Wine** | Chat logs live under the Proton compatdata pfx; capture on the same host. |
| Packet capture backend | **tshark (streaming stdout)** | Reuses existing Wireshark dependency; kernel-level BPF filtering; no embedded native capture lib. |
| Historical data | **Migrate it** | Build `replay` (.pcapng) + `migrate csv` paths so the new DB starts complete. |

---

## 2. History summary

The legacy Windows-only scripts remain in `loot-tracker/` as reference material and are not modified. The port happened in ordered phases (scaffold → offline core with golden tests → live packet → live chat → OCR → assembled `run` → CSV compat + web). All phases are complete; the tracker below records the items.

The correlator port, the packet/chat/player-log formats, the OCR pipeline, and the target architecture are documented canonically in `docs/architecture.md` and `docs/specs/`. The user-facing setup and commands live in `README.md`.

---

## Development Tracker

Agents working on this project must update this section. Mark items `[x]` only when verified (tests/lint pass). Keep one item `[/]` at a time.

### Phase 0 — Scaffold
- [x] Repo layout: `src/gorgon_tracker/` package + `tests/`
- [x] `pyproject.toml` (uv/venv ready, dev deps: pytest, mypy, ruff)
- [x] `config.py` — TOML load + pydantic validation of §5.1 schema
- [x] `cli.py` — typer skeleton with all commands stubbed
- [x] `db.py` + `schema.sql` — sqlite bootstrap, WAL, `schema_migrations`, `PRAGMA user_version`
- [x] Exit criteria: `run` opens DB, `status` reports a session

### Phase 1 — Offline core (parsers + correlator + replay/migrate)
- [x] `parsers/packets.py` — hex decode, monster-name cleanup, flags, session windows (§3.2)
- [x] `parsers/chat.py` — loot/bury regexes (§3.1)
- [x] `correlator.py` — streaming port of CompileLootEvents rules (§3.3)
- [x] `replay.py` — offline `.pcapng` ingest through same parser+correlator (accepts pcapng via tshark, pre-extracted tshark JSON, chat logs, zone/target CSVs)
- [x] `migrate.py` — import old CSVs / parsed JSON as historical sessions
- [x] Golden-test fixtures (expected `loot_drops` CSV) committed; pytest asserts match
- [x] Exit criteria: replay produces `loot_drops` matching the committed golden output; `v_drop_rates`/`v_summary` views materialize. Validation against the user's real `.pcapng`/CSV history is ready via `gorgon-tracker replay` / `migrate`.

### Phase 2 — Live packet source
- [x] `sources/tshark_live.py` — long-lived `tshark -T <fields>` stdout stream, line parser
- [x] `find-ports` — Proton-aware `ss -tnp` discovery → BPF (`ports.py`)
- [x] Exit criteria: streaming parse == replay parse results (parity test `test_live_parse_matches_replay_parse`)

### Phase 3 — Live chat tail
- [x] `sources/chat_tail.py` — poll-based tail of the newest CompatData chat log, incremental regex parse. Deviation: polling (configurable `chat.poll_interval_s`) instead of `watchdog` keeps the tool self-contained and rotation-safe without a native dependency.
- [x] Exit criteria: loot/bury events emitted live as lines append (tests cover append-only, rotation, and tail-from-start)

### Phase 4 — OCR sources
- [x] `parsers/ocr.py` — mss grab + Pillow grayscale preprocess + pytesseract
- [x] `sources/ocr_zone.py`, `sources/ocr_targets.py` — change-detection + zone heartbeat (single generic `sources/ocr.py::produce_region`)
- [x] `calibrate.py` — snapshot + live OCR preview for tuning regions; CLI `calibrate --region x,y,w,h [--watch]`
- [x] Exit criteria: OCR capture path and region calibration tooling implemented and unit-tested (headless CI verified via mocks; on-display verification requires a display)

### Phase 5 — Assemble `run`
- [x] `pipeline.py` — source threads → queue → ingest worker → DB writer (single SQLite connection owned by the pipeline thread)
- [x] Session lifecycle: create/continue on start, SIGINT/SIGTERM graceful close, crash-safe flush; `run` opens/reuses a session and closes it on exit
- [x] `status`/`stop` (pidfile-based); `run --daemon` (double-fork) + `packaging/gorgon-tracker.service` systemd unit
- [x] Exit criteria: start/stop freely between sessions (verified end-to-end: foreground + daemon runs, SIGTERM, pidfile lifecycle)

### Phase 6 — CSV compat + web
- [x] `export.py` — backwards-compatible CSV export (`export [--since]`, same header/columns as the legacy loot.csv)
- [x] Aggregation SQL views (`v_drop_rates`, `v_summary`, `v_sessions`) — in `schema.sql`. Note: `v_drop_rates` counts encounters as distinct `encounter_id` per monster so `drops/encounters` is a rate.
- [x] `serve.py` — read-only FastAPI browsing over the same DB (`serve --host --port`; endpoints `/health /sessions /summary /drop-rates /loot`)
- [x] Exit criteria: web browsing of loot data works off the same DB

### Cross-cutting
- [x] README updated for Linux setup (tshark setcap, tesseract install, Proton chat dir, replay/migrate/export/serve usage, systemd)
- [x] CI workflow (`.github/workflows/ci.yml`) running ruff + mypy + pytest on 3.11/3.12/3.14

### Known open items for future agents
- [ ] Validate `replay` against the user's real historical `.pcapng` + chat logs and confirm `loot_drops` matches their prior CSV (no sample data exists in-repo; golden fixtures cover the algorithm).
- [ ] Calibrate OCR regions for the live Proton display via `gorgon-tracker calibrate` (needs a display).
- [ ] Consider a reorder-tolerance buffer in `Correlator` for out-of-order live events (currently correct for in-order ingestion).
- [ ] Optional: `find-ports --write-config` to persist discovered ports back into `gorgon-tracker.toml`.
- [ ] Run `gorgon-tracker sniff-inspect` during a scripted looting session (kill, loot-all, skin, butcher, bury, harvest) and inspect `strings.csv`/per-stream dumps for plaintext loot/status messages. If `added to inventory` (or similar) crosses the wire, extend `parsers/packets.py` with a loot decoder feeding ms-exact packet timing into the correlator; otherwise treat the packet path as closed and rely on chat timing + the audit/override layer.
- [ ] Storage seam: run the public read/ingest surface against PostgreSQL (the SQL that feeds it is portable; `COLLATE NOCASE` / `ROUND(CAST(...AS REAL))` need dialect handling). Local capture stays SQLite-only.
- [ ] Publish history: keep an append-only log of every publication attempt (currently one latest-state row per `loot_drop_id`).

### Correlation audit & hardening (evidence, harvestables, overrides)
- [x] `CorrelateConfig`: `target_fallback_seconds = 3.0`, `search_corroboration_seconds = 2.0`
- [x] Correlator: evidence fields on every `LootDrop` (`linked_via`, `monster_name/lag`, `target_name/lag`, `corroborated_by_search`); legacy closest-wins ranking preserved; target sighting window capped; `Harvesting` activity for target-linked drops without a corroborating same-name corpse search
- [x] Schema v2: `loot_drops` evidence columns + `loot_overrides` table (reversible manual corrections, merged partial updates); migration path from v1 verified
- [x] API: `/loot` exposes evidence + effective (override-merged) values + `linked_via`/`confidence` filters; `PUT/DELETE /api/loot/{id}` override endpoints (web app only; `serve` stays read-only; SSE loot rows carry evidence)
- [x] Web: Loot page badges (monster/corroborated target/target-only/orphan), evidence column, confidence filter, inline edit + revert
- [x] Export: overrides applied; `--with-evidence` appends audit columns (legacy header unchanged by default)
- [x] `sniff-inspect`: live (raw pcap retained) + offline `--pcap` modes; `strings.csv` token inventory; per-TCP-stream per-direction payload dumps; CLI command + tests
- [x] Tests/docs: correlator evidence + harvestable classification, db v2 migration + overrides, serve filters, override API, sniff-inspect; MIGRATION_PLAN §3.3 rationale updated

### Corpse-activity identification (skinning / butchering / extracting)
- [x] `ActivityEvent` (chat status marker `You skin/butcher/extract ...`) + `Correlator.ingest_activity`; drops within `correlate.activity_window_seconds` (default 2.0s) inherit the activity in both the monster-linked and orphan branches
- [x] Corpse-description transitions from the Unity `Player.log`: each `ProcessTalkScreen("Search Corpse of X")` shows the actions already performed (`skinned/butchered/extracted <item> from the corpse.`); a verb newly appearing on a previously-seen corpse flushes that search's pending loot as the activity. A corpse first seen already showing the verb — or searched again with it unchanged — never relabels (the "already skinned" exclusion)
- [x] Whole-second `Player.log` stamps use the wider activity window (0.9s retroactive threshold stays for the packet `can_*` path)
- [x] DB: migration v5 `corpse_searches.extractions_json` records the verb/item pairs that drove each attribution; `DbWriter.activity` persists chat markers as raw events
- [x] Tests: correlator transitions + negatives, chat markers, player-log verb extraction, db extractions roundtrip, replay end-to-end; legacy packet-path behavior covered by the unchanged golden scenario

### Item/zone catalog preseed (official game-data CDN)
- [x] `catalog.py`: bundled `items.json` (slug -> display + value/stack/keywords/icon) and `areas.json` (area id -> friendly/short name + adjacency), user-dir override, `update_catalog_files` + version pinning (CDN keeps only the last few game-data versions)
- [x] Item identification: `itemdb.infer_display` resolves Unity slugs from the catalog (exact slug then `(base, code)`) before the CamelCase heuristic (`ArmorPatchKit3` -> "Good Armor Patch Kit"); correlator unchanged
- [x] DB preseed: migration v4 adds `item_value`/`max_stack`/`keywords_json`/`icon_id`/`data_version` to `items`; `seed_items` upserts the full catalog (canonical names never override learned ones; sighting counts preserved); `seed_from_catalog` runs at CLI connect / pipeline / web build when `items` is empty (re-seeds after `clear_all`)
- [x] Zone identification: `LOADING LEVEL Area<id>` mapped to the official friendly name in the Unity parser (`AreaSerbule2` -> "Serbule Hills"); zone-name corrector gains a short-name alias table from the catalog (`Anagoge` -> `Anagoge Island`)
- [x] CLI `update-catalog` (+ web Import/Export "Update catalog" button, `GET/POST /api/catalog`); `[catalog] data_dir` config; item metadata (value/stack/keywords/version) surfaced in the Dashboard item drill-down
- [x] Tests/docs: catalog load + seed + idempotency + clear-reseed, alias correction, playerlog area mapping, web catalog endpoints; README + sample `gorgon-tracker.toml` updated

### Public deploy + publish (read-only server, local publish flow)
- [x] `public.py`: read-only public app (read API + public SPA + optional bearer-token ingest `POST /api/ingest/loot`); control routes never mounted; unique publish-key/encounter indexes created only on the public DB; synthetic "published" session keeps the schema shared
- [x] `serve` CLI now deploys the public surface (`--config`); `web` stays the local tool (read + control + publish)
- [x] `publish.py` + migration v6 `loot_publications`: effective-row payloads (overrides applied, encounter identity included), batch push, per-row audit; `POST /api/publish` (local-only, requires `[publish]`); re-publish replaces on the natural key
- [x] Frontend: shared `LootEvidence` components; Loot page Publish button + published badge; second Vite profile builds the read-only public UI (`static/public`)
- [x] Config: `[publish]` (local client) and `[serve]` (public ingest gate) keys; sample `gorgon-tracker.toml` + docs updated
- [x] Tests/docs: `tests/test_public.py`, `tests/test_publish.py`, `docs/specs/publish.md`; `docs/api.md`, `docs/architecture.md`, `docs/development.md`, README updated
- [x] Exit criteria: public server serves only read data; local tool publishes checked rows; re-publish replaces; Python + Node gates green