# AGENTS.md

This file tells agents how to navigate and develop in this repository. Start here, then follow the links. Human-facing usage lives in `README.md`. The docs index lives in `docs/README.md`.

## Project at a glance

gorgon-tracker is a Python + SQLite loot and drop-rate tracker for the game Project Gorgon. It captures game data at runtime (packets, chat logs, the Unity `Player.log`, screen OCR), correlates loot with the monster that dropped it, and serves the result through a read API and a React SPA.

Two subsystems:

1. `src/gorgon_tracker/` — Python package: CLI, capture pipeline, correlator, FastAPI.
2. `web/` — Vite + React + TypeScript SPA, built into the pip package.

## Repository index

| Path | What it is |
|---|---|
| `src/gorgon_tracker/` | Python package (see `docs/architecture.md` for the module map). |
| `web/` | Frontend SPA; build output goes to `src/gorgon_tracker/static/`. |
| `tests/` | Pytest suite; golden scenario in `tests/scenario.py`, fixture CSV in `tests/fixtures/phase1/`. |
| `tools/` | Thin wrappers for refreshing bundled data (`update_catalog.py`, `update_names.py`). |
| `loot-tracker/` | Legacy Windows PowerShell scripts. Reference only; do not modify. |
| `packaging/` | systemd unit for running the capture daemon. |
| `data/` | Gitignored runtime data (local DB, test output). |
| `docs/` | Agent documentation, specs, and the historical plan/tracker docs. |
| `gorgon-tracker.toml` | Sample config; all defaults with comments. |
| `pyproject.toml` | Package metadata, deps, ruff/mypy/pytest config. |

Bundled reference data (do not confuse with runtime `data/`) ships inside the package at `src/gorgon_tracker/data/`: `items.json`, `areas.json` (catalog), `zones.txt`, `monsters.txt` (names), `version.txt`.

## First stops

| Goal | Go to |
|---|---|
| Understand the system | `docs/architecture.md` |
| Find a reverse-engineered format | `docs/specs/` (chat, player-log, packets, correlation, cdn-catalog, csv-formats, ocr) |
| Add or change an API endpoint | `docs/api.md` |
| Config keys, tests, code style | `docs/development.md` |
| User-facing setup/usage | `README.md` |

Read `docs/README.md` once before deep work; it maps every subject to one focused doc so you fetch only what you need.

## Quality gates

Run all before finishing a change:

```sh
ruff check src tests && mypy src/gorgon_tracker && pytest
```

```sh
cd web && npm run typecheck && npm test && npm run build
```

CI runs the same on every push/PR (`.github/workflows/ci.yml`).

## Code style and rules

- The rules in `docs/development.md` apply. Highlights:
  - Ruff `E,F,I,UP,B,SIM`, line-length 120, mypy strict, Python 3.11+.
  - Event DTOs are frozen dataclasses in `src/gorgon_tracker/correlator.py`; parsers and sources follow the patterns in `docs/architecture.md`.
  - Any new tunable is a config key, never a hardcoded constant.
  - Timestamps are UTC epoch milliseconds everywhere.
  - Prose in user-visible strings and docs: STE (active voice, one name per thing, short sentences).
- Do not add comments to code unless the behavior is genuinely non-obvious (matching module docstring style).

## Commit rules

- One logical change per commit.
- Subject: imperative, capitalized, single line, no prefix. Example: `Add item and zone catalogs from the game data CDN`.
- Simple commits on `main`; no feature branches unless the user asks.
- Update the plan tracker docs when the change matches a tracked item:
  - CLI/core work → the tracker section in `docs/MIGRATION_PLAN.md`.
  - Web UI work → the tracker section in `docs/FRONTEND-PLAN.md`.
  - Mark `[x]` only when verified (tests/lint/typecheck pass); keep one item `[/]` at a time.

## Docs pass (required)

Documentation is part of every change. After your change, before finalizing:

1. If a format, correlation rule, config key, DB table, API route, or response shape changed, update the matching doc.
2. If no doc covers the behavior, create one. Data formats go in `docs/specs/`; one subject per doc.
3. Refresh the "source of truth" file:line pointers in the doc.
4. Link instead of duplicating: if a module docstring states it, point to the module.

Full protocol: `docs/README.md`.

## Working notes for fresh prompts

- The capture daemon is the only SQLite writer; read endpoints and SSE open short-lived connections. Never add a second writer during capture.
- The legacy PowerShell keys on packet plaintext plus chat regexes; the current port adds the Unity `Player.log` as the authoritative loot/corpse source. Reconcile logic: `docs/specs/correlation.md`.
- The live packet path has a known separator quirk (`FIELD_SEPARATOR = "/t"` vs tab split in `src/gorgon_tracker/sources/tshark_live.py`). See `docs/specs/packets.md`.
- Offline replay/migrate feed the same parsers and correlator as live capture; parity between the two is an invariant (golden test).