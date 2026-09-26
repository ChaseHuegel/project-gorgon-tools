from datetime import datetime

from gorgon_tracker.timeutil import iso_to_ms, ms_to_iso


def test_iso_to_ms_us_formats():
    cases = {
        "1/24/2026 5:49:21 PM": datetime(2026, 1, 24, 17, 49, 21),
        "1/24/2026 17:49:21": datetime(2026, 1, 24, 17, 49, 21),
        "1/24/2026": datetime(2026, 1, 24),
        "12/5/2026 12:00:00 AM": datetime(2026, 12, 5, 0, 0, 0),
        "12/5/2026 12:00:00 PM": datetime(2026, 12, 5, 12, 0, 0),
    }
    for raw, expected in cases.items():
        parsed = datetime.fromtimestamp(iso_to_ms(raw) / 1000).replace(tzinfo=None)
        assert parsed == expected, f"{raw!r} -> {parsed} != {expected}"


def test_iso_to_ms_epoch_ms():
    ms = 1768161600000
    assert iso_to_ms(f"/Date({ms})/") == ms


def test_iso_to_ms_iso_roundtrip():
    ms = iso_to_ms("2026-01-24T17:49:21")
    assert iso_to_ms(ms_to_iso(ms)) == ms


def test_iso_to_ms_epoch():
    assert ms_to_iso(0).startswith("1970-01-01T00:00:00")