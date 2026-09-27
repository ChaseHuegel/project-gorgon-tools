# Spec: publish and ingest

This spec is the source of truth for moving verified loot rows from the local
capture tool to a public server. Both sides use the same wire contract. The
local client (`src/gorgon_tracker/publish.py`) and the server-side ingest
validator (`src/gorgon_tracker/public.py`) build on the field list below.

## Flow

1. The local tool captures loot into its own SQLite database.
2. The owner fixes rows in the local Loot page (overrides). The owner checks the rows to publish and clicks **Publish selected**.
3. The local tool builds the *effective* (override-merged) payload for each checked row. It POSTs batches (max 500) to `<publish.url>/api/ingest/loot`. It sends `Authorization: Bearer <token>`.
4. The public server validates, inserts, and audits each row in its own database. Re-publishing a corrected row replaces the public copy.
5. The local tool records each outcome in `loot_publications` (one row per `loot_drop_id`, latest state).

## Payload

Each row is a JSON object of the publish fields with the local row's *effective*
values (manual overrides applied). The local `id`, `note`, and `overridden`
flags are private to the local database. The client never sends them.

| Field | Type | Notes |
|---|---|---|
| `captured_at` | int | Required. UTC epoch ms. |
| `source` | string | Required, non-empty. Effective monster/source name. |
| `item` | string | Required, non-empty. Effective display name. |
| `amount` | int | Required, >= 1. |
| `activity` | string | Default `Looting`. |
| `zone` | string | Default `Unknown`. |
| `status` | string | `Linked` or `Orphaned`. Default `Linked`. |
| `lag_ms` | int | Default 0. |
| `linked_via` | string | Non-empty. Default `monster`. |
| `monster_name`, `monster_lag_ms` | string, int\|null | Attribution evidence. |
| `target_name`, `target_lag_ms` | string, int\|null | Attribution evidence. |
| `corroborated_by_search` | bool | Default false. |
| `instance_id`, `entity_id`, `item_code_id` | int\|null | Unity provenance. |
| `item_display` | string\|null | Unity provenance. |
| `missed` | bool | Default false. |
| `killer_json` | string\|null | Corpse-search killer table. |
| `encounter_uuid` | string\|null | Encounter identity (see below). |

Unknown fields are rejected (`422`). Missing optional fields take their
defaults. The server rejects missing required fields.

## Encounter identity

The public dashboard computes drop rates from distinct encounters. Each
published row may carry `encounter_uuid`. The local tool looks the value up from
the `encounters` table. The server upserts a matching `encounters` row (unique
on `encounter_uuid`) and links the published drop to it. The server does not
link rows without an encounter.

## Ingest endpoint

`POST /api/ingest/loot`

- Body: `{"rows": [<payload>, ...]}` with 1..500 rows.
- Auth: `Authorization: Bearer <token>`. The token must equal `[serve] ingest_token`.
- Natural-key upsert: the new payload **replaces** a public row with the same `(captured_at, source, item, amount)`. Otherwise the server inserts a new row. The unique indexes `idx_loot_drops_publish_key` and `idx_encounters_publish_uuid` exist only on the public database. They never exist on the local capture DB.
- Response: `{received, created, replaced, actions: ["created"|"replaced", ...]}`
  where `actions` is parallel to the submitted `rows`.

## Publish endpoint (local-only)

`POST /api/publish` (mounted only by `gorgon-tracker web`)

- Body: `{"ids": [<loot_drop_id>, ...]}` (positive integers).
- Config: returns `403` unless `[publish] enabled`, `url`, and `token` are set.
- Response: `{published, created, replaced, failed, results:[{loot_drop_id,
  status, remote_action, message}]}`.

## Persisted audit

Local migration v6 adds:

```sql
loot_publications (
    id, loot_drop_id UNIQUE, published_at,
    payload_json, remote_batch, status, message, created_at
)
```

`payload_json` is the exact effective payload sent. `status` is `ok` or
`failed`. `message` carries the remote outcome or the error.

## Source of truth

- Local client: `src/gorgon_tracker/publish.py` (payload build + push + audit).
- Server ingest: `src/gorgon_tracker/public.py` (`build_ingest_router`,
  `_validate_row`, `_ingest_row`).
- Local endpoint: `src/gorgon_tracker/web.py` (`POST /api/publish`).
- Config keys: `[publish]` and `[serve]` (see `docs/development.md`).
- Tests: `tests/test_public.py`, `tests/test_publish.py`.

The local tool publishes rows onto a read-only public frontend. The public
server never exposes control endpoints. See `docs/architecture.md` for the
surface split.