# gorgon-tracker — Migration Plan & Development Tracker

Persistent development plan for evolving the PowerShell loot-collection scripts into a single-entrypoint, cross-platform (Linux-first) background tool that writes directly to SQLite.

Web UI that configures/runs/browses this tool is tracked separately in [`FRONTEND-PLAN.md`](FRONTEND-PLAN.md).

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

## 2. Current state analysis

### 2.1 Inventory of existing scripts (`loot-tracker/`)

All scripts are Windows-only and write/read intermediate files under `loot-tracker/output/` (gitignored).

| Script | Role | Notes |
|---|---|---|
| `ProjectGorgon-StartMonitoring.ps1` | Launcher | `Start-Process` for capture scripts; waits for a key; `taskkill` to stop. Hardcodes `powershell.exe`. |
| `ProjectGorgon-CapturePackets.ps1` | Live capture | Runs `tshark -i <InterfaceId> -w raw_<ts>.pcapng`. `-ListInterfaces` flag prints adapters; interface ID hardcoded (`4`). Manual stop via `Read-Host`. |
| `ProjectGorgon-CaptureZones.ps1` | Live capture | One-liner calling `CaptureScreenText` with region `-X 1680 -Y 0 -Width 180 -Height 50`, interval 5s, file `zones`. |
| `ProjectGorgon-CaptureTargets.ps1` | Live capture | One-liner calling `CaptureScreenText` with region `-X 1021 -Y 691 -Width 213 -Height 114`, interval 0.5s, file `targets`. |
| `ProjectGorgon-CaptureScreenText.ps1` | OCR engine | Screenshot via `System.Drawing.CopyFromScreen`, grayscale color-matrix preprocess, save PNG, OCR via external cmdlet `Convert-PsoImageToText`, sanitize text with `[^a-zA-Z\s]`, write change-detected rows to CSV (`Time` in UTC ms + `Text`). |
| `ProjectGorgon-GetPortFilters.ps1` | Port discovery | `Get-Process WindowsPlayer` → `Get-NetTCPConnection`/`Get-NetUDPEndpoint` owning-process ports → `tcp.port == X` / `udp.port == X` filters. |
| `ProjectGorgon-ParseChat.ps1` | Offline parse | Reads every file in `%USERPROFILE%\AppData\LocalLow\Elder Game\Project Gorgon\ChatLogs`. Regexes (see §3.1) produce Loot events (item + count) and Bury events. |
| `ProjectGorgon-ParsePackets.ps1` | Offline parse | Runs `tshark -r <file> -2 -Y "<filter>" -T json` on each `.pcapng`, converts to JSON, iterates frames, decodes `tcp.payload` (fallback `data.data`) hex→bytes→ASCII, filters payloads containing `Search Corpse of`, extracts monster name + `Skin`/`Butcher`/`Extract Skull` flags, derives session windows from frame times. Display filter proto string: hex of `Search Corpse of `. |
| `ProjectGorgon-CompileLootEvents.ps1` | Correlator (crown jewel) | Full timeline correlation. Core logic must be ported ~1:1 (see §3.3). |
| `ProjectGorgon-CollectLootData.ps1` | Orchestrator/export | Runs ParseChat → ParsePackets → CompileLootEvents, exports `loot.csv`, shows `Out-GridView`. |

### 2.2 Current data flow

```
Capture (per-session, manual):
  tshark → raw_<ts>.pcapng
  OCR zones (5s)  → zones.csv (change-detected)
  OCR targets (0.5s) → targets.csv (change-detected)

Parse (post-session):
  ParseChat    → parsed-chat.txt        (JSON: Loot/Bury events)
  ParsePackets → parsed-packets.txt     (JSON: Source events + sessions)
  ParsePackets also writes parsed-sessions.txt

Correlate + Export:
  CompileLootEvents → loot.csv  → manually copied → Google Sheets ← the "database"
```

### 2.3 Pain points being eliminated

- Multiple separate scripts with manual per-session setup and teardown.
- Windows-only surface (PowerShell, `System.Drawing`, Windows OCR cmdlet `Convert-PsoImageToText`, `taskkill`, hardcoded paths in `AppData\LocalLow`).
- One monolithic post-processing run; no runtime evaluation; no incremental persistence.
- CSV → Google Sheets manual copy = fragile data store with no schema, no history, no queryability.
- No raw data retention for reprocessing (parsed/derived only).

---

## 3. Port specifics (highest-risk ↔ highest-value)

### 3.1 Chat parsing regexes (from `ProjectGorgon-ParseChat.ps1`)

ChatLog file paths (current): `%USERPROFILE%\AppData\LocalLow\Elder Game\Project Gorgon\ChatLogs`

Proton default (configurable): `<steam-library>/steamapps/compatdata/1118200/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs`

- **Loot event:**
  `^(?<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+(?<item>.+?)(?:\s+x(?<count>\d+))?\s+added to inventory\.$`
  → `count` defaults to `1`; timestamp parsed with `yy-MM-dd HH:mm:ss` (InvariantCulture).
- **Bury event:**
  `^(?<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+You bury the corpse\.$`
- **Corpse-activity marker** (new; complementary signal for `ActivityEvent`):
  `^(?<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+You (skin|butcher|extract)\w*\b`
  → mapped to `Skinning`/`Butchering`/`Extracting` and pinned onto loot drops whose
  pickup time is within the correlate `activity_window_seconds`.

### 3.2 Packet parsing (from `ProjectGorgon-ParsePackets.ps1`)

- Display filter: `tcp.payload contains <hex of "Search Corpse of ">` = `"Search Corpse of "` in ASCII (`53:65:61:72:63:68:20:43:6f:72:70:73:65:20:6f:66:20`).
- Hex payload source: `tcp.payload` else `data.data`.
- Hex decode: `payload.split(':')` → bytes → join chars as ASCII string; also a sanitized view keeping only printable ASCII + `\n`/`\r`.
- Ignore frames whose text contains `You do not have permission to loot this corpse.`
- Monster name cleanup sequence (order matters):
  1. `.Replace("Autopsy", "")`
  2. `.Replace("Skin Corpse", "")`
  3. `.Replace("Butcher Corpse", "")`
  4. `.Replace("Extract Skull", "")`
  5. `.Trim()`, then `.Trim('-')`
- Flags: `canSkin` = raw contains `Skin Corpse`, `canButcher` = `Butcher Corpse`, `canExtract` = `Extract Skull`.
- Session window (packet-capture validity) = first → last frame time of each capture file.

### 3.3 Correlator port (from `ProjectGorgon-CompileLootEvents.ps1`) — port ~1:1

The timeline algorithm at `loot-tracker/ProjectGorgon-CompileLootEvents.ps1:107-245` is the core asset. It becomes a **streaming, windowed correlator** holding in-memory state:

- Current encounter: `encounter_uuid`, `current_monster`, `last_packet_time`, last skin/butcher/extract flags.
- `pending_drops` buffer (loot events not yet linked).
- Recent `target_sightings` (time-bounded lookup, replaces the pre-sorted targets array).
- Current zone (updated on each `zone_change`).
- Date parsing compatibility: existing JSON uses `\/Date(ms)\/` format → `epoch + ms → local time`, else `[DateTime]` parse.

**Behavioral rules to preserve exactly:**

- Constants: `BufferSeconds = 10`, `SessionTimeout = 3`, `RetroactiveThreshold = 0.9` (move to config).
- Looting requires targeting the entity being looted (corpse or harvestable), so the OCR
  target window is direct interaction evidence, not combat context:
  - `TargetFallbackSeconds = 3` — how stale a target sighting may be to compete with (or
    substitute for) a monster source; older sightings are coincidence risk.
  - `SearchCorroborationSeconds = 2` — a target-linked drop with a same-name corpse-search
    packet within this window is corpse loot (`activity=Looting`, `corroborated_by_search`);
    a target-linked drop without one is a harvestable (`activity=Harvesting`). Flowers/logs/
    apples have no corpse-search packet, so targets remain their **only** evidence channel.
- `Get-OrphanSource(drop_time, targets, buffer)`: best target sighting with `0 <= lag <= TargetFallbackSeconds`, smallest lag wins; default `"Ground/Unknown"`.
- Timeline merged from `Source` (SortPriority 2), `Loot` (1), `Bury` (2), sorted by `Time, SortPriority` (loot before source at equal time).
- **Loot event** → push to `pending_drops`.
- **Bury event** → end of encounter: for each pending drop, link to monster if `monster_lag <= BufferSeconds` AND `monster_lag < orphan.lag`, else orphan fallback. `Status = "Linked"|"Orphaned"`; orphan with a known target is still `"Linked"` (source = target name); `"Ground/Unknown"` → `"Orphaned"`. `Activity = "Looting"`. New GUID for each encounter; reset monster + flags.
- **Source event** → `isSameEncounter = (monster == current && time_since_last <= SessionTimeout)`. Compute `justSkinned/justButchered/justExtracted = (isSameEncounter && prevFlag && !newFlag)`; assign activity `Skinning|Butchering|Extracting|Looting` when `monster_lag <= RetroactiveThreshold`. Flush pending drops (same link/orphan logic). If new encounter, roll GUID + set monster.
- **End of stream (flush):** remaining pending drops link to `current_monster` / encounter, `Status="Linked"`, `LagTime=0`.
- **Zone assignment:** walk zone-change timestamps ≤ drop time; start `"Unknown"`.
- Output columns: `Time, Source, ID, Activity, Item, Amount, Status, LagTime, Zone`.

**Attribution audit trail (`linked_via` + evidence, migration v2):**

Every `loot_drops` row records *why* it was attributed so bad links are visible and fixable:

- `linked_via` = `monster` | `target` | `orphan`; plus `monster_name`, `monster_lag_ms`,
  `target_name`, `target_lag_ms`, `corroborated_by_search`.
- The legacy closest-wins ranking is **unchanged**; the target window is capped at
  `TargetFallbackSeconds` and `status` values are untouched, so historical CSV/golden
  outputs are byte-identical.
- `loot_overrides` table stores reversible manual corrections (source/status/activity/note)
  applied at read time (API `PUT/DELETE /api/loot/{id}`, web Loot page edit controls,
  CSV export `--with-evidence`). Residual noise (1s chat timestamps, OCR sampling latency)
  is mitigated through this audit + override layer rather than guessed at correlation time.

### 3.4 OCR port

- Swap `Convert-PsoImageToText` (Windows) for **`pytesseract`** (Tesseract). Keep the grayscale color-matrix preprocess (port with Pillow: `L` mode / luminance weights `0.3/0.59/0.11`).
- Sanitize OCR text with `[^a-zA-Z\s]` (matches current behavior), `.trim()`.
- Change-detection: write new row only when text changes. For zones, additionally store a low-frequency "heartbeat" (e.g., every 30s) when unchanged, so a static zone is still persisted at interval.
- Region values migrate to config, not code. Coordinates will need recalibration under the Linux display/Proton (see `calibrate` command, §5).
- Target OCR at 0.5s is the heaviest CPU consumer — interval must stay configurable.

### 3.5 Live packet source

- Replace `tshark -r <file> -T json` offline runs with a long-lived child process: `tshark -i <iface> -Y <filter> -T <per-line fields>` streamed + parsed line-by-line (minimal cost, no intermediate files).
- Replaces `GetPortFilters`: `find-ports` command inspects `ss -tnp`/`/proc/net` for connections owned by the game process (Proton-aware; process name `WindowsPlayer`/`ProjectGorgon`), producing `tcp.port == X || ...` BPF filters.
- Linux privilege note: tshark requires `CAP_NET_RAW` or membership in the capture/wireshark group — document `setcap` install step.

---

## 4. Target architecture

```
src/gorgon_tracker/
    cli.py            # typer entrypoint, dispatch table
    config.py         # TOML load/validate (pydantic)
    db.py             # sqlite bootstrap, WAL, migrations, writer helper
    schema.sql        # DDL (initial migration)
    pipeline.py       # thread/queue plumbing: sources -> single ingest worker -> DB
    correlator.py     # streaming port of CompileLootEvents
    parsers/
        chat.py       # chat regexes + tail state
        packets.py    # hex/ASCII decode, Search Corpse Of extraction
        ocr.py        # mss grab + Pillow preprocess + pytesseract
    sources/
        tshark_live.py
        chat_tail.py  # watchdog-based tail of newest chat log
        ocr_zone.py
        ocr_target.py
    replay.py         # offline .pcapng ingest through same parser+correlator
    migrate.py        # import old CSVs / JSON intermediates
    export.py         # backwards-compatible CSV export
    calibrate.py      # interactive region picker for OCR
    serve.py          # Phase 6: readonly FastAPI over same DB
tests/               # pytest; golden tests (see §8)
```

```
Sources (threads)                 Pipeline (single worker)            Persistence
tshark stdout (live BPF)  ──┐                                         raw_events
chat tail (Proton dir)  ────┤    parse ─► correlator ─► db_tx         ──────────
OCR zones (mss+tesseract) ──┼──►  (windowed, in-memory state) ────►   sources / loot /
OCR targets (mss+tesseract) ─┘                                         burials / sightings /
                                                                      zone_changes /
    replay <*.pcapng> (offline, same pipeline, synthetic sessions)    encounters /
    migrate csv (old outputs)                                          loot_drops (derived)
```

Single `queue.Queue` fed by source threads; one ingest worker runs the correlator; one DB writer connection. SQLite in **WAL mode**, `synchronous=NORMAL`, periodic flush/checkpoint — crash-safe, single-writer, concurrent readers (future web UI).

### 4.1 Data model (SQLite)

- `sessions(id, uuid, started_at, ended_at_nullable, platform, config_snapshot_json)` — each `run` creates/continues a session; SIGINT/SIGTERM closes it.
- `raw_events(id, session_id FK, source, captured_at, payload_json, dedup_hash)` — raw retention for reprocessability.
- `sources(id, session_id, raw_event_id, captured_at, monster, can_skin, can_butcher, can_extract)` — kills/body-state.
- `loot(id, session_id, raw_event_id, captured_at, item, amount)` — raw loot facts.
- `burials(id, session_id, raw_event_id, captured_at)`.
- `target_sightings(id, session_id, raw_event_id, captured_at, target_name)` — OCR target reads.
- `zone_changes(id, session_id, raw_event_id, captured_at, zone_name)`.
- `encounters(id, session_id, encounter_uuid, monster, started_at, ended_at_nullable)`.
- `loot_drops(id, session_id, encounter_id, captured_at, source, item, amount, activity, zone, status, lag_ms)` — correlated output, written live.
- Views: `v_drop_rates`, `v_summary`, `v_sessions` — feeding the future web UI.
- `schema_migrations` + `PRAGMA user_version` for versioned DDL.

---

## 5. CLI commands

| Command | Purpose |
|---|---|
| `gorgon-tracker run` | Foreground daemon; prints live status (current zone/target, event counts); graceful stop on SIGINT/SIGTERM. `--daemon` for background (systemd unit + pidfile). |
| `gorgon-tracker status` | Session table, current state, per-source event counts. |
| `gorgon-tracker stop` | Signal the running daemon. |
| `gorgon-tracker find-ports` | Auto-detect game ephemeral ports → BPF filter (Proton-aware). |
| `gorgon-tracker calibrate` | Interactive: screenshot a region repeatedly, show OCR output, until region/PSM tuned. |
| `gorgon-tracker replay <*.pcapng>` | Offline ingest of historical captures through the same parser+correlator. |
| `gorgon-tracker migrate csv <file...>` | Import old `loot.csv`/`zones.csv`/`targets.csv`/parsed JSON as historical sessions. |
| `gorgon-tracker export csv --since ...` | Backwards-compatible CSV export (kept for Google Sheets comfort). |
| `gorgon-tracker serve` | Phase 6: read-only FastAPI web UI over the same DB. |

### 5.1 Default config (`gorgon-tracker.toml`) sketch

```toml
db = { path = "data/gorgon.db" }

capture = {
  tshark_path = "tshark",
  interface = "auto",           # or explicit; default NIC
  ports = [],                    # auto-fill via `find-ports`
  bpf = "",                      # derived if ports empty
}

chat = {
  log_dir = "<steam-library>/steamapps/compatdata/1118200/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs",
  tail = true,
}

ocr = {
  tesseract_path = "tesseract",
  lang = "eng",
  zones  = { region = [1680, 0, 180, 50],  interval_s = 5.0,  heartbeat_s = 30.0 },
  targets = { region = [1021, 691, 213, 114], interval_s = 0.5, heartbeat_s = null },
}

correlate = {
  buffer_seconds = 10,
  session_timeout = 3,          # seconds
  retroactive_threshold = 0.9,  # seconds
}
```

---

## 6. Execution phases

| Phase | Scope | Exit criteria |
|---|---|---|
| 0 | Scaffold: package, `pyproject.toml` (uv/venv), config loader, CLI skeleton, sqlite bootstrap + WAL + migrations. | `run` opens DB; `status` reports a session. |
| 1 | **Offline core:** port chat/packet parsers + correlator; `replay`, `migrate`; pytest golden tests vs. old CSVs. | Historical `.pcapng` → `loot_drops` matches prior CSV output. |
| 2 | Live tshark stream source + `find-ports`. | Streaming parse == replay parse results. |
| 3 | Live chat tail (CompatData dir). | Loot/bury events appear live. |
| 4 | OCR sources (`mss`+Pillow+`pytesseract`) + `calibrate`. | Zone/target captured on the Proton display; regions calibrated. |
| 5 | Assemble `run`: sources → queue → correlator → sqlite; session lifecycle; crash-safe flush; systemd unit. | Start/stop freely between sessions; data persists without manual steps. |
| 6 | `export csv` + FastAPI `serve` (drop-rate views). | Web browsing of loot data works off the same DB. |

Phase 1 is intentionally first after scaffolding: it de-risks the correlator port against real historical data **before** any live capture work.

---

## 7. Dependencies & environment

**Python deps:** `typer` (or `click`) + `rich`, `Pillow`, `mss`, `pytesseract`, `watchdog`, `pydantic`, `tomli` (stdlib on 3.11+); dev `pytest`, `mypy`, `ruff`.

**External tools:** `tshark` (Wireshark), `tesseract`.

**Linux install notes:**
- Capture user needs `CAP_NET_RAW` (`setcap cap_net_raw,cap_net_admin=eip $(which tshark)`) or membership in the Wireshark capture group.
- OCR: `apt install tesseract-ocr` (plus `-eng` data).
- Screen grab on X11 via `mss`; on Wayland, document backend limits (may need `grim` or XWayland).

---

## 8. Testing strategy

- **Golden tests:** run the existing PowerShell pipeline on historical sample data, capture the CSV output, commit as fixtures; assert the Python port produces identical `loot_drops` rows.
- **Replay harness:** `replay` doubles as an offline test — feed a sample `.pcapng`, assert DB contents.
- **Unit tests:** pure functions (hex decode, monster-name cleanup, regexes, `Get-OrphanSource`, correlator transitions incl. same-encounter, retroactive skinning, bury-flush, orphan fallback).
- **Live smoke test:** short `run` while a capture fixture is replayed on a loop interface (if available); otherwise client-side synthetic stream into the source protocol.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|---|---|
| OCR accuracy on Linux display (scaling, theme, font) | `calibrate` command; configurable regions/intervals; PSM/lang tuning; keep existing grayscale preprocess. |
| Ephemeral game ports change per launch | `find-ports` at session start (Proton-aware). |
| Correlator port drift from historical behavior | Golden tests (Phase 1) before live work; port rules verbatim. |
| Proton chat log path varies | Config default + `chat.log_dir` override; path is derived from the Steam library mount point. |
| Live pipeline ordering/jitter vs. batched sort | Windowed correlator with monotonic reordering guard (small time-bucket reorder buffer); document deviation vs. original if any. |
| Heavy CPU from 0.5s OCR | Interval configurable; OCR only on change after region small; consider downscale/threshold optimization. |

---

## 10. Future (out of current scope, keep in mind for design)

- Web frontend (FastAPI/read-only or full UI) browsing drop rates per monster/item/zone.
  **Done**: the full UI ships as the `web` command; see [`FRONTEND-PLAN.md`](FRONTEND-PLAN.md).
- Export to Google Sheets (e.g., `gspread`) as an optional push rather than primary store.
- Stats/aggregation dashboards, backup/restore of the SQLite DB, multi-machine capture merging.

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