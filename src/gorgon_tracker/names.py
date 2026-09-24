"""Canonical zone/monster name lists: wiki fetch, snapshot files, fuzzy OCR correction.

Names enter the tracker through OCR and packet capture. OCR text is noisy, so
reads are corrected against canonical lists of known Project Gorgon zone and
monster names. The lists ship with the package (``data/zones.txt`` /
``data/monsters.txt``) and can be refreshed from the community wiki via
:func:`update_names_files` (used by the ``update-names`` CLI command and the
web UI button). User overrides live in a per-user data directory and take
precedence over the bundled snapshot.

Correction is deliberately conservative: text is only rewritten when it
matches a known name with high confidence, and a near tie between two
candidates leaves the raw OCR text untouched.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from .config import NamesConfig

logger = logging.getLogger("gorgon_tracker.names")

BUNDLED_DIR = Path(__file__).resolve().parent / "data"
_FILES = {"zones": "zones.txt", "monsters": "monsters.txt"}
_KINDS = ("zones", "monsters")

_API_URL = "https://wiki.projectgorgon.com/api.php"
_USER_AGENT = "gorgon-tracker/0.1 (name list refresh; contact: gorgon-tracker users)"
_MEMBER_LIMIT = 500

_ZONE_CATEGORIES = ("Zones", "Dungeons")
_AREA_CATEGORY = "Creatures by Area"
_TYPE_CATEGORY = "Creatures by Type"
_EVENT_CATEGORY = "Creatures by Event"
_ANIMAL_HANDLING_CATEGORY = "Animal Handling Creatures"
_BOSS_CATEGORY = "Bosses"
_SKIP_PAGES = {"Zones", "Zone Template", "Dungeons", "Creature Template"}

# Matches OCR sanitization: everything except letters and whitespace is dropped.
_NORM_RE = re.compile(r"[^a-z\s]")
# Wiki disambiguation suffixes, e.g. "Pig (mob)" -> "Pig".
_TRAILING_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*$")
# How close the top two fuzzy matches may be before we refuse to choose.
_AMBIGUITY_DELTA = 3.0
# Minimum length overlap for partial (substring) matching.
_PARTIAL_LENGTH_RATIO = 0.5
# Minimum length difference before partial matching is considered (a dropped
# or phoned-in extra word); equal-length text must win on the token stage.
_PARTIAL_LENGTH_DIFF = 3
# Maximum text not covered by a partial match before we reject it. Allows for
# a dropped leading "The" or a short OCR-adjacent word, but rejects large
# amounts of interleaved junk ("Mysterious New Zone" is not "Mysterious Locale").
_PARTIAL_UNCOVERED_BUDGET = 4.0


def _normalize(text: str) -> str:
    """Lowercase and drop non-alpha characters, mirroring OCR sanitization."""
    return _NORM_RE.sub("", " ".join(text.lower().split()))


def default_names_dir() -> Path:
    """Per-user data directory holding refreshable name overrides."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "gorgon-tracker" / "names"


def _read_names(path: Path) -> list[str]:
    """Read one name per line; blank lines and ``#`` comments are ignored."""
    if not path.is_file():
        return []
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        name = raw.strip()
        if name and not name.startswith("#"):
            names.append(name)
    return names


def _has_names(path: Path) -> bool:
    return bool(_read_names(path))


def _file_for(kind: str, user_dir: Path) -> tuple[Path, str]:
    user_file = user_dir / _FILES[kind]
    if _has_names(user_file):
        return user_file, "user"
    return (BUNDLED_DIR / _FILES[kind]), "bundled"


class _KindTable:
    """Precomputed lookup structures for one name kind."""

    def __init__(self, canonical: list[str], ratio: float, partial_ratio: float) -> None:
        self.canonical = canonical
        self.ratio = ratio
        self.partial_ratio = partial_ratio
        self.by_norm: dict[str, str] = {}
        self.by_stripped: dict[str, str] = {}
        for name in canonical:
            norm = _normalize(name)
            if norm:
                self.by_norm.setdefault(norm, name)
                self.by_stripped.setdefault(norm.replace(" ", ""), name)
        # Corpus of (normalized, canonical) pairs: several canonical names can
        # normalize identically (e.g. wiki duplicates), so the fuzzy ranking must
        # carry its canonical partner along.
        self.corpus: list[tuple[str, str]] = list(self.by_norm.items())


class NameCorrector:
    """Corrects OCR zone/monster reads against canonical name lists."""

    def __init__(self, names_cfg: NamesConfig, data_dir: str | None = None) -> None:
        self._cfg = names_cfg
        self._user_dir = Path(data_dir) if data_dir else default_names_dir()
        self._tables: dict[str, _KindTable] = {}
        self._sources: dict[str, str] = {}
        self._mtimes: dict[str, int] = {}
        for kind in _KINDS:
            self._reload(kind)

    # -- public API -----------------------------------------------------------

    def correct(self, text: str, kind: str) -> str:
        """Return the closest known name for ``text``, or ``text`` unchanged."""
        if not self._cfg.enabled:
            return text
        table = self._tables[kind]
        norm = _normalize(text)
        if not norm:
            return text

        canon = table.by_norm.get(norm)
        if canon is not None:
            return canon
        canon = table.by_stripped.get(norm.replace(" ", ""))
        if canon is not None:
            return canon

        stripped = norm.replace(" ", "")
        scores = [
            (
                max(fuzz.token_sort_ratio(norm, cand), fuzz.ratio(stripped, cand.replace(" ", ""))),
                i,
            )
            for i, (cand, _canon) in enumerate(table.corpus)
        ]
        best = self._pick(scores, table.ratio)
        if best is not None:
            return table.corpus[best][1]

        # Partial (substring) matching only rescues dropped/added-word noise:
        # candidates of near-identical length must clear the token stage on
        # their own, or a clean read of an unknown name would be rewritten
        # against a similar-sized neighbor (e.g. "Giant Bat" -> "Giant Rat").
        partial_scores = [
            (fuzz.partial_ratio(norm, cand), i)
            for i, (cand, _canon) in enumerate(table.corpus)
            if abs(len(norm) - len(cand)) >= _PARTIAL_LENGTH_DIFF
            and min(len(norm), len(cand)) / max(len(norm), len(cand), 1) >= _PARTIAL_LENGTH_RATIO
        ]
        best = self._pick(partial_scores, table.partial_ratio)
        if best is not None and self._partial_coverage_ok(norm, table.corpus[best][0]):
            return table.corpus[best][1]
        return text

    @staticmethod
    def _partial_coverage_ok(text: str, candidate: str) -> bool:
        """True when the partial match covers the text except a small prefix/suffix."""
        alignment = fuzz.partial_ratio_alignment(text, candidate)
        if alignment is None:  # pragma: no cover - only when score_cutoff rejects
            return False
        uncovered = len(text) - (alignment.src_end - alignment.src_start)
        return uncovered <= _PARTIAL_UNCOVERED_BUDGET

    def refresh_if_changed(self) -> None:
        """Reload tables when the backing files changed on disk (hot reload)."""
        for kind in _KINDS:
            path, _ = _file_for(kind, self._user_dir)
            mtime = int(path.stat().st_mtime_ns // 1_000_000) if path.is_file() else 0
            if mtime != self._mtimes[kind]:
                self._reload(kind)

    def info(self) -> dict[str, Any]:
        """Per-kind source and counts, as used by the web/CLI status display."""
        info: dict[str, Any] = {"enabled": self._cfg.enabled, "data_dir": str(self._user_dir)}
        for kind in _KINDS:
            path, source = _file_for(kind, self._user_dir)
            mtime = int(path.stat().st_mtime_ns // 1_000_000) if path.is_file() else None
            info.update(
                {
                    f"{kind}_count": len(_read_names(path)),
                    f"{kind}_path": str(path),
                    f"{kind}_source": source,
                    f"{kind}_mtime_ms": mtime,
                }
            )
        return info

    # -- internals ------------------------------------------------------------

    def _reload(self, kind: str) -> None:
        path, source = _file_for(kind, self._user_dir)
        kind_cfg = getattr(self._cfg, kind)
        self._tables[kind] = _KindTable(_read_names(path), kind_cfg.ratio, kind_cfg.partial_ratio)
        self._sources[kind] = source
        self._mtimes[kind] = int(path.stat().st_mtime_ns // 1_000_000) if path.is_file() else 0

    @staticmethod
    def _pick(scores: list[tuple[float, int]], threshold: float) -> int | None:
        """Best-scoring candidate index, or None when the match is too weak/ambiguous."""
        if not scores:
            return None
        ranked = sorted(scores, key=lambda item: item[0], reverse=True)
        top, top_index = ranked[0]
        if top < threshold:
            return None
        if len(ranked) > 1:
            second = ranked[1][0]
            if second >= threshold and top - second < _AMBIGUITY_DELTA:
                return None
        return top_index


def names_info(names_cfg: NamesConfig) -> dict[str, Any]:
    """Describe the effective name snapshot without building a corrector."""
    user_dir = Path(names_cfg.data_dir) if names_cfg.data_dir else default_names_dir()
    return NameCorrector(names_cfg, str(user_dir)).info()


# --- wiki fetch ---------------------------------------------------------------


def fetch_json(url: str, timeout: float = 20.0) -> Any:
    """Fetch a JSON document from ``url`` (the wiki API by default)."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _category_members(fetch: Callable[[str], Any], title: str, kind: str = "page") -> list[dict[str, Any]]:
    """All members of ``title``, following MediaWiki continuation tokens."""
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": title,
        "cmlimit": str(_MEMBER_LIMIT),
        "cmtype": kind,
    }
    members: list[dict[str, Any]] = []
    while True:
        data = fetch(_API_URL + "?" + urllib.parse.urlencode(params))
        members.extend(data.get("query", {}).get("categorymembers", []))
        continuation = data.get("continue")
        if not continuation:
            break
        params.update(continuation)
    return members


def _pages(fetch: Callable[[str], Any], category: str) -> set[str]:
    """All article titles directly in ``category``."""
    return {
        member["title"]
        for member in _category_members(fetch, f"Category:{category}")
        if member.get("ns") == 0
    }


def _subcats(fetch: Callable[[str], Any], category: str) -> list[str]:
    """All subcategory titles of ``category`` (without the ``Category:`` prefix)."""
    return [
        member["title"].removeprefix("Category:")
        for member in _category_members(fetch, f"Category:{category}", kind="subcat")
    ]


def _area_titles(fetch: Callable[[str], Any]) -> list[str]:
    """Zone/area names encoded as ``Category:<area> Creatures`` subcategories."""
    return [
        title[: -len(" Creatures")]
        for title in _subcats(fetch, _AREA_CATEGORY)
        if title.endswith(" Creatures")
    ]


def _clean_monster(title: str) -> str:
    return _TRAILING_PAREN_RE.sub("", title).strip()


def fetch_wiki_names(fetch: Callable[[str], Any] | None = None) -> tuple[list[str], list[str]]:
    """Fetch canonical (zones, monsters) names from the Project Gorgon wiki."""
    if fetch is None:
        fetch = fetch_json

    zones: set[str] = set()
    for category in _ZONE_CATEGORIES:
        zones.update(_pages(fetch, category) - _SKIP_PAGES)

    areas = _area_titles(fetch)
    zones.update(areas)

    monster_categories = [
        f"{area} Creatures" for area in areas
    ] + _subcats(fetch, _TYPE_CATEGORY) + _subcats(fetch, _EVENT_CATEGORY) + [
        _ANIMAL_HANDLING_CATEGORY,
        _BOSS_CATEGORY,
    ]
    raw_monsters: set[str] = set()
    for category in monster_categories:
        raw_monsters.update(_pages(fetch, category))

    monsters = {_clean_monster(title) for title in raw_monsters - _SKIP_PAGES}
    return sorted(zones), sorted(monsters)


def update_names_files(out_dir: Path | str, fetch: Callable[[str], Any] | None = None) -> dict[str, Any]:
    """Fetch current wiki names and write them atomically under ``out_dir``."""
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    zones, monsters = fetch_wiki_names(fetch)
    for kind, names in (("zones", zones), ("monsters", monsters)):
        _atomic_write(dest / _FILES[kind], names)
    return {"zones": len(zones), "monsters": len(monsters), "path": str(dest)}


def _atomic_write(path: Path, names: list[str]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(f"{name}\n" for name in names), encoding="utf-8")
    os.replace(tmp, path)