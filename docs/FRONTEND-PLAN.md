# gorgon-tracker — Web Front-End Plan & Development Tracker

Persistent development plan for adding a local browser UI that simplifies **configuring**, **running/stopping**, and **interacting with** the `gorgon-tracker` CLI.

The build-out is complete. The canonical reference docs have moved:

- As-built backend (process model, modules) and frontend structure: `docs/architecture.md`.
- Complete API surface (read, control, SSE, SPA): `docs/api.md`.
- This file keeps the locked decisions and the live development tracker.

Companion doc: [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md) tracks the CLI/core itself; this file tracks the web UI on top of it.

**Status legend:** `[ ]` = not started, `[/]` = in progress, `[x]` = done. Agents must update the tracker section ("Development Tracker") at the bottom of this file as work progresses, keeping one item `[/]` at a time and marking `[x]` only when verified (tests/lint/typecheck pass).

---

## 1. Context

`gorgon-tracker` is a Python/Typer CLI (see `MIGRATION_PLAN.md`) that captures Project Gorgon game events into SQLite (WAL). It already ships a **read-only** FastAPI (`serve.py`) with `/sessions /summary /drop-rates /loot /health`. There is currently **no HTML UI** and **no way to configure, start/stop the daemon, or run offline operations from a browser**.

The goal is a local web UI people actually use instead of the terminal for everyday workflows:

- **Configure** `gorgon-tracker.toml` (paths, capture BPF, chat dir, OCR regions, correlate tuning) without hand-editing TOML.
- **Run** the capture daemon (`run --daemon`) and stop it, with live status.
- **Interact** with the collected data: browse loot, view drop-rate dashboards/charts, run `replay`/`migrate`/`export`, calibrate OCR regions against a screenshot, and manage sessions.

### 1.1 Locked decisions (from project owner; do not revisit without the user)

| Decision | Choice | Rationale |
|---|---|---|
| Form factor | **Local web UI in browser** | Best for tables, charts, image-based OCR calibration. |
| Control scope | **Full control** | Edit config, start/stop daemon, run replay/migrate/export/calibrate, and browse data from the UI. |
| Framework | **Vite + React + TypeScript** | Mature ecosystem, robust tooling. |
| Charting | **Recharts** | Tree-shakeable, React-native, good bar/line/heatmap for drop rates. |
| SPA distribution | **Bundled artifact served by FastAPI** | Vite build → static dir shipped in the pip package; no Node needed at runtime. Dev uses Vite proxy to the API. |
| Config write-back | **tomlkit, preserving comments/formatting** | UI edits only changed keys; the annotated sample config stays human-readable. |
| Replay/migrate input | **File upload** (in addition to server paths) | Upload captures/logs/CSV from the browser into a temp dir and run offline operations on them. |

---

## 2. Key runtime facts that shape web work

These still hold. See `docs/architecture.md` (process model, DB) and `docs/api.md` (endpoints) for the as-built detail.

- SQLite is open in **WAL mode** with a single writer (the daemon). The web process opens read/control connections concurrently.
- The capture daemon runs as a **separate process** (`gorgon-tracker run --daemon`), keyed off the same pidfile. The web server does not host the pipeline; it launches the daemon via `subprocess`.
- OCR calibration and live OCR require a **display + tesseract**; capture requires **tshark with CAP_NET_RAW**. The UI surfaces these as actionable warnings rather than hard failures.

---

## 3. History summary

Backend phases (config write-back, status/config/daemon/offline/calibrate APIs, static serving, packaging) and frontend phases (Status, Dashboard, Loot, Config, Calibrate, Import/Export, Sessions pages, then the tabbed Dashboard analysis revamp) are complete. The tracker below records the items. The endpoint table and SPA serving details live in `docs/api.md`.

---

## Development Tracker

Agents working on this project must update this section. Mark items `[x]` only when verified (tests/lint/typecheck pass). Keep one item `[/]` at a time. Prefix backend items with `[be]` and frontend items with `[fe]`.

### Phase 0 — Backend foundations
- [x] `config_write.py` — tomlkit read/apply/write; active config path resolution; pydantic validation before persist (`[be]`)
- [x] Refactor `serve.py` read endpoints into a shared builder; `serve` still read-only (`[be]`)
- [x] `web` CLI command skeleton (`--host --port --config --db`) reporting URL once API ready (`[be]`)
- [x] Exit criteria: `tests/test_serve.py` unchanged & green; tomlkit round-trip preserves comments (`[be]`)

### Phase 1 — Status + config APIs
- [x] `GET /api/config` (effective JSON + active path), `PUT /api/config` (validated partial update) (`[be]`)
- [x] `GET /api/status` — pid/running, open session, per-source counts, config/db path, setup warnings (`[be]`)
- [x] `POST /api/daemon/start`, `POST /api/daemon/stop` (mock subprocess in tests) (`[be]`)
- [x] Exit criteria: endpoints verified with `TestClient`; daemon start/stop mocked without real fork (`[be]`)

### Phase 2 — Offline + calibration endpoints
- [x] `POST /api/ports/discover` (+ optional `write_config`) (`[be]`)
- [x] `POST /api/replay`, `POST /api/migrate` — multipart upload + server-path inputs (`[be]`)
- [x] `GET /api/export` CSV download (`[be]`)
- [x] `GET /api/calibrate/snapshot`, `GET /api/calibrate/preview`, `POST /api/calibrate/region` (`[be]`)
- [x] `GET /api/files?path=` server-side path browser (`[be]`)
- [x] Exit criteria: uploads land in temp dir and drive replay/migrate identically to paths (`[be]`)

### Phase 3 — Static serving + Vite scaffold
- [x] FastAPI serves `src/gorgon_tracker/static/` with SPA history fallback (`[be]`)
- [x] Vite project: React+TS, dev proxy `/api`→8000, `outDir`→`../src/gorgon_tracker/static` (`[fe]`)
- [x] Packaging: `package-data` includes `static/**`; gitignore built static (`[be]`)
- [x] CI Node job: `npm ci && npm run build && npm run test && tsc` (`[be]`)
- [x] Exit criteria: `npm run build` produces a static dir FastAPI serves; pip package installs + serves the SPA (`[be][fe]`)

### Phase 4 — Status, Dashboard, Loot pages
- [x] `api/client.ts`, `api/types.ts`, `hooks/useStatus` (polling), `useApiData` (`[fe]`)
- [x] `components/`: DataTable, StatusBadge, Page (`[fe]`)
- [x] `Status.tsx` — daemon toggle, live counters, session, warnings (`[fe]`)
- [x] `Dashboard.tsx` — summary table + Recharts (`[fe]`)
- [x] `Loot.tsx` — browsable table + filters (`[fe]`)
- [x] Exit criteria: pages render live/test data; polling updates counters; charts reflect `/drop-rates` (`[fe]`)

### Phase 5 — Config, Calibrate, Import/Export, Sessions pages
- [x] `Config.tsx` — sectioned forms → `GET/PUT /api/config` with dotted-key diff save (`[fe]`)
- [x] `Calibrate.tsx` — RegionPicker snapshot drag-select, live OCR preview, save region (`[fe]`)
- [x] `ImportExport.tsx` — upload + path inputs for replay/migrate; find-ports; export CSV (`[fe]`)
- [x] `Sessions.tsx` — list sessions / per-session counts (`[fe]`)
- [x] `components/`: FormField, FilePicker, RegionPicker; page tests for Config (`[fe]`)
- [x] Exit criteria: end-to-end workflows work in browser against a populated DB (`[fe]`)

### Phase 6 — Polish, docs, CI
- [x] Error/empty/loading states across pages (`[fe]`)
- [x] README: `web` usage, Node dev instructions, runtime note (no Node needed) (`[doc]`)
- [x] Update `MIGRATION_PLAN.md` (cross-ref) + finalize this tracker (`[doc]`)
- [x] Exit criteria: full CI green — Python matrix + Node job; lint/typecheck/tests pass (`[be][fe]`)

### Known open items / follow-ups
- [x] Decide whether the daemon runs via `run --daemon` subprocess (chosen) vs the web process hosting the pipeline in-process.
- [x] Live update transport: polling via `GET /api/status` (chosen); SSE/WebSocket left as a follow-up if sub-second freshness is needed.
- [x] Status page: live **tailed chat log** panel — `GET /api/chat/tail` reads the newest chat log in `chat.log_dir` (same file the daemon tails), returns the last N raw lines with per-line `loot`/`bury` classification, and degrades gracefully (`found: false` + reason) when the dir/path is unresolvable. Frontend polls every 1.5s with a follow/auto-scroll toggle.
- [ ] Optional auth/remote option if `--host 0.0.0.0` is used (reverse proxy or token).
- [ ] Code-split the recharts-heavy Dashboard bundle (Current: single ~150 kB chunk; consider `React.lazy`).

### Phase 7 — Dashboard analysis revamp (analyze / explore / find)
- [x] Read API: `since`/`until` time filters, `last_seen`, `offset` pagination (`[be]`)
- [x] New endpoints: `/api/stats`, `/api/zone/{name}`, comma-list `monsters`/`items` for `/api/drop-rates` matrix queries (`[be]`)
- [x] `GET /api/export/analysis` CSV of the filtered drop-rate table (`[be]`)
- [x] Backend tests for time filters, last-seen, zone/stats, matrix lists, pagination, CSV export (`[be]`)
- [x] Dashboard rebuilt as Overview / Rates / Find / Matrix tabs with filters + active tab synced to the URL (`[fe]`)
- [x] Rate-first charts, KPI stat cards, confidence badges (sample-size-aware), clickable cell drill-downs (`[fe]`)
- [x] Type-ahead search with keyboard nav, drill-down cross-links (source/item/zone/activity), rate matrix heatmap, `DataTable` pagination (`[fe]`)
- [x] Exit criteria: `pytest`, `vitest`, `tsc`, `ruff`, `mypy` green; SPA smoke-tested against a populated DB (`[be][fe]`)