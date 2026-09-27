# Spec: Unity Player.log format

This spec describes the Project Gorgon Unity `Player.log` lines the tracker parses. It is the canonical reference for the Player.log message format.

## Source and rotation

The game writes `Player.log` to the same folder tree as the chat logs:

```text
<Steam library>/steamapps/compatdata/342940/pfx/drive_c/users/steamuser/
  AppData/LocalLow/Elder Game/Project Gorgon/Player.log
```

At every game launch the game rotates `Player.log` to `Player-prev.log` and starts a new file. The tracker auto-detects the path as the sibling of the chat dir (`config.py:194-217`) or uses `[playerlog] path`. The live source `sources/player_log.py` parses with one persistent `PlayerLogParser` so clock anchor and corpse-window state span polls. `[playerlog] backfill_prev` (default false) parses `Player-prev.log` once at startup.

## Clock

`Player.log` stamps lines in UTC wall time with `[HH:MM:SS]`, not epoch. The parser anchors the date from the login line:

```text
[03:12:22] Logged in as character Mennelaia. Time UTC=09/24/2026 03:12:22. Timezone Offset -04:00:00
```

Regex: `LOADING` no field; login handled at `src/gorgon_tracker/parsers/playerlog.py:37-41`. `_line_ms` (playerlog.py:116-129) builds absolute epoch ms from the log's `HH:MM:SS` plus the anchored UTC date, with a rollover guard (`+1 day`) if stamps drop more than 60 s behind the last seen value.

The live source `sources/player_log.py` tails from the file end by default, so the top-of-file login line is never fed. It seeds the anchor with `set_anchor_from` (playerlog.py:131-148) by scanning the existing file at start and again on rotation, so timestamps are real epoch ms. A file with no login line (partial replay) falls back to the current UTC wall-clock date (`_line_ms`, playerlog.py:117-121) so absolute times stay plausible and match the chat source for cross-source dedupe (`specs/correlation.md`).

## Corpus lines

The file is mostly asset/appearance download noise. Only `LocalPlayer: Process*` lines and zone markers are kept. Regexes: `playerlog.py:42-65`.

### Item pickup and corpse removal

```text
LocalPlayer: ProcessAddItem(GoblinCallingCard15(-1719916789), -1, True)
LocalPlayer: ProcessRemoveLoot(-1719916789)
```

- `ProcessAddItem(<item>(<iid>), -1, <new>)`: the third argument separates real pickups (`True`) from login-time inventory loads (`False`). Only `True` emits a `LootEvent` (`playerlog.py:194-210`).
- `ProcessRemoveLoot(<iid>)`: removes an item off the corpse. A removed iid that never matches a pickup during the corpse window was not collected (inventory full) and emits `LootEvent(item="Unknown", missed=True)` at window close.

### Interaction and corpse-search

```text
LocalPlayer: ProcessStartInteraction(996594, 13.5, 0, False, "")
LocalPlayer: ProcessTalkScreen(996594, "Search Corpse of Goblin Horsebeater", "...", ..., Corpse)
```

- `ProcessStartInteraction(<eid>, ...)` opens a looting window (emits `InteractionStart`), flushing any prior window (`playerlog.py:218-222`).
- `ProcessTalkScreen(<eid>, "Search Corpse of <monster>", ...)` opens a corpse search (emits `CorpseSearch` with killer and participants, `playerlog.py:224-246`).
- The talk-screen details body can include:
  - Killer: `<em>Killer:</em> <name>` (`KILLER_RE`, playerlog.py:58).
  - Damage table: `<name>: <n> health dmg[ <n2> armor dmg]. Aggro (at death): <pct>%` (`PARTICIPANT_RE`, playerlog.py:59-61).
  - Extractions: `<name> <verb> <item> from the corpse` where verb is `extracted|skinned|butchered|harvested` (`EXTRACT_RE`, playerlog.py:62).
  - Reward: `<name> <verb> the corpse (...) and obtained <item> x2 plus <item>` where verb is `skinned|butchered|extracted` (`REWARD_RE`, playerlog.py:63). This form names the local player's own action and the items it granted. `EXTRACT_RE` handles pre-existing corpse state; `REWARD_RE` handles the local player's fresh action.
- Unity escapes real newlines as literal `\n` inside the logged text. `_parse_talk_details` unescapes them first (`playerlog.py:307-335`).

### Errors and screen text

```text
LocalPlayer: ProcessErrorMessage(InventoryFull, "...")
LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")
LocalPlayer: ProcessScreenText(GeneralInfo, "You searched the corpse and found 42 coins.")
```

- `ProcessErrorMessage(InventoryFull, ...)` closes the current corpse window (missed-loot flush).
- `ProcessScreenText(GeneralInfo|CombatInfo, "<msg>")` with message `You bury the corpse.` closes the window and emits a `BuryEvent`. `You searched the corpse and found <n> coins.` emits a `LootEvent` for item `Coins` with amount `<n>` (`playerlog.py:174-192`).

### Zone markers

```text
LOADING LEVEL AreaSerbule2
```

`LOADING LEVEL Area<id>` emits a `ZoneChange`. The internal area id maps to the friendly name via the bundled zone catalog (`AreaSerbule2` → `Serbule Hills`, `playerlog.py:145-161`).

## Missed-loot window algorithm

One `_Window` tracks the open corpse interaction (`playerlog.py:82-88`):

- `removals`: iids removed off the corpse (`ProcessRemoveLoot`) not yet confirmed in inventory.
- `collected`: iids seen in both `RemoveLoot` and a pickup.

At window close (new interaction, corpse search, error, or bury), every iid still in `removals` emits a missed `LootEvent`. `parser.close()` flushes the trailing window at end of stream (`playerlog.py:282-297`).

A skinning/butchering/extracting reward does not stock items through a corpse-window pickup. Instead the game reports one `ProcessRemoveLoot` per reward bundle, and the items reach inventory by way of the talk-screen reward text and the chat `added to inventory.` lines. Because that `ProcessRemoveLoot` never meets a matching pickup, the plain rule would emit a false `Unknown (Missed)` row for a reward the player actually collected. When a corpse search carries a fresh reward for the same corpse, `_close_window(... suppress_missed=True)` drops those unmatched removals instead of emitting them (`playerlog.py:252-280`).

## Source of truth and tests

- Parser: `src/gorgon_tracker/parsers/playerlog.py`
- Live tailer: `src/gorgon_tracker/sources/player_log.py`
- Tests: `tests/test_playerlog.py`, `tests/test_player_log_source.py`
- Reconcile of chat + unity facts: `src/gorgon_tracker/correlator.py:670-789` (see `specs/correlation.md`)

Update this doc when the game's log line shapes or the window/missed-loot logic change.