# Spec: Loot correlation logic

This spec describes how the tracker links loot pickups to monster sources and activities. It is the streaming port of the legacy PowerShell `ProjectGorgon-CompileLootEvents.ps1` correlator. This is the canonical reference for correlation behavior.

## Tuning constants

All constants are config-backed (`[correlate]`). Defaults at `src/gorgon_tracker/config.py:68-84`, consumed at `correlator.py:239-254`.

| Key | Default | Meaning |
|---|---|---|
| `buffer_seconds` | `10.0` | Max age of a monster source (or target sighting) that can explain a loot drop. |
| `session_timeout` | `3.0` | Max seconds between body-state packets that still count as the same encounter. |
| `retroactive_threshold` | `0.9` | Max seconds a drop may precede a packet `can_*` transition to inherit Skinning/Butchering/Extracting. |
| `activity_window_seconds` | `2.0` | Max distance from a corpse-description transition or chat activity marker a drop inherits its activity. Wider than `retroactive_threshold` because the Unity log stamps whole seconds. |
| `target_fallback_seconds` | `3.0` | Max age of a target sighting that may attribute loot. |
| `search_corroboration_seconds` | `2.0` | A target-linked drop within this many seconds of a same-name corpse search is corpse loot, not a harvestable. |

## Event DTOs

Defined at `src/gorgon_tracker/correlator.py:20-135`:

| DTO | Producer | Purpose |
|---|---|---|
| `SourceEvent` | packets | A corpse-search frame: monster + `can_skin/can_butcher/can_extract`. |
| `LootEvent` | chat, Player.log | A pickup. `instance_id`/`entity_id` come from the Unity log. `source_class` is `chat` or `unity`. `missed=True` means inventory was full. |
| `BuryEvent` | chat, Player.log | Corpse buried. It ends the encounter. |
| `ActivityEvent` | chat | A `You skin/butcher/extract ...` status marker. |
| `TargetSighting` | OCR | A target-name OCR read. |
| `ZoneChange` | OCR, Player.log | Current zone. |
| `InteractionStart` | Player.log | A corpse-looting window opens. |
| `CorpseSearch` | Player.log | Names the corpse's monster, killer, participants, and extraction verbs. |
| `ItemCode` | Player.log | Maps an instance id to an item code. |
| `EncounterBegin` | correlator output | A corpse encounter starts with a known monster, zone, and time. |
| `EncounterActivity` | correlator output | An action performed on a corpse during an encounter. |
| `EncounterEnd` | correlator output | An encounter ends with a known time. |
| `LootDrop` | correlator output | The correlated result row (see Evidence below). |

`EncounterBegin`, `EncounterActivity`, and `EncounterEnd` are synthetic outputs. They are not parser events, so they never appear in `raw_events`. The pipeline drains them beside `LootDrop` and the writer persists them. See the rates semantics section for what they drive.

## Ingestion rules

All rules implemented in `src/gorgon_tracker/correlator.py:276-437`.

### Loot

`ingest_loot` appends to a pending buffer. If the event has an `instance_id` in the known `item_codes` map, the correlator attaches the code id.

### Bury

`ingest_bury` flushes pending drops against the current monster, records a `Buried` activity and an `EncounterEnd` on the current encounter, then starts a new encounter and clears monster, flags, activity hint, and corpse state.

### Source (packet frame)

`ingest_source` decides whether the frame is the same encounter: same monster and within `session_timeout` seconds. A state transition (`just_skinned` = same encounter, previous `can_skin` true, now false) relabels the flush if drops fall within the threshold and records a `Skinning`/`Butchering`/`Extracting` activity. Otherwise a monster change rolls a new `encounter_uuid`, emits `EncounterBegin` for the old one's end, and starts the new encounter.

### Interaction and corpse search

- `ingest_interaction` opens a loot window. If the entity id maps to a known monster, it restores that monster context. The tracker never maps a ground-node or container entity to a monster. Such a window does not flush pending loot, so a ground pickup never inherits a lingering corpse (`correlator.py:345-361`).
- `ingest_corpse_search` records the monster by entity id. The corpse-description extractions (`skinned/butchered/extracted <item> from the corpse`) drive activity: a verb that newly appears on a previously-seen corpse flushes pending loot as that activity and records it on the encounter. A corpse first seen already showing the verb, or re-searched unchanged, never relabels or records (`correlator.py:374-435`).
- The local player's own action arrives as the reward form (`<you> skinned/butchered/extracted the corpse (...) and obtained <items>`, parsed by `REWARD_RE` in `playerlog.py:63`). The reward names the items it granted (`reward_items`), so it is the fresh-action signal itself: it relabels without needing a prior search (`correlator.py:404-415`). The attribution is per item: only the named reward items inherit the verb, and other corpse loot in the same window (for example Stomach alongside skins) stays `Looting` (`correlator.py:819-832`).

### Chat activity marker

`ingest_activity` stores an activity hint that applies to drops within `activity_window_seconds`, before or after the marker (`correlator.py:363-369`). It records the activity on the current encounter when a monster binds it. It also flushes immediately, so the `x added to inventory.` line before or after it is labeled.

### Encounter lifecycle records

Every new encounter with a known monster emits an `EncounterBegin` and a `Looting` activity (`_begin_encounter`, `correlator.py:516-527`). A corpse search frame means the player opened the corpse dialogue, which is looting performed. Activity records are emitted at the detection points above. A chat marker with no monster context never records. The `EncounterEnd` emits on bury and on encounter roll-over (`_end_encounter`, `correlator.py:538-543`).

The pipeline drains these through the writer (`pipeline.py:216-217`). Replay does the same per timeline event (`replay.py:212`).

## Flush and attribution

`_flush` (`correlator.py:791-`) runs on a source/bury/activity/corpse-search event. For each pending drop, after chat/unity reconciliation:

1. Monster-linked branch: `monster_lag <= buffer_seconds`, `monster_lag < orphan_lag`, and `_plausibly_from_corpse` accepts the drop (`correlator.py:595-614`). A Unity pickup passes when its entity id maps to the current monster. A chat-only pickup passes when the open window is a corpse of the current monster and the pickup is within `search_corroboration_seconds`. Without any Unity corpse knowledge, every pickup passes (legacy proximity). Activity is `Looting`, upgraded to `Skinning`/`Butchering`/`Extracting` on a `just_*` transition within the window, or to the chat activity hint. Status `Linked`.
2. Orphan branch: best target sighting within `target_fallback_seconds` (smallest lag wins). A same-name corpse search within `search_corroboration_seconds` makes it `Looting`. Otherwise it is `Harvesting` (flowers/logs/apples have no corpse-search packet). No target → `Ground/Unknown` with status `Orphaned`.

`flush_expired` (`correlator.py:455-473`) emits orphaned drops for pending loot older than `buffer_seconds` so live streams do not hold them forever. `finalize` (`correlator.py:476-516`) flushes the remainder at end of stream with `lag_ms=0`, by the same branch rules.

## Chat / Unity reconciliation

Chat and Unity facts for the same physical pickup share a whole-second timestamp. `_reconcile` (`correlator.py:617-726`) buckets events by whole second and pairs them in three passes:

1. Exact token match on the item name (tokens = lowercase alphanumerics).
2. One remaining item on each side → forced pair.
3. Fuzzy best match via rapidfuzz (max of ratio / partial / token_sort), threshold `85.0`.

Paired facts join the chat display name with the Unity instance/entity identity, so the same pickup never double-counts.

## Evidence audit trail

Every `LootDrop` carries attribution evidence (`correlator.py:120-144`):

| Field | Meaning |
|---|---|
| `linked_via` | `monster`, `target`, or `orphan`. |
| `monster_name`, `monster_lag_ms` | The monster source that claimed the drop. |
| `target_name`, `target_lag_ms` | The target sighting that claimed the drop. |
| `corroborated_by_search` | A same-name corpse-search packet corroborated a target link. |
| `instance_id`, `entity_id`, `item_code_id`, `item_display` | Unity provenance. |
| `missed` | Inventory full. Not collected. |
| `killer_json` | Killer + participant damage table for the corpse's encounter. |

## Rates semantics (per activity)

Drop rates divide by the activity ledger, not by encounters that produced drops. The ledger table `encounter_activities` has one row per `(encounter_id, activity)`. The unique key dedupes the same action reported by a packet transition, a chat marker, and a corpse description.

The `v_drop_rates` view (migration v7, `db.py:117-152`) and the shared inline SQL (`serve.py:76-112`) group by `(monster, activity, item)`. The denominator is the count of distinct encounters where that activity happened, joined from `encounter_activities`:

- A `Skinning` drop divides by skinned encounters, not by every deer encounter.
- A `Looting` drop divides by encounters where the corpse dialogue opened.
- Crude Animal Skin from a deer reads 1 drop / 1 skinned deer, even when only 1 of 100 deer encounters was skinned.

Encounters are written eagerly at first sighting (`ingest.py:223-236`), so a corpse that yields no recorded loot still counts as an encounter. The `events_counts` from a stream end flush the end time. Orphan and `Harvesting` drops keep their own synthetic encounter and stay out of the monster ledger.

`/api/stats` counts encounters the same way: distinct encounters with any recorded activity (or with the filtered activity) instead of encounters-with-drops.

## Timeline merge (offline replay)

`replay.py:183-233` merges events from all sources into `(time_ms, priority)` tuples, then feeds one event at a time through the same correlator:

| Priority | Events |
|---|---|
| 0 | `ZoneChange`, `TargetSighting` (state) |
| 1 | `LootEvent` (loot before state changes at equal time) |
| 2 | `SourceEvent`, `BuryEvent`, `ActivityEvent`, `InteractionStart`, `CorpseSearch`, `ItemCode` |

## Backfill of historical sessions

Sessions captured before activity tracking only have drop-derived encounters. `gorgon-tracker backfill-encounters` replays each session's own `raw_events` through the correlator and writes the missing ledger (`src/gorgon_tracker/backfill.py`). Rebuilt encounters match existing rows by (monster, drop times). Zero-drop corpses match by (monster, zone, start time). Loot rows are never rewritten.

Sessions whose `raw_events` contain no corpse events cannot be replayed. This covers legacy CSV imports, where the loot rows already carry monster, activity, and encounter identity. For those sessions the drops are the only evidence, so the backfill derives the ledger from them: each distinct drop activity on an encounter becomes one row at the earliest drop time (`_derive_legacy_ledger`). The backfill also stamps the encounter's zone and end time from the drops. Skinned corpses that yielded no loot are unknowable in legacy data, so the derived ledger records only observed activities. The CLI table and the API result show the derived count.

## Source of truth and tests

- Correlator: `src/gorgon_tracker/correlator.py`
- Config: `[correlate]` in `src/gorgon_tracker/config.py:68-84`
- Writer: `src/gorgon_tracker/ingest.py`
- Backfill: `src/gorgon_tracker/backfill.py`
- Golden scenario: `tests/scenario.py`; expected output `tests/fixtures/phase1/expected_loot.csv`
- Tests: `tests/test_correlator.py`, `tests/test_replay.py`, `tests/test_backfill.py`

Update this doc when any correlation constant, transition rule, reconcile pass, evidence field, or rates-denominator rule changes.