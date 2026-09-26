"""Tests for the bundled item/zone catalogs and their identity helpers."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from gorgon_tracker import catalog, itemdb, names


def test_bundled_item_catalog_maps_known_slugs() -> None:
    cat = catalog.load_item_catalog()
    assert cat.version == "486"
    assert cat.display_for("ArmorPatchKit3") == "Good Armor Patch Kit"
    assert cat.display_for("FlowerSeeds1") == "Bluebell Seeds"
    assert cat.display_for("EmptyBottle") == "Empty Bottle"
    assert cat.display_for("Skin3") == "Crude Animal Skin"


def test_bundled_item_catalog_unknown_slug_returns_none() -> None:
    cat = catalog.load_item_catalog()
    assert cat.display_for("DefinitelyNotAnItem123") is None


def test_infer_display_uses_catalog_before_heuristic() -> None:
    # Authoritative: catalog name (includes the quality prefix) beats CamelCase splitting.
    assert itemdb.infer_display("ArmorPatchKit3") == "Good Armor Patch Kit"
    assert itemdb.infer_display("PorkShoulder") == "Pork Shoulder"
    # Fallback: unknown slugs fall back to the inflation heuristic.
    assert itemdb.infer_display("GoblinHorsebeater") == "Goblin Horsebeater"
    # Chat display names pass through untouched.
    assert itemdb.infer_display("Pork Shoulder") == "Pork Shoulder"


def test_bundled_zone_catalog_maps_area_ids() -> None:
    zc = catalog.load_zone_catalog()
    assert zc.name_for_id("AreaEltibule") == "Eltibule"
    assert zc.name_for_id("AreaSerbule2") == "Serbule Hills"
    assert zc.name_for_id("AreaDoesNotExist") is None


def test_zone_aliases_map_short_names_to_canonical() -> None:
    aliases = catalog.load_zone_catalog().aliases()
    assert aliases["anagoge"] == "Anagoge Island"
    assert aliases["gazluk"] == "Gazluk Plateau"
    # No-op aliases (short == full after normalization) are dropped.
    assert "serbule" not in aliases


def test_user_catalog_overrides_bundled(tmp_path: Path) -> None:
    snapshot = {
        "version": "777",
        "items": [["FlowerSeeds1", "Custom Seed Name", 1, 1, ["Custom"], 42]],
    }
    (tmp_path / "items.json").write_text(json.dumps(snapshot), encoding="utf-8")
    cat = catalog.load_item_catalog(str(tmp_path))
    assert cat.version == "777"
    assert cat.display_for("FlowerSeeds1") == "Custom Seed Name"
    # Bundled areas still fall back when the user dir only holds items.
    assert catalog.load_zone_catalog(str(tmp_path)).name_for_id("AreaSerbule") == "Serbule"


def test_item_seed_rows_shape_and_count() -> None:
    rows = catalog.item_seed_rows()
    assert len(rows) == 11048
    row = next(r for r in rows if r[0] == "ArmorPatchKit" and r[1] == "3")
    assert row[2] == "Good Armor Patch Kit"
    assert row[7] == "486"  # data version
    # Uncoded slugs are seeded with an empty code so full-name lookups work.
    uncoded = next(r for r in rows if r[0] == "EmptyBottle" and r[1] == "")
    assert uncoded[2] == "Empty Bottle"


def test_names_corrector_resolves_zone_alias() -> None:
    from gorgon_tracker.config import NamesConfig

    corrector = names.NameCorrector(
        NamesConfig(),
        aliases={"zones": catalog.load_zone_catalog().aliases()},
    )
    assert corrector.correct("Anagoge", "zones") == "Anagoge Island"
    assert corrector.correct("Gazluk", "zones") == "Gazluk Plateau"
    # Alias rewriting applies to the zones kind only, not monster reads.
    assert corrector.correct("Giant Rat", "monsters") == "Giant Rat"


_SNAPSHOT_ITEMS = {
    "item_1": {
        "InternalName": "ArmorPatchKit3",
        "Name": "Good Armor Patch Kit",
        "Value": 5,
        "MaxStackSize": 100,
        "Keywords": ["ConsumableKit"],
        "IconId": 1,
    }
}
_SNAPSHOT_AREAS = {
    "AreaTest": {
        "FriendlyName": "Test Area",
        "ShortFriendlyName": "Test",
        "AdjacentAreas": ["AreaSerbule"],
    }
}


def _fake_cdn(url: str) -> str | dict:
    query = urllib.parse.urlparse(url)
    if query.path == "/fileversion.txt" or url == catalog._VERSION_URL:
        return "777"
    version = query.path.split("/")[1]  # v777/data/items.json
    assert version == "v777"
    filename = query.path.split("/")[-1]
    if filename == "items.json":
        return _SNAPSHOT_ITEMS
    if filename == "areas.json":
        return _SNAPSHOT_AREAS
    raise AssertionError(f"unexpected fetch: {url}")


def test_update_catalog_files_writes_compact_snapshots(tmp_path: Path) -> None:
    stats = catalog.update_catalog_files(tmp_path, fetch=_fake_cdn)
    assert stats == {"version": "777", "items": 1, "areas": 1, "path": str(tmp_path)}
    assert (tmp_path / "version.txt").read_text(encoding="utf-8").strip() == "777"

    cat = catalog.load_item_catalog(str(tmp_path))
    assert cat.display_for("ArmorPatchKit3") == "Good Armor Patch Kit"
    zc = catalog.load_zone_catalog(str(tmp_path))
    assert zc.name_for_id("AreaTest") == "Test Area"
    assert zc.by_id["AreaTest"].adjacent == ("AreaSerbule",)
    assert not any(tmp_path.glob("*.tmp"))