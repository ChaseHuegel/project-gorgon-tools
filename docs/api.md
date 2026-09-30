# Spec: Web API

This spec describes the complete HTTP API served by `gorgon-tracker serve` and `gorgon-tracker web`. It is the canonical reference for the API surface. All paths are under `/api`. All timestamps are UTC epoch milliseconds (int) unless noted.

Readiness notes:

- `serve` (public) mounts the read router, the read-only public SPA, and (when configured) the write-only publish ingest. It exposes no control endpoints.
- `web` (local tool) mounts the read router plus control endpoints, the publish action, and the full SPA.
- Every request opens a fresh SQLite connection and runs migrations (`src/gorgon_tracker/serve.py:229-254`).
- All endpoints are unauthenticated and bind `127.0.0.1` by default. The destructive endpoints (`POST /api/data/clear`, `POST /api/loot/rows/delete`) are unauthenticated POSTs. Do not bind `web` beyond localhost. The public ingest endpoint (`POST /api/ingest/loot`) is the only externally writable route. It requires a bearer token.

## Read endpoints

Builder: `build_read_router` at `src/gorgon_tracker/serve.py:257-681`.

| Method | Path | Purpose | Params | Response |
|---|---|---|---|---|
| GET | `/api/health` | Liveness | — | `{status, db}` |
| GET | `/api/sessions` | Sessions, newest first | — | array of `{id, uuid, started_at, ended_at, platform}` |
| GET | `/api/distinct` | Distinct axis values for filters | — | `{sources[], zones[], items[], activities[]}` (NOCASE sorted) |
| GET | `/api/summary` | Aggregate per zone/monster/activity/item | `source` (LIKE), `item` (LIKE), `zone`, `activity`, `since`, `until` | array of `{zone, monster, activity, item, total_quantity, drop_count, last_seen}`; only `status='Linked'` |
| GET | `/api/drop-rates` | Drop-rate matrix per (monster, activity, item) | `monster`, `item`, `zone`, `activity`, `status` (default `Linked`), `sort`, `order`, `limit` (1..5000), `offset`, `since`, `until`, `monsters`, `items` (comma lists) | array of `{monster, activity, item, drops, quantity, encounters, drop_rate, last_seen}` |
| GET | `/api/loot` | Latest loot rows, overrides merged | `limit_rows` (default 200, 1..5000), `linked_via`, `confidence` (`high`/`uncertain`, mutually exclusive with `linked_via`) | array of effective loot rows |
| GET | `/api/search` | Fuzzy autocomplete across three axes | `q`, `limit` (default 20, cap 100), `since`, `until` | `{sources[], items[], activities[]}`; empty `q` → empty arrays |
| GET | `/api/source/{name}` | Monster drill-down | `since` | `{source, zones[], items[]}` |
| GET | `/api/item/{name}` | Item drill-down | `since` | `{item, sources[], zones[], metadata}` |
| GET | `/api/activity/{name}` | Activity drill-down | `since` | `{activity, sources[], items[], zones[]}` |
| GET | `/api/zone/{name}` | Zone drill-down | `since` | `{zone, sources[], items[], activities[]}` |
| GET | `/api/analysis/sources` | Top sources chart | `source`, `item`, `zone`, `activity`, `status` (default `Linked`), `limit` (default 50, cap 500), `since`, `until` | array of `{monster, drops, quantity, encounters, drop_rate, last_seen}` |
| GET | `/api/analysis/zones` | Top zones chart | `source`, `item`, `activity`, `status` (default none), `limit`, `since`, `until` | array of `{zone, drops, sources, last_seen}` |
| GET | `/api/analysis/items` | Top items chart | `source`, `item`, `zone`, `activity`, `status` (default `Linked`), `limit`, `since`, `until` | array of `{item, drops, sources, last_seen}` |
| GET | `/api/stats` | Global stat cards | `source`, `item`, `zone`, `activity`, `since`, `until` | `{drops, encounters, quantity, sources, items, zones, linked, orphaned, newest_at}` |

`encounters` is per-activity everywhere it appears. For `drop-rates` and
`analysis/sources` it is the count of distinct encounters where the filtered
activity happened (any activity when no filter is set). For `stats` it is the
same count summed over sources. Rates divide drops by that count, so a skin
drop divides by skinned encounters, not by every encounter. See
`docs/specs/correlation.md` → Rates semantics.

`GET /` (serve only, `serve.py:660-679`): `{service, endpoints[]}`.

### Effective loot row shape

`GET /api/loot` and `PUT /api/loot/{id}` return the override-merged row (`serve.py:48-64`):

```json
{id, captured_at, source, activity, item, amount, zone, status, lag_ms,
 linked_via, monster_name, monster_lag_ms, target_name, target_lag_ms,
 corroborated_by_search, note, overridden, published, published_at}
```

`note`, `overridden`, `published`, and `published_at` exist only here. `published`
is true when a `loot_publications` audit row exists for the drop. The SSE loot
stream sends the raw row. It omits override and publication fields. It includes
extra source fields (see below).

### Item metadata

`GET /api/item/{name}` includes `metadata` when an item matches the catalog (`serve.py:156-185`): `{display_name, item_value, max_stack, icon_id, keywords, data_version, variants}`. Field values may be null; a corrupt `keywords_json` decodes to `[]`.

## Control endpoints

Builder: `build_control_router` at `src/gorgon_tracker/web.py:53-467`.

| Method | Path | Purpose | Body / query | Response |
|---|---|---|---|---|
| GET | `/api/status` | UI status | — | `{db_path, config_path, config_db_path, sessions_total, open_session_id, open_session_counts, daemon, warnings, publish}` where `publish` is `{configured, url}` (token never exposed) and `warnings` may include a note that a session has loot without an activity ledger (run `backfill-encounters`) |
| GET | `/api/chat/tail` | Tail the newest chat log | `limit` (default 500, cap 5000) | `{found, log_dir, file, mtime_ms, start_offset, reason, lines:[{text, kind}]}` where `kind` is `loot`, `bury`, or null |
| GET | `/api/config` | Effective config + path | — | `{path, config}` |
| PUT | `/api/config` | Partial config write | `{updates: {"section.key": value}}` (non-empty); `422` on pydantic error | `{path, config}` |
| POST | `/api/daemon/start` | Spawn capture daemon | — | daemon status |
| POST | `/api/daemon/stop` | SIGTERM the daemon | — | daemon status |
| POST | `/api/replay` | Offline replay (upload and/or server paths) | multipart: `paths[]`, `chat_dir`, `files[]` | `{inputs, session_id, parsed_files, loot_kept, zones, targets, burials, activities, encounters, encounter_activities, drops}` |
| POST | `/api/migrate` | Import legacy CSV/JSON | multipart: `paths[]`, `kind`, `files[]` | `{imported:[{file, session_id, kind, imported}]}` |
| POST | `/api/backfill` | Rebuild encounter rows and the activity ledger from raw events (or from drops for legacy sessions) | — | `{sessions:[{session_id, encounters_created, encounters_matched, derived, activities}]}` |
| GET | `/api/export` | Loot CSV download | `since` (ISO string) | `text/csv` attachment |
| GET | `/api/export/analysis` | Drop-rate CSV download | `source`, `item`, `zone`, `activity`, `status` (default `Linked`), `since`, `until` (ISO), `sort`, `order` | `text/csv` attachment; header `Monster,Activity,Item,Drops,Quantity,Encounters,DropRate,LastSeen` |
| PUT | `/api/loot/{id}` | Set or merge a manual override | `{source?, status?, activity?, note?}`; `status` must be `Linked` or `Orphaned` | effective loot row; `404` unknown id |
| DELETE | `/api/loot/{id}` | Remove override | — | `{ok: true}` |
| POST | `/api/loot/rows/delete` | Hard-delete loot rows | `{ids: [positive ints]}` | `{deleted}` |
| POST | `/api/data/clear` | Wipe all captured data | — | `{ok: true, cleared: {table: count}}` |
| POST | `/api/publish` | Publish selected loot rows to the configured public server | `{ids: [positive ints]}`. Returns `403` unless `[publish]` url and token are set | `{published, created, replaced, failed, results:[{loot_drop_id, status, remote_action, message}]}` |
| GET | `/api/names` | Name-list snapshot info | — | `{enabled, data_dir, zones_count, monsters_count, zones_path, monsters_path, zones_source, monsters_source, zones_mtime_ms, monsters_mtime_ms}` |
| POST | `/api/names/update` | Fetch name lists from the wiki | — | `{zones, monsters, path}`; `502` on fetch failure |
| GET | `/api/catalog` | Catalog snapshot info | — | `{data_dir, item_source, area_source, item_count, area_count, version}` |
| POST | `/api/catalog/update` | Fetch catalog, reload, re-seed `items` | — | `{version, items, areas, path, seeded}`; `502` on fetch failure |
| GET | `/api/calibrate/screens` | List displays | — | `{monitors:[{left, top, width, height}]}`; `502` when capture unavailable |
| GET | `/api/calibrate/snapshot` | PNG of a region | `x`, `y`, `w`, `h`, `color` (default false) | `image/png` |
| GET | `/api/calibrate/preview` | OCR a region | `x`, `y`, `w`, `h` | `{text, raw}` |
| POST | `/api/calibrate/region` | Save an OCR region | `{kind: "zones"|"targets", region: [x, y, w, h]}` | `{path, config}` |
| GET | `/api/files` | Minimal server file browser | `path` (default `$HOME`), `_limit` (default 500, cap 2000) | `{path, entries:[{name, path, is_dir}]}`; `404` when not a dir |

Config write-back (`PUT /api/config`) uses tomlkit partial updates via dotted keys. Only changed keys are written; comments and formatting survive. See `src/gorgon_tracker/config_write.py`.

## SSE streams

Generator module: `src/gorgon_tracker/stream.py`; routes at `serve.py:636-658`.

| Path | Event name | Poll | Payload per frame (`data:`) |
|---|---|---|---|
| `/api/stream/loot` | `loot` | 0.5 s | Raw `loot_drops` row: `{id, captured_at, source, activity, item, amount, zone, status, lag_ms, linked_via, monster_name, monster_lag_ms, target_name, target_lag_ms, corroborated_by_search, instance_id, entity_id, item_code_id, item_display, missed, killer_json}` |
| `/api/stream/events` | `event` | 0.5 s | `{id, session_id, source, captured_at, payload}` where `payload` is the decoded `payload_json` (see raw event payload shapes below) |
| `/api/stream/status` | `status` | 1.5 s | `{open_session_id, open_session_counts}`; the `id:` cursor is synthetic (increments per poll), not a row id |

Frame format (`stream.py:38-53`): each frame carries `retry: 2500`, `id: <cursor>`, `event: <name>`, and one-line compact JSON `data:`. A heartbeat frame `retry: 2500\n: ping\n\n` follows each poll. The `id:` doubles as the resume cursor for reconnects. Response headers: `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no`.

### Raw event payload shapes (`raw_events.payload_json`)

Written by `src/gorgon_tracker/ingest.py`:

| `source` | Payload |
|---|---|
| `chat` | loot: `{item, amount, instance_id, entity_id, item_code_id, missed}`; bury: `{}`; activity: `{activity}` |
| `unity` | loot payload (same shape as chat loot, `source_class` `unity`) |
| `unity_interaction` | `{entity_id}` |
| `unity_corpse` | `{monster, entity_id, killer, participants}` where participants is `name -> {health, armor, aggro}` |
| `unity_item_code` | `{instance_id, code}` |
| `ocr_target` | `{name}` |
| `ocr_zone` | `{zone}` |

Raw event dedup: loot events carry a `dedup_hash = sha1(source_class|item|amount|whole_second)` so the chat and Unity reports of one pickup share a hash (`ingest.py:25-34`).

## Publish ingest (write-only, public server)

Mounted by `gorgon-tracker serve` only when `[serve] ingest_enabled=true` and `[serve] ingest_token` is set. This is the single write route on the public server. Everything else is read-only. See the payload contract in `docs/specs/publish.md`.

| Method | Path | Purpose | Auth | Response |
|---|---|---|---|---|
| POST | `/api/ingest/loot` | Receive verified loot rows | `Authorization: Bearer <ingest_token>` | `{received, created, replaced, actions:[...]}` |

The natural key is `(captured_at, source, item, amount)`. The server replaces a public row with an exact key match. It inserts a new row otherwise. Rows attach to a stable synthetic "published" session. An optional `encounter_uuid` reconstructs encounters, and an optional `encounter_activities` list (each `{activity, performed_at}`) rebuilds their activity ledger, so public drop rates keep working. The server returns `401` without the token. It returns `422` on invalid fields. See `src/gorgon_tracker/public.py`.

## Pagination and filter conventions

- `limit`/`offset` exist only on `drop-rates` (`limit` clamped 1..5000, `offset` ≥ 0). Other lists are limit-only; the client pages.
- Shared filter family: `source`, `item`, `zone`, `activity`, `since`, `until`. `since`/`until` are inclusive `captured_at` ms bounds.
- Fuzzy `LIKE %x%` only on `/api/summary` (`source`/`item`) and `/api/search` (`q`). Everything else is exact.
- Sort is whitelisted (`_SORT_COLUMNS`, `serve.py:65-74`): `monster, item, drops, quantity, encounters, rate, zone, activity`.
- `status` defaults to `Linked` on `drop-rates`, `analysis/sources`, `analysis/items`, and `export/analysis`; drill-down item lists pass no `status` so all statuses show.

## SPA serving

Two SPAs come bundled. Both use the same fallback helper (`src/gorgon_tracker/spa.py`).

- `web` mounts `static/app/` (full local UI: Status, Dashboard, Loot, Sessions, Config, Calibrate, Import/Export).
- `serve` mounts `static/public/` (read-only public UI: Dashboard, Loot, Sessions, About).

`/assets` is a static mount. Any other path serves an existing static file (MIME-guessed) or the preloaded `index.html` for client routing. An unknown `/api/*` path returns `404`, not the SPA shell. The Vite build output lives in `src/gorgon_tracker/static/` (gitignored).

## Known type drift (frontend vs backend)

Recorded so agents do not re-discover it (`web/src/api/types.ts`):

- The TS `Config` type omits the `playerlog`, `names`, `catalog`, `publish`, `serve` sections and `correlate.activity_window_seconds` from the wire shape.
- The SSE `loot` payload has extra fields (`instance_id`, `entity_id`, `item_code_id`, `item_display`, `missed`, `killer_json`) and lacks `note`/`overridden`/`published`/`published_at`; pages tolerate the difference.
- `SourceAgg` omits `last_seen`. `ReplayResult` is a partial view of an additive response (it omits `encounters` and `encounter_activities`).
- `open_session_counts` keys are table names (`raw_events`, `sources`, `loot`, `burials`, `target_sightings`, `zone_changes`, `encounters`, `loot_drops`, `corpse_searches`, `encounter_activities`).

## Source of truth and tests

- Read router: `src/gorgon_tracker/serve.py`
- Control router + SPA: `src/gorgon_tracker/web.py`
- Public app + ingest: `src/gorgon_tracker/public.py`
- SSE: `src/gorgon_tracker/stream.py`
- Config write-back: `src/gorgon_tracker/config_write.py`
- Tests: `tests/test_serve.py`, `tests/test_web.py`, `tests/test_web_ops.py`, `tests/test_public.py`, `tests/test_publish.py`

Update this doc when any route, query param, response field, or SSE payload changes.