# Spec: Project Gorgon chat log format

This spec describes the game chat-log lines the tracker parses. It is the canonical reference for the chat message format.

## Location and rotation

The game saves chat logs as plain-text files when the player enables "Save Chat Logs" (VIP feature). Files live under `ChatLogs/`:

```text
<Steam library>/steamapps/compatdata/342940/pfx/drive_c/users/steamuser/
  AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs
```

The tracker auto-detects the directory (`src/gorgon_tracker/config.py:171-191`) or uses `[chat] log_dir`. The live source `sources/chat_tail.py` tails the newest `*.log` or `*.txt` file by mtime, polls `[chat] poll_interval_s` (default 1.0), and handles rotation via device+inode tracking. See `src/gorgon_tracker/sources/chat_tail.py:61-119`.

## Line format

The parser matches whole lines that start with a `[Status]` tag. All three regexes live at `src/gorgon_tracker/parsers/chat.py:12-20`.

### Loot pickup

```text
[Status] <item> added to inventory.
[Status] <item> x<count> added to inventory.
```

Regex: `^(?P<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+(?P<item>.+?)(?:\s+x(?P<count>\d+))?\s+added to inventory\.$`

Count defaults to `1` when the `x<count>` part is absent (`chat.py:46`).

### Corpse burial

```text
[Status] You bury the corpse.
```

Regex: `^(?P<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+You bury the corpse\.$`

### Corpse action marker

```text
[Status] You skin the corpse.
[Status] You butcher the corpse.
[Status] You extract the skull.
```

Regex: `^(?P<timestamp>[\d-]+\s+[\d:]+)\s+\[Status\]\s+You (?P<verb>skin\w*|butcher\w*|extract\w*)\b`

Verbs normalize to an activity (`chat.py:22-32`):

| Verb | Activity |
|---|---|
| skin, skinned, skinning | `Skinning` |
| butcher, butchered, butchering | `Butchering` |
| extract, extracted, extracting | `Extracting` |

## Timestamps

The line timestamp is `yy-MM-dd HH:mm:ss[.fff]` (two-digit year). `timeutil.iso_to_ms` treats it as local time (`src/gorgon_tracker/timeutil.py:39-43`).

## Output events

`parse_chat_line` returns one of the correlation DTOs (`src/gorgon_tracker/correlator.py:30-52`):

| Event | Fields |
|---|---|
| `LootEvent` | `time_ms`, `item`, `amount` |
| `BuryEvent` | `time_ms` |
| `ActivityEvent` | `time_ms`, `activity` |

## Source of truth and tests

- Parser: `src/gorgon_tracker/parsers/chat.py`
- Live tailer: `src/gorgon_tracker/sources/chat_tail.py`
- Tests: `tests/test_chat.py`, `tests/test_chat_tail.py`
- Golden chat fixture: built by `tests/scenario.py:83-92`

Update this doc when the chat line format, the status tag, or the verb-to-activity mapping changes.