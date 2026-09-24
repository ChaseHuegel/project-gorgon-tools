"""Tests for canonical name lists and OCR name correction."""

from __future__ import annotations

import urllib.parse
from pathlib import Path

import pytest

from gorgon_tracker import names
from gorgon_tracker.config import NamesConfig


@pytest.fixture
def tables(tmp_path: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A small canonical dataset in a temp user data dir."""
    zone_file = tmp_path / "zones.txt"
    monster_file = tmp_path / "monsters.txt"
    zone_file.write_text(
        "Old Graveyard\nIlmari\nRed Wing Casino\nThe Wintertide\nMysterious Locale\nErrruka's Cave\n# a comment\n\n",
        encoding="utf-8",
    )
    monster_file.write_text("Giant Bat\nGiant Rat\nWolf\nTiger\nPig\nSkeleton Archer\n", encoding="utf-8")
    return zone_file, monster_file


def _corrector(data_dir: Path, enabled: bool = True) -> names.NameCorrector:
    cfg = NamesConfig(enabled=enabled)
    return names.NameCorrector(cfg, str(data_dir))


# --- normalization ----------------------------------------------------------------


def test_normalize_drops_punctuation_and_case() -> None:
    assert names._normalize("Errruka's Cave") == "errrukas cave"
    assert names._normalize("  Red   Wing Casino ") == "red wing casino"
    assert names._normalize("\"Sewer Kings\" Loiterer") == "sewer kings loiterer"


# --- correction -------------------------------------------------------------------


def test_correct_exact_match_restores_canonical(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    assert corrector.correct("errrukas cave", "zones") == "Errruka's Cave"
    assert corrector.correct("Errruka's Cave", "zones") == "Errruka's Cave"


def test_correct_single_word_ocr_damage(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    assert corrector.correct("Old Graveryard", "zones") == "Old Graveyard"  # token 95.9 >= 90
    assert corrector.correct("Skeleton Arther", "monsters") == "Skeleton Archer"  # token 93.3 >= 90


def test_correct_merged_words(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    assert corrector.correct("RedWing Casino", "zones") == "Red Wing Casino"


def test_correct_dropped_word_via_partial(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    # OCR dropped the leading "The": partial match recovers the canonical zone.
    assert corrector.correct("Wintertide", "zones") == "The Wintertide"


def test_pick_rejects_ambiguous_and_weak_matches() -> None:
    assert names.NameCorrector._pick([(95.0, 0), (93.0, 1)], 90.0) is None  # within delta 3
    assert names.NameCorrector._pick([(95.0, 0), (91.5, 1)], 90.0) == 0  # clear margin
    assert names.NameCorrector._pick([(89.0, 0)], 90.0) is None  # below threshold
    assert names.NameCorrector._pick([], 90.0) is None


def test_correct_weak_match_left_untouched(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    assert corrector.correct("Tigat", "monsters") == "Tigat"  # token 60 below threshold
    assert corrector.correct("Woll", "monsters") == "Woll"  # token 75 below threshold
    # Partial matches must cover the text nearly entirely: interleaved junk is rejected.
    assert corrector.correct("Mysterious New Zone", "zones") == "Mysterious New Zone"
    assert corrector.correct("Mysterious Floating Fortress", "zones") == "Mysterious Floating Fortress"


def test_correct_clean_read_of_unknown_name_left_untouched(
    tmp_path: Path, tables: tuple[Path, Path]
) -> None:
    corrector = _corrector(tmp_path)
    # 'Giant Bat' normalized to 'giant bat', token 87.5 vs 'Giant Rat' < 90: kept raw.
    assert corrector.correct("Giant Bat", "monsters") == "Giant Bat"
    # Near tie between 'Giant Bat'/'Giant Rat' for a damaged read: kept raw.
    assert corrector.correct("Giant Fat", "monsters") == "Giant Fat"


def test_correct_partial_tail_match(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    # 'Pig' is a real canonical name (wiki disambiguator already stripped).
    assert corrector.correct("Pig", "monsters") == "Pig"


def test_correct_disabled_returns_raw(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path, enabled=False)
    assert corrector.correct("Old Graveryard", "zones") == "Old Graveryard"


# --- user dir precedence + hot reload --------------------------------------------


def test_user_dir_takes_precedence(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    zone_file, _ = tables
    zone_file.write_text("Custom Zone\n", encoding="utf-8")
    corrector = _corrector(tmp_path)
    assert corrector.correct("custom zone", "zones") == "Custom Zone"
    assert corrector.correct("Serbule", "zones") == "Serbule"  # bundled name no longer known
    assert corrector.info()["zones_source"] == "user"


def test_bundled_snapshot_used_without_user_dir(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    corrector = _corrector(tmp_path)
    assert corrector.info()["zones_source"] == "user"
    assert corrector.info()["zones_path"].endswith("zones.txt")


def test_refresh_if_changed_reloads(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    zone_file, _ = tables
    corrector = _corrector(tmp_path)
    assert corrector.correct("Brand New Area", "zones") == "Brand New Area"
    zone_file.write_text("Brand New Area\n", encoding="utf-8")
    assert corrector.correct("Brand New Area", "zones") == "Brand New Area"
    corrector.refresh_if_changed()
    assert corrector.correct("Brand New Area", "zones") == "Brand New Area"
    assert corrector.correct("Brand New Area", "zones") == "Brand New Area"


# --- info -------------------------------------------------------------------------


def test_names_info_shape(tmp_path: Path, tables: tuple[Path, Path]) -> None:
    info = names.names_info(NamesConfig(data_dir=str(tmp_path)))
    assert info["enabled"] is True
    assert info["data_dir"] == str(tmp_path)
    assert info["zones_count"] == 6
    assert info["monsters_count"] == 6
    assert info["zones_source"] == "user"
    assert info["zones_mtime_ms"] is not None


# --- wiki fetch -------------------------------------------------------------------


def _canned_wiki() -> dict[str, list[dict]]:
    return {
        "Category:Zones": [
            {"ns": 0, "title": "Serbule"},
            {"ns": 0, "title": "Zones"},  # meta page, skipped
            {"ns": 0, "title": "Zone Template"},  # meta page, skipped
        ],
        "Category:Dungeons": [
            {"ns": 0, "title": "Kur Tower"},
            {"ns": 0, "title": "Wolf Cave"},
            {"ns": 0, "title": "Dungeons"},  # meta page, skipped
        ],
        "Category:Creatures by Area": [
            {"ns": 14, "title": "Category:Serbule Creatures"},
            {"ns": 14, "title": "Category:Wolf Cave Creatures"},
            {"ns": 14, "title": "Category:Scion Summon"},  # not an area, skipped
        ],
        "Category:Serbule Creatures": [
            {"ns": 0, "title": "Giant Bat"},
            {"ns": 0, "title": "Pig (mob)"},
            {"ns": 14, "title": "Category:Nested Creatures"},  # subcategory, skipped
        ],
        "Category:Wolf Cave Creatures": [
            {"ns": 0, "title": "Giant Bat"},
            {"ns": 0, "title": "Wolf"},
        ],
        "Category:Creatures by Type": [
            {"ns": 14, "title": "Category:Canine"},
        ],
        "Category:Canine": [
            {"ns": 0, "title": "Wolf"},
            {"ns": 0, "title": "Cerberus"},
        ],
        "Category:Creatures by Event": [
            {"ns": 14, "title": "Category:Halloween Creatures"},
        ],
        "Category:Halloween Creatures": [
            {"ns": 0, "title": "Pumpkin Golem"},
        ],
        "Category:Animal Handling Creatures": [
            {"ns": 0, "title": "Giant Bat"},
            {"ns": 0, "title": "Angry Bear"},
        ],
        "Category:Bosses": [
            {"ns": 0, "title": "Angry Bear"},
            {"ns": 0, "title": "Creature Template"},  # meta page, skipped
        ],
    }


def _wiki_fetch(canned: dict[str, list[dict]], paginate: str | None = None):
    """A fake MediaWiki API: returns canned members, optionally splitting one category."""

    def fetch(url: str) -> dict:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        title = query["cmtitle"][0]
        kind = query.get("cmtype", ["page"])[0]
        members = [m for m in canned[title] if m["ns"] == (14 if kind == "subcat" else 0)]
        continuation = query.get("cmcontinue", [None])[0]
        if paginate == title:
            half = len(members) // 2
            if continuation is None:
                return {
                    "query": {"categorymembers": members[:half]},
                    "continue": {"cmcontinue": "token", "continue": "-||"},
                }
            return {"query": {"categorymembers": members[half:]}}
        return {"query": {"categorymembers": members}}

    return fetch


def test_fetch_wiki_names() -> None:
    zones, monsters = names.fetch_wiki_names(_wiki_fetch(_canned_wiki()))
    assert zones == ["Kur Tower", "Serbule", "Wolf Cave"]
    assert monsters == ["Angry Bear", "Cerberus", "Giant Bat", "Pig", "Pumpkin Golem", "Wolf"]


def test_fetch_wiki_names_pagination() -> None:
    canned = _canned_wiki()
    canned["Category:Serbule Creatures"] = [{"ns": 0, "title": f"Creature {i}"} for i in range(10)]
    zones, monsters = names.fetch_wiki_names(_wiki_fetch(canned, paginate="Category:Serbule Creatures"))
    assert zones == ["Kur Tower", "Serbule", "Wolf Cave"]
    base = ["Angry Bear", "Cerberus", "Giant Bat", "Pumpkin Golem", "Wolf"]
    expected = sorted(base + [f"Creature {i}" for i in range(10)])
    assert monsters == expected


def test_update_names_files(tmp_path: Path) -> None:
    stats = names.update_names_files(tmp_path, _wiki_fetch(_canned_wiki()))
    assert stats == {"zones": 3, "monsters": 6, "path": str(tmp_path)}
    assert (tmp_path / "zones.txt").read_text(encoding="utf-8").splitlines() == [
        "Kur Tower",
        "Serbule",
        "Wolf Cave",
    ]
    assert not any(tmp_path.glob("*.tmp"))