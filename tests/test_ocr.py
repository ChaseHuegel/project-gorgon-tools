import threading
import time

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.correlator import TargetSighting, ZoneChange
from gorgon_tracker.parsers import ocr
from gorgon_tracker.sources import ocr as ocr_sources


def test_sanitize_text_drops_non_alpha() -> None:
    assert ocr.sanitize_text("  Ilmari   Island \n [Dock] 12:34 ") == "Ilmari Island Dock"


def test_grayscale_mode(monkeypatch) -> None:

    from PIL import Image

    img = Image.new("RGB", (4, 4), (200, 100, 50))
    gray = ocr.grayscale(img)
    assert gray.mode == "L"


def test_capture_text_with_mocks(monkeypatch) -> None:

    cfg = TrackerConfig()

    class _FakeMss:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def grab(self, monitor: dict) -> object:
            class FakeShot:
                size = (monitor["width"], monitor["height"])
                bgra = b"\x00\x00\x00\xff" * monitor["width"] * monitor["height"]

            return FakeShot()

    def fake_mss():
        return _FakeMss()

    def fake_ocr_image(image, tesseract_cmd, lang):
        assert tesseract_cmd == "tesseract"
        assert lang == "eng"
        return "Fairy Glen  42\n"

    monkeypatch.setattr(ocr, "mss", type("M", (), {"mss": staticmethod(fake_mss)}))
    monkeypatch.setattr(ocr, "ocr_image", fake_ocr_image)
    assert ocr.capture_text(cfg, [0, 0, 2, 2]) == "Fairy Glen"


def test_raw_capture_text_returns_ocr_raw(monkeypatch) -> None:
    from PIL import Image

    cfg = TrackerConfig()
    monkeypatch.setattr(ocr, "grab_region", lambda region: Image.new("RGB", (2, 2)))
    monkeypatch.setattr(
        ocr, "ocr_image", lambda image, tesseract_cmd, lang: "Elmet  12:34\n"
    )
    assert ocr.raw_capture_text(cfg, [0, 0, 2, 2]) == "Elmet  12:34\n"
    assert ocr.capture_text(cfg, [0, 0, 2, 2]) == "Elmet"


def test_list_monitors_returns_bounds(monkeypatch) -> None:
    class _FakeMss:
        monitors = [
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(ocr, "mss", type("M", (), {"mss": staticmethod(lambda: _FakeMss())}))
    assert ocr.list_monitors() == _FakeMss.monitors


def _emit_sequences(monkeypatch, cfg, producer) -> list:
    """Drive a producer with a scripted sequence of OCR reads."""
    script = ["Ilmari Island", "Ilmari Island", "Elmet", "Elmet"]
    calls = {"index": 0}

    def fake_capture(cfg_, region):
        idx = calls["index"]
        calls["index"] += 1
        return script[idx] if idx < len(script) else ""

    monkeypatch.setattr(ocr, "capture_text", fake_capture)
    monkeypatch.setattr(ocr_sources, "capture_text", fake_capture)

    collected = []
    stop = threading.Event()

    def runner():
        ocr_sources.produce_region(
            cfg, cfg.ocr.targets, lambda t, n: TargetSighting(time_ms=n, name=t), collected.append, stop
        )

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    time.sleep(0.35)
    stop.set()
    thread.join(timeout=3)
    return [(type(e).__name__, e.name) for e in collected]


def test_produce_targets_change_detection(monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.ocr.targets.interval_s = 0.02
    seen = _emit_sequences(monkeypatch, cfg, None)
    # Change detection only: 'Ilmari Island' once, 'Elmet' once, duplicates skipped.
    assert seen == [("TargetSighting", "Ilmari Island"), ("TargetSighting", "Elmet")]


def test_produce_zones_change_and_heartbeat(monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.ocr.zones.interval_s = 0.02
    cfg.ocr.zones.heartbeat_s = 0.1

    script = ["Old Graveyard", "Old Graveyard"]
    calls = {"index": 0}

    def fake_capture(cfg_, region):
        idx = calls["index"]
        index = min(idx, len(script) - 1) if idx < len(script) else len(script) - 1
        calls["index"] += 1
        return script[index]

    monkeypatch.setattr(ocr_sources, "capture_text", fake_capture)
    collected = []
    stop = threading.Event()

    def runner():
        ocr_sources.produce_zones(cfg, collected.append, stop)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    time.sleep(0.45)
    stop.set()
    thread.join(timeout=3)

    zones = [e for e in collected if isinstance(e, ZoneChange)]
    assert zones  # at least the initial change
    # Heartbeat re-persists the same zone after heartbeat_s elapses.
    name = zones[0].zone
    assert sum(1 for z in zones if z.zone == name) >= 2


def test_parse_region() -> None:
    from gorgon_tracker.calibrate import parse_region

    assert parse_region("1680,0,180,50") == [1680, 0, 180, 50]