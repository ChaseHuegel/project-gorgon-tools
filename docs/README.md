# Documentation index

This index maps subjects to their docs. It is the recommended first read for agents new to the repo. Human-facing usage lives in `README.md`; agent navigation lives here and in `AGENTS.md`.

## Subject index

| Subject | Doc |
|---|---|
| Where to start (navigation, rules) | [`AGENTS.md`](../AGENTS.md) |
| As-built architecture, module map, CLI table, DB | [`docs/architecture.md`](architecture.md) |
| Development workflows, config, tests, code style | [`docs/development.md`](development.md) |
| Web API (all endpoints, SSE, payloads) | [`docs/api.md`](api.md) |
| Chat log line format | [`docs/specs/chat-log.md`](specs/chat-log.md) |
| Unity `Player.log` format | [`docs/specs/player-log.md`](specs/player-log.md) |
| Packet format (corpse-search frames) | [`docs/specs/packets.md`](specs/packets.md) |
| Loot correlation logic | [`docs/specs/correlation.md`](specs/correlation.md) |
| Game CDN + wiki data formats | [`docs/specs/cdn-catalog.md`](specs/cdn-catalog.md) |
| CSV and import formats | [`docs/specs/csv-formats.md`](specs/csv-formats.md) |
| OCR capture pipeline | [`docs/specs/ocr.md`](specs/ocr.md) |
| Publish + public ingest contract | [`docs/specs/publish.md`](specs/publish.md) |
| Historical plan + development tracker (CLI/core) | [`docs/MIGRATION_PLAN.md`](MIGRATION_PLAN.md) |
| Historical plan + development tracker (web UI) | [`docs/FRONTEND-PLAN.md`](FRONTEND-PLAN.md) |

## How to read the specs

Each spec (`docs/specs/*.md`) is standalone. It records:

- The exact format, with examples.
- The source of truth: the module and the file:line range implementing it.
- The tests that pin the behavior.

Use the source-of-truth pointers to jump straight to the code. Update the pointers when the code moves.

## Docs-pass protocol

The "source of truth" is the code; docs record behavior so agents do not re-discover it. Docs therefore change with the code. Every change set must end with a docs pass:

1. **Run the pass after every change**, before finalizing. When the change is arcane (message formats, correlation rules, DB schema, config keys, API routes), the pass is mandatory, not a suggestion.
2. **Find the doc.** Map the changed behavior to a doc via the subject index. Specs live in `docs/specs/`; the API table lives in `docs/api.md`; architecture facts live in `docs/architecture.md`; toolchain and rules live in `docs/development.md`.
3. **Update or create.** Edit the matching doc to reflect the new behavior. If the behavior has no home, create a new doc. Put data formats in `docs/specs/`. Keep one subject per doc so a fetch stays focused.
4. **Fix the pointers.** Refresh the "source of truth" file:line references so the next reader lands on the new code.
5. **Do not document what is obvious.** If a module docstring already states the fact, delete the doc copy and keep the pointer. Docs exist to make the non-obvious explicit.
6. **Keep it minimal.** One name per thing. Active voice. Short sentences (STE-flavored).

### Examples of changes that trigger a docs pass

- A chat, Player.log, packet, CDN, or CSV format changes → update the matching spec.
- A correlation constant or transition rule changes → `docs/specs/correlation.md`.
- A route, query param, or response field changes → `docs/api.md`.
- A migration or table changes → `docs/architecture.md` (DB section).
- A config key changes → `docs/development.md` (schema table) + the sample `gorgon-tracker.toml` + `README.md`.
- A CLI command is added or renamed → `docs/architecture.md` (CLI table).
- A team member adds a brand-new reverse-engineered format → create a new file in `docs/specs/` and add it to this index + `AGENTS.md`.