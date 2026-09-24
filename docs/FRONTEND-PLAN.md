# gorgon-tracker — Web Front-End Plan & Development Tracker

Persistent development plan for adding a local browser UI that simplifies **configuring**, **running/stopping**, and **interacting with** the `gorgon-tracker` CLI.

**Status legend:** `[ ]` = not started, `[/]` = in progress, `[x]` = done. Agents must update the tracker section ("Development Tracker") at the bottom of this file as work progresses, keeping one item `[/]` at a time and marking `[x]` only when verified (tests/lint/typecheck pass).

Companion doc: [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md) tracks the CLI/core itself; this file tracks the web UI on top of it.

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

## 2. Current state analysis

Relevant existing modules (all in `src/gorgon_tracker/`):

| Module | Role today | What the UI adds on top |
|---|---|---|
| `serve.py` | Read-only FastAPI: `/health /sessions /summary /drop-rates /loot` | Kept as-is (compat); read endpoints extracted into a shared builder both `serve` and `web` mount. |
| `config.py` | pydantic `TrackerConfig` load/validate; candidate path discovery | Write-back via tomlkit; expose active config path. |
| `daemon.py` | pidfile + double-fork daemonize + stop | Spawn `run --daemon` via subprocess from the web process; read pid/status. |
| `pipeline.py` | Source threads → queue → correlator → sqlite | Runs only in the daemon process; the web process just reads WAL. |
| `db.py` | connect/migrate/session helpers; `status_overview` | Reused for status API. |
| `replay.py`, `migrate.py`, `export.py` | Offline ingest/export | Reused via control endpoints; inputs from uploads or server paths. |
| `ports.py` | `find-ports` → BPF | Expose as API (`--write-config` optional). |
| `calibrate.py`, `parsers/ocr.py` | Snapshot + OCR preview | Expose snapshot + preview + region-save endpoints. |

Key runtime facts that shape the design:

- SQLite is open in **WAL mode** with a single writer (the daemon). The web process can open read/control connections concurrently; a fast `status` endpoint can poll live counters. (See §4.4 for polling vs push.)
- The capture daemon runs as a **separate process** (`gorgon-tracker run --daemon`). The web server does **not** host the pipeline; it launches the daemon via `subprocess` keyed off the same pidfile. This keeps one writer and reuses existing lifecycle logic.
- OCR calibration and live OCR require a **display + tesseract**; capture requires **tshark with CAP_NET_RAW**. The UI must surface these as actionable warnings rather than hard failures.

---

## 3. Target architecture

```
browser (React SPA)  ──HTTPS/JSON──►  gorgon-tracker web  (FastAPI, 127.0.0.1)
                                        │  mounts read endpoints (shared with `serve`)
                                        │  adds control endpoints (/api/...)
                                        │  serves built SPA static when present
                                        │
                                        ├──► sqlite (WAL)            read-only browsing/status
                                        ├──► subprocess run --daemon  start/stop capture
                                        ├──► ports / replay / migrate / export / calibrate
                                        └──► gorgon-tracker.toml      tomlkit write-back
```

### 3.1 Backend additions (`src/gorgon_tracker/`)

- **`config_write.py`** — resolve active config path; tomlkit read / apply nested updates / write; pydantic-validate before persist.
- **`control.py`** — daemon status/start/stop (via `daemon.py` + subprocess); wrappers for `find-ports`, `replay`, `migrate`, `export`, upload handling.
- **`api.py`** — FastAPI router with control endpoints (below). Read endpoints refactored from `serve.py` into a reusable builder.
- **`serve.py`** — refactor: read-only app builder shared with `web`; add static serving + SPA fallback.
- **`web` CLI command** — launches the full UI app (`--host --port --config --db`).

### 3.2 API surface

Read (shared, existing behavior):
`GET /health`, `GET /sessions`, `GET /summary`, `GET /drop-rates`, `GET /loot`

Control:
- `GET /api/status` — daemon pid/running, open session, per-source counts, db path, config path, setup warnings.
- `GET /api/config` — effective config JSON + active file path.
- `PUT /api/config` — validated partial update → tomlkit persist → returns new effective config.
- `POST /api/daemon/start`, `POST /api/daemon/stop`.
- `POST /api/ports/discover` (optional `write_config=true`).
- `POST /api/replay`, `POST /api/migrate` — accept uploaded files (multipart) **and** server-side path lists; return summary tables.
- `GET /api/export` — steaming CSV download.
- `GET /api/calibrate/snapshot?region=`, `GET /api/calibrate/preview?region=`, `POST /api/calibrate/region`.
- `GET /api/files?path=` — minimal server-side path browser for non-uploaded inputs (falls back to upload when path unsupported).

Static:
- Serve `src/gorgon_tracker/static/` build with SPA history fallback to `index.html` when present; otherwise return a hint that the UI isn't built (dev mode).

---

## 4. Frontend (`web/` — Vite + React + TS)

```
web/
  package.json, tsconfig.json, vite.config.ts, index.html
  vite.config.ts        # dev: proxy /api + read endpoints + /health -> http://127.0.0.1:8000
                        # build: outDir -> ../src/gorgon_tracker/static
  src/
    main.tsx, App.tsx                     # react-router sidebar layout
    api/client.ts, api/types.ts           # typed fetch wrapper + backend JSON types
    hooks/ useConfig, useDaemon, useStatus (polling),
           useUpload, useApiData           # + useData (debounced fetch w/ filters)
    components/ DataTable, StatusBadge, FormField, RegionPicker, DropRateChart, FilePicker
    pages/
      Status.tsx        # daemon start/stop, live counters, session, setup warnings
      Dashboard.tsx     # v_summary table + Recharts (drops/encounters/quantity by monster/item/zone)
      Loot.tsx          # loot_drops table, filters (monster/activity/status/zone), pagination
      Config.tsx        # sectioned forms (db/capture/chat/ocr/correlate) -> GET/PUT /api/config
      Calibrate.tsx     # screenshot canvas, drag region, live OCR preview, save region
      ImportExport.tsx  # file upload + path inputs for replay/migrate; find-ports; export CSV; sessions
```

Charts (Recharts): drop-rate bar charts per monster, stacked quantity by item/zone, activity split; driven by `/drop-rates` and `/summary`.

---

## 5. Dependencies & environment

**Backend (Python):**
- Add `tomlkit` (config write-back); `python-multipart` (file upload).
- Reuse existing `pydantic`, `fastapi`, `uvicorn`, `Pillow`, `mss`, `pytesseract`, `pytest`, `httpx`.

**Frontend (Node — dev only):**
- `react`, `react-dom`, `react-router-dom`, `recharts`
- Dev: `typescript`, `vite`, `@vitejs/plugin-react`, `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom`

**Runtime deployment:** the built SPA ships inside the pip package (`src/gorgon_tracker/static/**` listed in `package-data`). End users do **not** need Node.

---

## 6. Execution phases

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | Backend foundations: `config_write.py` (tomlkit), control-layer stubs, `web` command skeleton, shared read-API refactor. | Existing `serve` still passes `tests/test_serve.py`; config round-trips through tomlkit preserving comments. |
| 1 | Status + config APIs: `GET/PUT /api/config`, `GET /api/status`, daemon start/stop endpoints. | Endpoints verified with FastAPI `TestClient`; daemon start/stop tested with a mocked subprocess (no real fork in CI). |
| 2 | Offline + calibration endpoints: ports discover, replay/migrate (upload + server paths), export CSV, calibrate snapshot/preview/region, `/api/files`. | All endpoints return expected payloads; uploads land in temp dir and drive replay/migrate identically to paths. |
| 3 | Static serving + Vite scaffold: SPA shell, build `outDir` into package, packaging (`package-data`), CI Node job. | `npm ci && npm run build` produces a static dir that FastAPI serves; pip package installs and serves the SPA with history fallback. |
| 4 | Status + Dashboard + Loot pages (Recharts, filters, polling). | Pages render live/test data; polling status updates counters; charts reflect `/drop-rates`. |
| 5 | Config page (sectioned forms), Calibrate page (drag-region + preview), Import/Export + Sessions pages. | Full workflows work end-to-end in browser against a populated DB. |
| 6 | Polish: error/empty states, loading UX, README + `MIGRATION_PLAN`/`FRONTEND-PLAN` updates, full CI green. | Docs updated; lint/typecheck/tests pass for Python + Node. |

---

## 7. Testing strategy

- **Backend (pytest):** tomlkit round-trip (comments preserved), config PUT validation/rejection, status/config/daemon/ports/replay/migrate/export/calibrate endpoints via `TestClient`; mock `ports`, `ocr`, and daemon subprocess (assert subprocess called with expected args; do not genuinely double-fork in CI). Upload tests use `client.post(url, files=...)`.
- **Frontend (Vitest + RTL):** component tests for `StatusToggle`, `DropRateChart`, `RegionPicker`, `ConfigForm` (loads/saves via mocked client), `DataTable` filtering; `tsc` typecheck in CI.
- **CI:** keep the existing Python matrix; add a Node job (Node 20/22) running `npm ci`, `npm run build`, `npm run test`, `tsc`. Ensure the Python package still builds with the SPA included.
- **Manual smoke:** populated DB via `replay`/`migrate`; run `web`, confirm Status/Dashboard/Config/Calibrate/ImportExport flows.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Exposing process/config control increases local attack surface | Bind `127.0.0.1` by default; document that `--host 0.0.0.0` requires a reverse proxy/auth; control endpoints validated & pydantic-checked. |
| Daemon subprocess management from web is fragile (env, cwd, PATH) | Reuse existing `daemon.py` + pidfile; spawn via the `gorgon-tracker` entrypoint; surface stdout/stderr log path in status. |
| Uploading many/large captures | Enforce size limits and upload to a temp dir under the DB dir; validate mime/filename; keep server-path fallback. |
| Two writers (web + daemon) | Daemon is the only writer; web only reads WAL. Calibration/export/replay operate on select files, not concurrent writes. |
| tomlkit drift breaks readability of hand-edited config | Only write keys the user changed; validate before persist; keep ordering/comments via tomlkit document objects. |
| Node toolchain burden on contributors | Node required only for `web/` dev/build; runtime artifact is pip-shipped. CI provides a node job + `web/.env.example`/README instructions. |
| Chart bloat / heavy bundles | Recharts is tree-shakeable; code-split routes; limit dashboard payloads via existing `LIMIT` + filters. |

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