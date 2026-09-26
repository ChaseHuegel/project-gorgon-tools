# Spec: Game-data CDN and wiki formats

This spec describes the canonical item and zone data formats the tracker fetches from Project Gorgon's official third-party data CDN, plus the wiki name lists. This is the canonical reference for these data formats.

## Catalog snapshots

Source: `src/gorgon_tracker/catalog.py`.

### CDN layout

- Version probe: `http://client.projectgorgon.com/fileversion.txt` returns a plain version string (e.g. `486`).
- Data files: `https://cdn.projectgorgon.com/v<version>/data/<file>`.
- The CDN keeps only the last few versions. `_fetch_versions` retries up to 4 older versions (`catalog.py:240-265`, `_VERSION_RETRIES = 4` at `catalog.py:44`).

### `items.json`

Compact form, one keyed row per line:

```json
{"version": "486", "items": [
  ["AAmuletOfTheRuggedTraveler", "Advanced Amulet of the Rugged Traveler",
   300, 1, ["AAmuletOfTheRuggedTraveler", "Amulet", "Elegant", "Equipment",
   "Jewelry", "Loot", "Necklace"], 17001],
  ...
]}
```

Row layout (compacted at `catalog.py:268-281`):

| Index | Field | Source key | Type |
|---|---|---|---|
| 0 | `slug` | `InternalName` | string |
| 1 | `name` (canonical display) | `Name` | string |
| 2 | `value` | `Value` | int or null |
| 3 | `stack` (max stack) | `MaxStackSize` | int or null |
| 4 | `keywords` | `Keywords` | string list |
| 5 | `icon` | `IconId` | int or null |

The `slug` is the Unity internal item name that appears in `Player.log` (`ArmorPatchKit3`). The catalog maps slugs to canonical display names; fallback splits the slug into `(base, code)` (`src/gorgon_tracker/itemdb.py:27-40`).

### `areas.json`

```json
{"version": "486", "areas": [
  ["AreaNewbieIsland", "Anagoge Island", "Anagoge", ["AreaSerbule", "AreaSerbuleCaves"]],
  ...
]}
```

Row layout (compacted at `catalog.py:284-292`):

| Index | Field | Source key | Type |
|---|---|---|---|
| 0 | `area_id` | key | string |
| 1 | `name` (friendly) | `FriendlyName` | string |
| 2 | `short` (alias) | `ShortFriendlyName` | string |
| 3 | `adjacent` (area ids) | `AdjacentAreas` | string list |

Used to map `LOADING LEVEL Area<id>` lines to friendly names (see `specs/player-log.md`) and to build the OCR zone-name alias table.

### `version.txt`

Plain text with the pinned game-data version. Note the bundled file contains literal quotes (`"486"`); the fetcher writes it bare (`catalog.py:326`).

### Storage and override

- Bundled snapshots ship in `src/gorgon_tracker/data/` (`items.json`, `areas.json`, `version.txt`).
- A per-user snapshot in `default_catalog_dir()` overrides them: `$XDG_DATA_HOME` (or `~/.local/share`) + `gorgon-tracker/catalog` (`catalog.py:122-125`), or `[catalog] data_dir`.
- Refresh: `gorgon-tracker update-catalog` (CLI) or the web button (POST `/api/catalog/update`), which also re-seeds the DB `items` table. Snapshots are written atomically (`catalog.py:295-304`).

## Wiki name lists

Source: `src/gorgon_tracker/names.py`.

### File format

`zones.txt` and `monsters.txt`, one name per line, `#` comments and blank lines ignored (`names.py:78-87`). Examples:

```text
Anagoge
Anagoge Island
Anagoge Records Facility
```

### Fetch

`gorgon-tracker update-names` (CLI; `names.py:368-375`) pulls category pages from the Project Gorgon wiki. Zone categories are `Zones`, `Dungeons`, and the `Creatures by Area` subcategories; monster categories are the per-area creature lists plus `Creatures by Type`, `Creatures by Event`, `Animal Handling Creatures`, `Bosses` (`names.py:329-359`). Disambiguation suffixes like `(Elite)` are stripped (`_TRAILING_PAREN_RE`, `names.py:53,338-339`).

### Storage and override

- Bundled: `src/gorgon_tracker/data/zones.txt` / `monsters.txt`.
- Per-user override: `default_names_dir()` = `$XDG_DATA_HOME` (or `~/.local/share`) + `gorgon-tracker/names` (`names.py:72-75`), or `[names] data_dir`. The manager uses a user file when it is non-empty, else the bundled file (`names.py:90-98`).
- Hot reload: `NameCorrector.refresh_if_changed` re-reads on mtime change (`names.py:209-215`).

### Correction rules

`NameCorrector.correct(text, kind)` (`names.py:154-198`):

1. Normalize (lowercase, strip non-`[a-z\s]`).
2. Lookup: alias map (built from catalog short names, e.g. `Anagoge` → `Anagoge Island`, `names.py:130-131`) → exact normalized → space-stripped.
3. Fuzzy token stage: `max(token_sort_ratio, ratio)` against the `[names.<kind>] ratio` threshold (default `90`).
4. Partial stage: length-diff ≥ 3 and length-ratio ≥ 0.5, scored with `partial_ratio` against `[names.<kind>] partial_ratio` (default `85`).
5. A top-two gap under `_AMBIGUITY_DELTA = 3.0` refuses the rewrite (conservative: near-ties are left untouched, `names.py:247-260`).

## Source of truth and tests

- CDN fetch + compaction: `src/gorgon_tracker/catalog.py`
- Item slug split: `src/gorgon_tracker/itemdb.py`
- Wiki fetch + correction: `src/gorgon_tracker/names.py`
- Refresh tools: `tools/update_catalog.py`, `tools/update_names.py`
- Tests: `tests/test_catalog.py`, `tests/test_names.py`

Update this doc when the CDN file layouts, the fetch URLs, the compaction rules, or the name-correction thresholds change.