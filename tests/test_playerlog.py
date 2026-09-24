"""Parser tests for the Unity ``Player.log`` source (synthetic-real fixtures)."""

from __future__ import annotations

from gorgon_tracker.correlator import (
    BuryEvent,
    CorpseSearch,
    InteractionStart,
    LootEvent,
    ZoneChange,
)
from gorgon_tracker.parsers.playerlog import PlayerLogParser

from . import scenario

LOGIN = (
    "[20:00:00] Logged in as character Tester. Time UTC=01/11/2026 20:00:00. "
    "Timezone Offset -01:00:00."
)


def _at(seconds: float) -> int:
    return scenario.at(seconds) - scenario.at(seconds) % 1000


def run(lines: list[str], parser: PlayerLogParser | None = None) -> list[object]:
    parser = parser or PlayerLogParser()
    events: list[object] = []
    for line in lines:
        events.extend(parser.feed(line))
    events.extend(parser.close())
    return events


def _newline(text: str) -> list[str]:
    return text.splitlines()


def test_login_anchors_stamp_to_utc_epoch() -> None:
    events = run([LOGIN, "[20:00:01] LocalPlayer: ProcessAddItem(BatWing(-1), -1, True)"])
    pickups = [e for e in events if isinstance(e, LootEvent)]
    assert pickups[0].time_ms == _at(1.0)


def test_add_item_true_is_pickup_false_is_load() -> None:
    events = run(
        [
            LOGIN,
            "[20:00:01] LocalPlayer: ProcessAddItem(BatWing(-1), -1, True)",
            "[20:00:02] LocalPlayer: ProcessAddItem(RatJaw(-2), -1, False)",
        ]
    )
    pickups = [e for e in events if isinstance(e, LootEvent) and not e.missed]
    assert len(pickups) == 1
    assert pickups[0].item == "BatWing"
    assert pickups[0].instance_id == -1
    assert pickups[0].source_class == "unity"


def test_midnight_rollover_advances_anchor_date() -> None:
    from datetime import UTC, datetime

    events = run(
        [
            "[23:59:58] Logged in as character Tester. Time UTC=01/11/2026 23:59:58. Timezone Offset -01:00:00.",
            "[23:59:58] LocalPlayer: ProcessSetAttributes(1, \"[MAX_HEALTH], [1]\")",
            "[23:59:59] LocalPlayer: ProcessAddItem(BatWing(-1), -1, True)",
            "[00:00:01] LocalPlayer: ProcessAddItem(RatJaw(-2), -1, True)",
        ]
    )
    pickups = sorted((e for e in events if isinstance(e, LootEvent)), key=lambda e: e.time_ms)
    assert pickups[1].time_ms == round(
        datetime(2026, 1, 12, 0, 0, 1, tzinfo=UTC).timestamp() * 1000
    )


def test_corpse_search_parses_monster_killer_and_participants() -> None:
    line = (
        '[20:00:01] LocalPlayer: ProcessTalkScreen(1001, "Search Corpse of Goblin Horsebeater", '
        '"\\n<em>Cause of death:</em> Killed by the living dead\\n<em>Killer:</em> Mennelaia\\n\\n'
        '<h2>Detailed Analysis:</h2>\\nMennelaia: 319 health dmg 273 armor dmg. Aggro (at death): 18.52%\\n'
        'Skeletal Swordsman: 211 health dmg. Aggro (at death): 41.35%\\n\\n'
        'Mennelaia extracted Impressive Goblin Skull from the corpse.", "", [], System.String[], 1, Corpse)'
    )
    events = run([LOGIN, line])
    searches = [e for e in events if isinstance(e, CorpseSearch)]
    assert len(searches) == 1
    search = searches[0]
    assert search.entity_id == 1001
    assert search.monster == "Goblin Horsebeater"
    assert search.killer == "Mennelaia"
    assert search.participants["Mennelaia"]["health"] == 319
    assert search.participants["Mennelaia"]["aggro"] == 18.52
    assert search.participants["Skeletal Swordsman"]["armor"] == 0
    assert search.extractions == {"extracted": "Impressive Goblin Skull"}


def test_corpse_window_marked_missed_when_remove_loot_unmatched() -> None:
    events = run(
        [
            LOGIN,
            "[20:00:01] LocalPlayer: ProcessStartInteraction(1001, 13.5, 0, False, \"\")",
            "[20:00:01] LocalPlayer: ProcessRemoveLoot(-1719916789)",
            '[20:00:01] LocalPlayer: ProcessErrorMessage(InventoryFull, "You need a free inventory slot!")',
            '[20:00:02] LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")',
        ]
    )
    missed = [e for e in events if isinstance(e, LootEvent) and e.missed]
    assert len(missed) == 1
    assert missed[0].instance_id == -1719916789
    assert missed[0].item == "Unknown"
    assert missed[0].entity_id == 1001
    # The bury that ends the window must also be emitted.
    assert any(isinstance(e, BuryEvent) for e in events)
    assert any(isinstance(e, InteractionStart) for e in events)


def test_corpse_window_collected_when_add_item_matches() -> None:
    events = run(
        [
            LOGIN,
            "[20:00:01] LocalPlayer: ProcessStartInteraction(1001, 13.5, 0, False, \"\")",
            "[20:00:02] LocalPlayer: ProcessAddItem(GoblinCallingCard15(-1719916789), -1, True)",
            "[20:00:02] LocalPlayer: ProcessRemoveLoot(-1719916789)",
            '[20:00:03] LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")',
        ]
    )
    pickups = [e for e in events if isinstance(e, LootEvent) and not e.missed]
    assert len(pickups) == 1
    assert pickups[0].instance_id == -1719916789
    assert pickups[0].entity_id == 1001
    assert not any(e for e in events if isinstance(e, LootEvent) and e.missed)


def test_ai_pickup_before_remove_loot_is_still_collected() -> None:
    # The Unity log can report the inventory add before the corpse removal.
    events = run(
        [
            LOGIN,
            "[20:00:01] LocalPlayer: ProcessStartInteraction(1001, 13.5, 0, False, \"\")",
            "[20:00:02] LocalPlayer: ProcessAddItem(GoblinCallingCard15(-1719916789), -1, True)",
            "[20:00:02] LocalPlayer: ProcessRemoveLoot(-1719916789)",
            "[20:00:03] LocalPlayer: ProcessStartInteraction(1002, 13.5, 0, False, \"\")",
        ]
    )
    assert not any(e for e in events if isinstance(e, LootEvent) and e.missed)


def test_coins_and_bury_lines() -> None:
    events = run(
        [
            LOGIN,
            "[20:00:01] LocalPlayer: ProcessStartInteraction(1001, 13.5, 0, False, \"\")",
            '[20:00:02] LocalPlayer: ProcessScreenText(GeneralInfo, "You searched the corpse and found 43 coins.")',
            '[20:00:03] LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")',
        ]
    )
    coins = [e for e in events if isinstance(e, LootEvent) and e.item == "Coins"]
    assert len(coins) == 1
    assert coins[0].amount == 43
    assert any(isinstance(e, BuryEvent) for e in events)


def test_zone_change_from_loading_level() -> None:
    events = run([LOGIN, "[20:00:00] LOADING LEVEL AreaEltibule"])
    zones = [e for e in events if isinstance(e, ZoneChange)]
    assert len(zones) == 1
    assert zones[0].zone == "Eltibule"


def test_noise_and_nonplayer_lines_are_ignored() -> None:
    events = run(
        [
            LOGIN,
            "[20:00:00] Download appearance loop @Base1 is waiting on Appearance",
            "[20:00:00] LoadAssetAsync: eq-staff18. Status=None.",
            'If you absolutely need to use negative scaling you can use the convex MeshCollider.',
            "[20:00:01] New Network State: PickingCharacter -> JoinedArea)",
            "[20:00:02] SomeRandomActor: ProcessAddItem(BatWing(-1), -1, True)",
        ]
    )
    assert events == []