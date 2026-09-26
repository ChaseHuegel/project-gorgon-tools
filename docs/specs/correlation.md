# Spec: Loot correlation logic

This spec describes how the tracker links loot pickups to monster sources and activities. It is the streaming port of the legacy PowerShell `ProjectGorgon-CompileLootEvents.ps1` correlator. This is the canonical reference for correlation behavior.

## Tuning constants

All constants are config-backed (`[correlate]`). Defaults at `src/gorgon_tracker/config.py:68-84`, consumed at `correlator.py:204-218`.

| Key | Default | Meaning |
|---|---|---|
| `buffer_seconds` | `10.0` | Max age of a monster source (or target sighting) that can explain a loot drop. |
| `session_timeout` | `3.0` | Max seconds between body-state packets that still count as the same encounter. |
| `retroactive_threshold` | `0.9` | Max seconds a drop may precede a packet `can_*` transition to inherit Skinning/Butchering/Extracting. |
| `activity_window_seconds` | `2.0` | Max distance from a corpse-description transition or chat activity marker a drop inherits its activity. Wider than `retroactive_threshold` because the Unity log stamps whole seconds. |
| `target_fallback_seconds` | `3.0` | Max age of a target sighting that may attribute loot. |
| `search_corroboration_seconds` | `2.0` | A target-linked drop within this many seconds of a same-name corpse search is corpse loot, not a harvestable. |

## Event DTOs

Defined at `src/gorgon_tracker/correlator.py:20-114`:

| DTO | Producer | Purpose |
|---|---|---|
| `SourceEvent` | packets | A corpse-search frame: monster + `can_skin/can_butcher/can_extract`. |
| `LootEvent` | chat, Player.log | A pickup. `instance_id`/`entity_id` come from the Unity log; `source_class` is `chat` or `unity`; `missed=True` means inventory was full. |
| `BuryEvent` | chat, Player.log | Corpse buried; ends the encounter. |
| `ActivityEvent` | chat | A `You skin/butcher/extract ...` status marker. |
| `TargetSighting` | OCR | A target-name OCR read. |
| `ZoneChange` | OCR, Player.log | Current zone. |
| `InteractionStart` | Player.log | A corpse-looting window opens. |
| `CorpseSearch` | Player.log | Names the corpse's monster, killer, participants, and extraction verbs. |
| `ItemCode` | Player.log | Maps an instance id to an item code. |
| `LootDrop` | correlator output | The correlated result row (see Evidence below). |

## Ingestion rules

All rules implemented in `src/gorgon_tracker/correlator.py:247-426`.

### Loot

`ingest_loot` appends to a pending buffer. If the event has an `instance_id` in the known `item_codes` map, the correlator attaches the code id.

### Bury

`ingest_bury` flushes pending drops against the current monster, then starts a new encounter and clears monster, flags, activity hint, and corpse state.

### Source (packet frame)

`ingest_source` decides whether the frame is the same encounter: same monster and within `session_timeout` seconds. A state transition (`just_skinned` = same encounter, previous `can_skin` true, now false) relabels the flush if drops fall within the threshold. Otherwise a monster change rolls a new `encounter_uuid`.

### Interaction and corpse search

- `ingest_interaction` opens a loot window; if the entity id maps to a known monster, it restores that monster context.
- `ingest_corpse_search` records the monster by entity id. The corpse-description extractions (`skinned/butchered/extracted <item> from the corpse`) drive activity: a verb that newly appears on a previously-seen corpse flushes pending loot as that activity. A corpse first seen already showing the verb, or re-searched unchanged, never relabels (`correlator.py:329-368`).

### Chat activity marker

`ingest_activity` stores an activity hint that applies to drops within `activity_window_seconds`, before or after the marker (`correlator.py:319-327`). It also flushes immediately, so the `x added to inventory.` line before or after it is labeled.

## Flush and attribution

`_flush` (`correlator.py:657-717`) runs on a source/bury/activity/corpse-search event. For each pending drop, after chat/unity reconciliation:

1. Monster-linked branch: `monster_lag <= buffer_seconds` and `monster_lag < orphan_lag`. Activity is `Looting`, upgraded to `Skinning`/`Butchering`/`Extracting` on a `just_*` transition within the window, or to the chat activity hint. Status `Linked`.
2. Orphan branch: best target sighting within `target_fallback_seconds` (smallest lag wins). A same-name corpse search within `search_corroboration_seconds` makes it `Looting`; otherwise it is `Harvesting` (flowers/logs/apples have no corpse-search packet). No target → `Ground/Unknown` with status `Orphaned`.

`flush_expired` (`correlator.py:379-398`) emits orphaned drops for pending loot older than `buffer_seconds` so live streams do not hold them forever. `finalize` (`correlator.py:400-426`) flushes the remainder at end of stream with `lag_ms=0`.

## Chat / Unity reconciliation

Chat and Unity facts for the same physical pickup share a whole-second timestamp. `_reconcile` (`correlator.py:536-655`) buckets events by whole second and pairs them in three passes:

1. Exact token match on the item name (tokens = lowercase alphanumerics).
2. One remaining item on each side → forced pair.
3. Fuzzy best match via rapidfuzz (max of ratio / partial / token_sort), threshold `85.0`.

Paired facts join the chat display name with the Unity instance/entity identity, so the same pickup never double-counts.

## Evidence audit trail

Every `LootDrop` carries attribution evidence (`correlator.py:90-114`):

| Field | Meaning |
|---|---|
| `linked_via` | `monster`, `target`, or `orphan`. |
| `monster_name`, `monster_lag_ms` | The monster source that claimed the drop. |
| `target_name`, `target_lag_ms` | The target sighting that claimed the drop. |
| `corroborated_by_search` | A same-name corpse-search packet corroborated a target link. |
| `instance_id`, `entity_id`, `item_code_id`, `item_display` | Unity provenance. |
| `missed` | Inventory-full; not collected. |
| `killer_json` | Killer + participant damage table for the corpse's encounter. |

## Timeline merge (offline replay)

`replay.py:183-233` merges events from all sources into `(time_ms, priority)` tuples, then feeds one event at a time through the same correlator:

| Priority | Events |
|---|---|
| 0 | `ZoneChange`, `TargetSighting` (state) |
| 1 | `LootEvent` (loot before state changes at equal time) |
| 2 | `SourceEvent`, `BuryEvent`, `ActivityEvent`, `InteractionStart`, `CorpseSearch`, `ItemCode` |

## Source of truth and tests

- Correlator: `src/gorgon_tracker/correlator.py`
- Config: `[correlate]` in `src/gorgon_tracker/config.py:68-84`
- Golden scenario: `tests/scenario.py`; expected output `tests/fixtures/phase1/expected_loot.csv`
- Tests: `tests/test_correlator.py`, `tests/test_replay.py`

Update this doc when any correlation constant, transition rule, reconcile pass, or evidence field changes.