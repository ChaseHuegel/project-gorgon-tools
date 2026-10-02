# Spec: CSV and import formats

This spec describes the CSV files the tracker writes and reads, plus the legacy JSON intermediates accepted by `migrate`. This is the canonical reference for these formats.

## Export CSV (loot)

Source: `src/gorgon_tracker/export.py`. Produced by `gorgon-tracker export` and `GET /api/export`.

Header (`export.py:12`):

```text
Time,Source,ID,Activity,Item,Amount,Status,LagTime,Zone
```

- `Time`: local time `%Y-%m-%d %H:%M:%S` (`export.py:56-57`).
- `ID`: the encounter UUID.
- `LagTime`: `lag_ms / 1000` with two decimals (`export.py:84`).
- `Source`, `Activity`, `Status`: manual overrides from `loot_overrides` win via `COALESCE` (`export.py:27-53`).

With `--with-evidence` the header appends the audit columns after `Zone` (`export.py:13-25`):

```text
LinkedVia,MonsterName,MonsterLagMs,TargetName,TargetLagMs,
CorroboratedBySearch,Missed,InstanceId,EntityId,ItemCodeId,KillerJson
```

### Analysis CSV (drop rates)

Header (`export.py:117`):

```text
Monster,Activity,Item,Drops,Quantity,Encounters,DropRate,LastSeen
```

Rows are per `(monster, activity, item)`. `Encounters` counts the corpses where
that activity happened (`docs/specs/correlation.md` → Rates semantics).
`DropRate` renders as a percentage with two decimals (`export.py:134`).

## Legacy CSV inputs

Reader: `src/gorgon_tracker/parsers/csvs.py`.

### Legacy loot CSV (`read_legacy_loot_csv`)

Same base header as the export CSV. `Time` accepts any format `iso_to_ms` parses (see Timestamps below). `LagTime` is seconds (float), converted to ms (`csvs.py:44-49`). `Amount` defaults to `1`.

### `zones.csv` and `targets.csv`

Change-detected OCR output from the legacy PowerShell capture:

| Column | Meaning |
|---|---|
| `Time` | Capture time; parsed with `assume_utc=True` (legacy output stored UTC wall-clock strings). |
| `Text` | OCR text (zone name or target name). |

Fallback column names `time`/`zone`/`target` are accepted (`csvs.py:28-41`).

## Migrate JSON intermediates

Source: `src/gorgon_tracker/migrate.py`. Kind is detected from the filename (`filename` contains `zone` → zones, `target` → targets, `chat`/`parsed-chat` → chat-json, `packet`/`parsed-packet` → packets-json, else loot).

### `parsed-chat*.txt` / chat JSON

A JSON list. Each entry:

| Field | Meaning |
|---|---|
| `EventType` | `"Bury"` or `"Loot"`. |
| `ItemName` | Item (loot only). |
| `Amount` | Count (loot only). |
| time | `\/Date(ms)\/` (`.NET`), an ISO string, or a chat-style timestamp (`_entry_time_ms`, `migrate.py:113-117`). |

### `parsed-packet*.txt` / packets JSON

A JSON list, one entry per corpse-search frame:

| Field | Meaning |
|---|---|
| `Monster` | Monster name. |
| `CanSkin`, `CanButcher`, `CanExtract` | Flag truthiness; accepts bool, `None`, `"1"`, `"true"`, `"yes"` (`migrate.py:105-110`). |
| time | Encodes the frame time. |

## Timestamps accepted anywhere (`timeutil.iso_to_ms`)

Source: `src/gorgon_tracker/timeutil.py:28-60`.

1. `.NET` `/Date(ms)/`.
2. Chat `yy-MM-dd HH:mm:ss[.fff]` (assumed local).
3. Google Sheets US `M/D/YYYY h:mm:ss AM/PM`, `M/D/YYYY HH:MM:SS`, or `M/D/YYYY` (assumed local).
4. ISO-8601 (naive assumed local; `assume_utc=True` for OCR CSVs).

## Source of truth and tests

- Export: `src/gorgon_tracker/export.py`
- CSV readers: `src/gorgon_tracker/parsers/csvs.py`
- Migrate: `src/gorgon_tracker/migrate.py`
- Timestamps: `src/gorgon_tracker/timeutil.py`
- Tests: `tests/test_export.py`, `tests/test_migrate.py`, `tests/test_timeutil.py`

Update this doc when any header, column, or accepted timestamp format changes.