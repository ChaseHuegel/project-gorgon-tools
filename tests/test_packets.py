import json

from gorgon_tracker.parsers import packets

from . import scenario


def _payload(text: str) -> str:
    return scenario.hexify(text)


def test_hex_roundtrip() -> None:
    assert packets.hex_payload_to_text(_payload("Search Corpse of Giant Bat")) == "Search Corpse of Giant Bat"


def test_clean_ascii_drops_non_printable() -> None:
    text = "Search Corpse of Rat\n\x00\x01"
    assert packets.clean_ascii(text) == "Search Corpse of Rat\n"


def test_decode_corpse_search_flags() -> None:
    search = packets.decode_corpse_search(
        _payload("Search Corpse of Giant Bat\nSkin Corpse\nButcher Corpse\nExtract Skull")
    )
    assert search is not None
    assert search.monster == "Giant Bat"
    assert search.can_skin and search.can_butcher and search.can_extract


def test_decode_strips_menu_words_from_name() -> None:
    search = packets.decode_corpse_search(_payload("Search Corpse of Autopsy Giant Bat\nSkin Corpse"))
    assert search is not None
    assert search.monster == "Giant Bat"
    assert search.can_skin


def test_decode_ignores_no_permission() -> None:
    text = "Search Corpse of Troll\nYou do not have permission to loot this corpse."
    assert packets.decode_corpse_search(_payload(text)) is None


def test_decode_ignores_non_search() -> None:
    assert packets.decode_corpse_search(_payload("Hello world")) is None


def test_frame_epoch_and_window() -> None:
    doc = [
        scenario.frame_json(2.0, "Search Corpse of Giant Bat\nSkin Corpse\n"),
        scenario.frame_json(5.5, "Search Corpse of Dire Wolf\n"),
    ]
    parsed = packets.parse_capture_doc(doc)
    assert parsed.start_ms == scenario.at(2.0)
    assert parsed.end_ms == scenario.at(5.5)
    assert [e.monster for e in parsed.events] == ["Giant Bat", "Dire Wolf"]
    assert parsed.events[0].time_ms == scenario.at(2.0)


def test_frame_time_to_ms_with_timezone_suffix() -> None:
    local_dt = __import__("datetime").datetime.fromtimestamp(scenario.at(4.0) / 1000)
    display = local_dt.strftime("%b %d, %Y %H:%M:%S.%f") + "000 Eastern Standard Time"
    assert packets.frame_time_to_ms(display) == scenario.at(4.0)


def test_load_json_doc_and_window_defaults(tmp_path) -> None:
    path = tmp_path / "cap.json"
    path.write_text(json.dumps([scenario.frame_json(3.0, "Search Corpse of Rat\n")]))
    doc = packets.parse_capture_doc(packets.load_json_doc(path))
    assert doc.events[0].monster == "Rat"
    assert doc.start_ms == doc.end_ms == scenario.at(3.0)