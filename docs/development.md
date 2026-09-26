# Development

This doc describes how to develop, test, and commit to gorgon-tracker. It is the canonical development reference. Setup and usage for end users live in `README.md`.

## Python

Requirements: Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,serve]"
```

Quality gates (also run by CI):

```sh
ruff check src tests
mypy src/gorgon_tracker
pytest
```

Config: ruff targets `py311`, line-length `120`, rules `E, F, I, UP, B, SIM` (`pyproject.toml:69-75`). Mypy runs strict on the package (`pyproject.toml:60-67`).

## Frontend (Node)

The `web/` SPA is optional to develop; the built bundle ships in the pip package. Install Node 20/22:

```sh
cd web
npm install
npm run dev         # Vite dev server; proxies /api to 127.0.0.1:8000 (or BACKEND=)
npm run typecheck   # tsc --noEmit
npm test            # vitest
npm run build       # bundles into ../src/gorgon_tracker/static, served by FastAPI
```

## Testing conventions

- Pytest config: `testpaths = ["tests"]`, quiet mode (`pyproject.toml:56-58`). There is no `conftest.py`; tests use `tmp_path` and `monkeypatch`.
- Golden scenario: `tests/scenario.py` builds the deterministic Phase-1 fixture (frames, chat lines, zone/target CSVs) with a fixed timezone-independent base. `tests/fixtures/phase1/expected_loot.csv` is the expected correlated output. `tests/test_replay.py` asserts the replay pipeline reproduces it exactly.
- Headless limits: OCR and screen capture are mocked in CI; on-display verification needs a display. Do not add tests that fork a real capture daemon.
- Run the full suite before finishing a change (`pytest` at the repo root).

## Configuration schema

Canonical source: `src/gorgon_tracker/config.py` (pydantic models). The sample file `gorgon-tracker.toml` and `README.md` document all keys. Every section and default:

| Section | Key | Default | Meaning |
|---|---|---|---|
| `[db]` | `path` | `data/gorgon.db` | SQLite database location |
| `[capture]` | `enabled` | `true` | Packet capture master switch |
| `[capture]` | `tshark_path` | `tshark` | tshark binary |
| `[capture]` | `interface` | `auto` | tshark interface, or auto-discovery |
| `[capture]` | `ports` | `[]` | Ports to sniff (set by `find-ports`) |
| `[capture]` | `bpf` | `""` | Explicit filter; wins over `ports` |
| `[chat]` | `log_dir` | `""` | ChatLogs dir (auto-detected) |
| `[chat]` | `tail` | `true` | Tail chat log |
| `[chat]` | `poll_interval_s` | `1.0` | Chat poll interval |
| `[chat]` | `tail_from_start` | `false` | Parse whole log at startup |
| `[playerlog]` | `path` | `""` | `Player.log` path (auto-detected) |
| `[playerlog]` | `tail` | `true` | Tail `Player.log` |
| `[playerlog]` | `poll_interval_s` | `1.0` | Player.log poll interval |
| `[playerlog]` | `tail_from_start` | `false` | Parse whole file at startup |
| `[playerlog]` | `backfill_prev` | `false` | Parse `Player-prev.log` once at startup |
| `[ocr]` | `enabled` | `true` | OCR master switch |
| `[ocr]` | `tesseract_path` | `tesseract` | tesseract binary |
| `[ocr]` | `lang` | `eng` | tesseract language |
| `[ocr.zones]` | `region` | `[1680, 0, 180, 50]` | Screen region `[x, y, w, h]` |
| `[ocr.zones]` | `interval_s` | `5.0` | Zone OCR interval |
| `[ocr.zones]` | `heartbeat_s` | `30.0` | Re-persist unchanged zone (null disables) |
| `[ocr.targets]` | `region` | `[1021, 691, 213, 114]` | Screen region |
| `[ocr.targets]` | `interval_s` | `0.5` | Target OCR interval |
| `[ocr.targets]` | `heartbeat_s` | null | Heartbeat |
| `[correlate]` | `buffer_seconds` | `10.0` | Loot correlation window |
| `[correlate]` | `session_timeout` | `3.0` | Encounter timeout |
| `[correlate]` | `retroactive_threshold` | `0.9` | Packet activity retro window |
| `[correlate]` | `activity_window_seconds` | `2.0` | Corpse-description/chat activity window |
| `[correlate]` | `target_fallback_seconds` | `3.0` | Max target sighting age |
| `[correlate]` | `search_corroboration_seconds` | `2.0` | Corpse-search corroboration window |
| `[names]` | `enabled` | `true` | Name correction master switch |
| `[names]` | `data_dir` | `""` | Name list dir (defaults to user data dir) |
| `[names.zones]` / `[names.monsters]` | `ratio` | `90.0` | Fuzzy threshold (percent) |
| `[names.zones]` / `[names.monsters]` | `partial_ratio` | `85.0` | Partial threshold (percent) |
| `[catalog]` | `data_dir` | `""` | Pin catalog snapshots dir |

Config file discovery: explicit path or `$GORGON_TRACKER_CONFIG`, then `gorgon-tracker.toml` in the working dir, then `~/.config/gorgon-tracker/config.toml` (`config.py:135`, `:265-285`). `db.path` is absolutized on load; empty `chat.log_dir`/`playerlog.path` auto-fill from Steam/Proton discovery (`config.py:251-262`).

Environment overrides for OCR headless/tests: `GORGON_TRACKER_SCREEN_METHOD` (`auto`|`mss`|`portal`) and `GORGON_TRACKER_SCREEN_TTL` (default `1.0`) — see `docs/specs/ocr.md`.

## Code style

- Follow the conventions in `docs/architecture.md`. Type hints everywhere (mypy strict). One module = one concern.
- Event DTOs are frozen dataclasses in `correlator.py`; parsers are pure functions or stateful classes; sources are `Callable[[Event], None]` producers.
- Add a config key for any new tunable; never hardcode a correlation constant.
- User-visible strings and docs: STE (Simplified Technical English) — active voice, one name per thing, short sentences. No marketing adjectives.

## Commit rules

- One logical change per commit.
- Subject line: imperative, capitalized, single line, no `feat:`/`fix:` prefix. Example: `Add item and zone catalogs from the game data CDN`.
- The repo uses simple squashed commits on `main`; do not open feature branches unless asked.
- Before finalizing, run the docs pass (below) and the quality gates (Python + Node), then commit only if asked.

## Docs pass (required)

Documentation is part of every change. Full protocol in `docs/README.md`. Minimum duty:

1. If a data format, correlation rule, config key, DB table, API route, or response shape changed, update the matching doc in `docs/` (specs live in `docs/specs/`).
2. If no doc covers the behavior, add one; single subject per doc.
3. Keep the "source of truth" file:line pointers current so the next agent finds the new code fast.
4. Never duplicate what a module docstring already states; link instead.