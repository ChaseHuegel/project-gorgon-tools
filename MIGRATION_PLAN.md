# gorgon-tracker — Migration Plan & Development Tracker

Persistent development plan for evolving the PowerShell loot-collection scripts into a single-entrypoint, cross-platform (Linux-first) background tool that writes directly to SQLite.

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
- `Get-OrphanSource(drop_time, targets, buffer)`: best target sighting with `0 <= lag <= buffer`, smallest lag wins; default `"Ground/Unknown"`.
- Timeline merged from `Source` (SortPriority 2), `Loot` (1), `Bury` (2), sorted by `Time, SortPriority` (loot before source at equal time).
- **Loot event** → push to `pending_drops`.
- **Bury event** → end of encounter: for each pending drop, link to monster if `monster_lag <= BufferSeconds` AND `monster_lag < orphan.lag`, else orphan fallback. `Status = "Linked"|"Orphaned"`; orphan with a known target is still `"Linked"` (source = target name); `"Ground/Unknown"` → `"Orphaned"`. `Activity = "Looting"`. New GUID for each encounter; reset monster + flags.
- **Source event** → `isSameEncounter = (monster == current && time_since_last <= SessionTimeout)`. Compute `justSkinned/justButchered/justExtracted = (isSameEncounter && prevFlag && !newFlag)`; assign activity `Skinning|Butchering|Extracting|Looting` when `monster_lag <= RetroactiveThreshold`. Flush pending drops (same link/orphan logic). If new encounter, roll GUID + set monster.
- **End of stream (flush):** remaining pending drops link to `current_monster` / encounter, `Status="Linked"`, `LagTime=0`.
- **Zone assignment:** walk zone-change timestamps ≤ drop time; start `"Unknown"`.
- Output columns: `Time, Source, ID, Activity, Item, Amount, Status, LagTime, Zone`.

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
- [ ] `parsers/packets.py` — hex decode, monster-name cleanup, flags, session windows (§3.2)
- [ ] `parsers/chat.py` — loot/bury regexes (§3.1)
- [ ] `correlator.py` — streaming port of CompileLootEvents rules (§3.3)
- [ ] `replay.py` — offline `.pcapng` ingest through same parser+correlator
- [ ] `migrate.py` — import old CSVs / parsed JSON as historical sessions
- [ ] Golden-test fixtures (PowerShell CSV output) committed; pytest asserts match
- [ ] Exit criteria: historical `.pcapng` → `loot_drops` matches prior CSV

### Phase 2 — Live packet source
- [ ] `sources/tshark_live.py` — long-lived `tshark -T <fields>` stdout stream, line parser
- [ ] `find-ports` — Proton-aware `ss -tnp` discovery → BPF
- [ ] Exit criteria: streaming parse == replay parse results

### Phase 3 — Live chat tail
- [ ] `sources/chat_tail.py` — watchdog tail of newest CompatData chat log, incremental regex parse
- [ ] Exit criteria: loot/bury events appear live during a session

### Phase 4 — OCR sources
- [ ] `parsers/ocr.py` — mss grab + Pillow grayscale preprocess + pytesseract
- [ ] `sources/ocr_zone.py`, `sources/ocr_targets.py` — change-detection + zone heartbeat
- [ ] `calibrate.py` — interactive region picker
- [ ] Exit criteria: zone/target captured on Proton display; regions calibrated

### Phase 5 — Assemble `run`
- [ ] `pipeline.py` — source threads → queue → ingest worker → DB writer
- [ ] Session lifecycle: create/continue, SIGINT/SIGTERM graceful close, crash-safe flush/checkpoint
- [ ] `status`/`stop`; `--daemon` + systemd unit
- [ ] Exit criteria: start/stop freely between sessions with zero manual steps

### Phase 6 — CSV compat + web
- [ ] `export.py` — backwards-compatible CSV export
- [ ] Aggregation SQL views (`v_drop_rates`, `v_summary`, `v_sessions`)
- [ ] `serve.py` — read-only FastAPI browsing over same DB
- [ ] Exit criteria: web browsing of loot data works off the same DB

### Cross-cutting
- [ ] README updated for Linux setup (tshark setcap, tesseract install, Proton chat dir)
- [ ] Set up CI (optional): pytest + mypy + ruff on push