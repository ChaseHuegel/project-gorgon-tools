from gorgon_tracker.parsers import chat

from . import scenario


def _line(seconds: float, item: str | None = None, amount: int = 1) -> str:
    if item is None:
        return f"{scenario.local_wall(seconds)} [Status] You bury the corpse."
    return f"{scenario.local_wall(seconds)} [Status] {item} x{amount} added to inventory."


def test_parse_loot_with_count() -> None:
    event = chat.parse_chat_line(_line(3.5, "Bat Guano", 2))
    assert isinstance(event, chat.LootEvent)
    assert event.item == "Bat Guano"
    assert event.amount == 2
    assert event.time_ms == scenario.at(3.5) - scenario.at(3.5) % 1000  # second resolution


def test_parse_loot_without_count_defaults_one() -> None:
    event = chat.parse_chat_line(f"{scenario.local_wall(4.0)} [Status] Bat Wing added to inventory.")
    assert isinstance(event, chat.LootEvent)
    assert event.amount == 1


def test_parse_bury() -> None:
    event = chat.parse_chat_line(_line(6.0))
    assert isinstance(event, chat.BuryEvent)
    assert event.time_ms == scenario.at(6.0) - scenario.at(6.0) % 1000


def test_nonmatching_lines_ignored() -> None:
    assert chat.parse_chat_line("") is None
    assert chat.parse_chat_line("26-01-11 12:00:00 [Status] You skin the corpse.") is None
    assert chat.parse_chat_line("garbage") is None


def test_parse_chat_lines_skips_noise() -> None:
    events = list(
        chat.parse_chat_lines(
            iter(["noise", _line(9.7, "Wolf Pelt", 2), "more noise", _line(13.0)])
        )
    )
    assert len(events) == 2
    assert isinstance(events[0], chat.LootEvent)
    assert isinstance(events[1], chat.BuryEvent)


def test_four_digit_chat_timestamp() -> None:
    dt = scenario.at(5.0)
    local = __import__("datetime").datetime.fromtimestamp(dt / 1000).strftime("%Y-%m-%d %H:%M:%S")
    event = chat.parse_chat_line(f"{local} [Status] Bone added to inventory.")
    assert isinstance(event, chat.LootEvent)
    assert event.time_ms == dt - dt % 1000