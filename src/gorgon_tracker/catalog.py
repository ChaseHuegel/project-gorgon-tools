"""Canonical item/zone catalogs from Project Gorgon's official data CDN.

Two compact snapshots ship with the package (``data/items.json``,
``data/areas.json``) and can be refreshed from the game's third-party-data CDN
via :func:`update_catalog_files` (used by the ``update-catalog`` CLI command and
the web UI button):

* ``items.json`` maps the Unity ``Player.log`` internal item slug
  (``ArmorPatchKit3``) to its canonical display name and metadata
  (``Good Armor Patch Kit``, value, max stack, keywords, icon id). This is the
  exact key space the tracker already splits with ``itemdb.split_item_name``, so
  the catalog resolves slug -> display authoritatively instead of guessing from
  CamelCase.
* ``areas.json`` maps the game's internal area ids (``AreaSerbule2``) to the
  friendly player-visible name and its short alias, plus the adjacent-area graph.
  The Player.log ``LOADING LEVEL Area...`` line uses these ids, so the catalog
  turns a raw ``AreaSerbule2`` into ``Serbule Hills``.

The catalogs are canonical reference only. They never feed the drop-rate
aggregates; coincident with ``names.py``, a per-user data directory can pin a
custom snapshot that overrides the bundled one.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_BUNDLED_DIR = Path(__file__).resolve().parent / "data"
_ITEMS_FILE = "items.json"
_AREAS_FILE = "areas.json"
_VERSION_FILE = "version.txt"

_CDN_ROOT = "https://cdn.projectgorgon.com"
_VERSION_URL = "http://client.projectgorgon.com/fileversion.txt"
_USER_AGENT = "gorgon-tracker/0.1 (catalog refresh; contact: gorgon-tracker users)"
# The CDN guarantees only the last few game-data versions; retry older versions
# if the newest one has not been mirrored yet.
_VERSION_RETRIES = 4


@dataclass(frozen=True)
class ItemEntry:
    """One authoritative item identity from the game's own data files."""

    slug: str  # Unity internal name, e.g. ``ArmorPatchKit3``
    name: str  # canonical display name, e.g. ``Good Armor Patch Kit``
    value: int | None
    stack: int | None
    keywords: tuple[str, ...]
    icon: int | None


@dataclass(frozen=True)
class Zone:
    """One area: internal id, friendly names, and the adjacent-area graph."""

    area_id: str  # internal id, e.g. ``AreaSerbule2``
    name: str  # friendly player-visible name, e.g. ``Serbule Hills``
    short: str  # short alias, e.g. ``Anagoge`` for ``Anagoge Island``
    adjacent: tuple[str, ...]  # internal ids of connected areas


class ItemCatalog:
    """Lookup indexes over the bundled/user item snapshot."""

    def __init__(self, version: str, entries: list[ItemEntry]) -> None:
        self.version = version
        self.by_slug: dict[str, ItemEntry] = {}
        self.by_key: dict[tuple[str, str], ItemEntry] = {}
        from .itemdb import split_item_name

        for entry in entries:
            self.by_slug.setdefault(entry.slug, entry)
            base, code = split_item_name(entry.slug)
            self.by_key.setdefault((base, code), entry)

    def display_for(self, slug: str) -> str | None:
        """Canonical display name for a Unity slug, or None when unknown."""
        entry = self.by_slug.get(slug)
        if entry is not None:
            return entry.name
        from .itemdb import split_item_name

        base, code = split_item_name(slug)
        entry = self.by_key.get((base, code))
        return entry.name if entry is not None else None


class ZoneCatalog:
    """Lookup indexes over the bundled/user area snapshot."""

    def __init__(self, version: str, zones: list[Zone]) -> None:
        self.version = version
        self.by_id: dict[str, Zone] = {zone.area_id: zone for zone in zones}
        self.zones = zones

    def name_for_id(self, area_id: str) -> str | None:
        zone = self.by_id.get(area_id)
        return zone.name if zone is not None else None

    def aliases(self) -> dict[str, str]:
        """Short-name alias (normalized) -> canonical name, where they differ."""
        from .names import _normalize

        aliases: dict[str, str] = {}
        for zone in self.zones:
            if not zone.short:
                continue
            short = _normalize(zone.short)
            full = _normalize(zone.name)
            if short and short != full:
                aliases[short] = zone.name
        return aliases


def default_catalog_dir() -> Path:
    """Per-user data directory holding refreshable catalog snapshots."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "gorgon-tracker" / "catalog"


def _item_file(data_dir: Path | None) -> Path:
    best = (data_dir or default_catalog_dir()) / _ITEMS_FILE
    return best if best.is_file() else (_BUNDLED_DIR / _ITEMS_FILE)


def _area_file(data_dir: Path | None) -> Path:
    best = (data_dir or default_catalog_dir()) / _AREAS_FILE
    return best if best.is_file() else (_BUNDLED_DIR / _AREAS_FILE)


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_item_catalog(data_dir: str | os.PathLike[str] | None = None) -> ItemCatalog:
    """Load the item catalog (user snapshot overrides the bundled one)."""
    path = _item_file(Path(data_dir) if data_dir else None)
    data = _read_json(path)
    entries = [
        ItemEntry(
            slug=raw[0],
            name=raw[1],
            value=raw[2],
            stack=raw[3],
            keywords=tuple(raw[4] or ()),
            icon=raw[5],
        )
        for raw in data["items"]
    ]
    return ItemCatalog(str(data.get("version", "")), entries)


def load_zone_catalog(data_dir: str | os.PathLike[str] | None = None) -> ZoneCatalog:
    """Load the zone catalog (user snapshot overrides the bundled one)."""
    path = _area_file(Path(data_dir) if data_dir else None)
    data = _read_json(path)
    zones = [
        Zone(area_id=raw[0], name=raw[1], short=raw[2], adjacent=tuple(raw[3] or ()))
        for raw in data["areas"]
    ]
    return ZoneCatalog(str(data.get("version", "")), zones)


# --- process-lifetime cache --------------------------------------------------

_item_catalog: ItemCatalog | None = None
_zone_catalog: ZoneCatalog | None = None


def item_catalog(data_dir: str | os.PathLike[str] | None = None) -> ItemCatalog:
    """Return the cached item catalog (thread-safe enough for a single runtime)."""
    global _item_catalog
    if _item_catalog is None:
        _item_catalog = load_item_catalog(data_dir)
    return _item_catalog


def zone_catalog(data_dir: str | os.PathLike[str] | None = None) -> ZoneCatalog:
    global _zone_catalog
    if _zone_catalog is None:
        _zone_catalog = load_zone_catalog(data_dir)
    return _zone_catalog


def item_display_for(slug: str, data_dir: str | os.PathLike[str] | None = None) -> str | None:
    """Canonical display name for a Unity item slug, or None when unknown."""
    return item_catalog(data_dir).display_for(slug)


def item_seed_rows(
    data_dir: str | os.PathLike[str] | None = None,
) -> list[tuple[str, str, str, int | None, int | None, str | None, int | None, str]]:
    """Rows for the ``items`` table seed: (base, code, display, value, stack, keywords_json, icon, version)."""
    from .itemdb import split_item_name

    cat = item_catalog(data_dir)
    rows: list[tuple[str, str, str, int | None, int | None, str | None, int | None, str]] = []
    for entry in cat.by_key.values():
        base, code = split_item_name(entry.slug)
        keywords_json = json.dumps(list(entry.keywords)) if entry.keywords else None
        rows.append(
            (base, code, entry.name, entry.value, entry.stack, keywords_json, entry.icon, cat.version)
        )
    return rows


def reload() -> None:
    """Drop cached catalogs so the next access reloads from disk."""
    global _item_catalog, _zone_catalog
    _item_catalog = None
    _zone_catalog = None


# --- CDN fetch + snapshot write ----------------------------------------------

def current_data_version(fetch: Callable[[str], Any] | None = None) -> str:
    """Read the current game-data version from the CDN's version probe."""
    if fetch is None:
        fetch = _fetch_url_text
    return str(fetch(_VERSION_URL)).strip()


def _fetch_url_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=20.0) as response:  # noqa: S310 - fixed game CDN
        data: object = response.read()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)


def _fetch_versions(
    filename: str,
    fetch: Callable[[str], Any] | None = None,
) -> Any:
    """Fetch ``filename`` for the current version, retrying older versions."""
    if fetch is None:
        fetch = _fetch_url_text
    try:
        version = current_data_version(fetch)
    except OSError:
        version = ""
    attempts = [version] if version else []
    if version.isdigit():
        attempts += [str(int(version) - i) for i in range(1, _VERSION_RETRIES + 1)]
    last_error: Exception | None = None
    for ver in attempts:
        url = f"{_CDN_ROOT}/v{ver}/data/{filename}"
        try:
            raw = fetch(url)
            if isinstance(raw, dict | list):
                return raw
            return json.loads(str(raw))
        except (OSError, ValueError) as exc:  # ValueError: malformed json (HTML error page)
            last_error = exc
            continue
    raise RuntimeError(f"unable to fetch {filename} from the Project Gorgon CDN ({last_error})")


def _compact_items(raw: dict[str, Any]) -> list[Any]:
    items: list[Any] = []
    for meta in raw.values():
        slug = str(meta.get("InternalName") or "")
        if not slug:
            continue
        name = str(meta.get("Name") or slug)
        value: int | None = meta.get("Value")
        stack: int | None = meta.get("MaxStackSize")
        keywords = [str(k) for k in (meta.get("Keywords") or ())]
        icon: int | None = meta.get("IconId")
        items.append([slug, name, value, stack, keywords, icon])
    items.sort(key=lambda row: row[0])
    return items


def _compact_areas(raw: dict[str, Any]) -> list[Any]:
    areas: list[Any] = []
    for area_id, meta in raw.items():
        name = str(meta.get("FriendlyName") or area_id)
        short = str(meta.get("ShortFriendlyName") or "")
        adjacent = [str(a) for a in (meta.get("AdjacentAreas") or ())]
        areas.append([area_id, name, short, adjacent])
    areas.sort(key=lambda row: row[0])
    return areas


def _atomic_write_json(path: Path, document: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(document), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def update_catalog_files(
    out_path: str | Path,
    fetch: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Fetch the current item/zone snapshots from the CDN and write them.

    Writes ``items.json``, ``areas.json``, and ``version.txt`` atomically under
    ``out_path``. Returns counts and the pinned game-data version.
    """
    dest = Path(out_path)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        version = current_data_version(fetch)
    except OSError:
        version = ""
    items_raw = _fetch_versions("items.json", fetch)
    areas_raw = _fetch_versions("areas.json", fetch)
    _atomic_write_json(dest / _ITEMS_FILE, {"version": version, "items": _compact_items(items_raw)})
    _atomic_write_json(dest / _AREAS_FILE, {"version": version, "areas": _compact_areas(areas_raw)})
    _atomic_write_text(dest / _VERSION_FILE, version)
    return {
        "version": version,
        "items": len(items_raw),
        "areas": len(areas_raw),
        "path": str(dest),
    }


def catalog_info(data_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Describe the effective catalog snapshot (source, counts, versions)."""
    user_dir = Path(data_dir) if data_dir else default_catalog_dir()
    items_path = _item_file(user_dir)
    areas_path = _area_file(user_dir)
    items_data = _read_json(items_path)
    areas_data = _read_json(areas_path)
    items = len(items_data["items"]) if items_data.get("items") else 0
    areas = len(areas_data["areas"]) if areas_data.get("areas") else 0
    version_file = user_dir / _VERSION_FILE
    version = version_file.read_text(encoding="utf-8").strip() if version_file.is_file() else ""
    return {
        "data_dir": str(user_dir),
        "item_source": "user" if (user_dir / _ITEMS_FILE).is_file() else "bundled",
        "area_source": "user" if (user_dir / _AREAS_FILE).is_file() else "bundled",
        "item_count": items,
        "area_count": areas,
        "version": version or str(items_data.get("version", "")),
    }