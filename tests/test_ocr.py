import threading
import time

import pytest

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.correlator import TargetSighting, ZoneChange
from gorgon_tracker.parsers import ocr
from gorgon_tracker.sources import ocr as ocr_sources


@pytest.fixture(autouse=True)
def _screen_env(monkeypatch) -> None:
    """Pin a deterministic capture environment and reset the shared cache."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("GORGON_TRACKER_SCREEN_METHOD", raising=False)
    monkeypatch.setenv("GORGON_TRACKER_SCREEN_TTL", "1.0")
    ocr._FULL_SCREEN_CACHE.image = None
    ocr._FULL_SCREEN_CACHE.origin = None
    ocr._FULL_SCREEN_CACHE.ts = 0.0


def test_sanitize_text_drops_non_alpha() -> None:
    assert ocr.sanitize_text("  Ilmari   Island \n [Dock] 12:34 ") == "Ilmari Island Dock"


def test_grayscale_mode(monkeypatch) -> None:
    from PIL import Image

    img = Image.new("RGB", (4, 4), (200, 100, 50))
    gray = ocr.grayscale(img)
    assert gray.mode == "L"


class _FakeMss:
    monitors = [{"left": 0, "top": 0, "width": 2, "height": 2}]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def grab(self, monitor: dict) -> object:
        class FakeShot:
            size = (monitor["width"], monitor["height"])
            bgra = b"\x00\x00\x00\xff" * monitor["width"] * monitor["height"]

        return FakeShot()


def test_capture_text_with_mocks(monkeypatch) -> None:
    cfg = TrackerConfig()

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
    fake = _FakeMss()
    fake.monitors = [
        {"left": 0, "top": 0, "width": 3840, "height": 1080},
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
    ]

    def fake_mss():
        return fake

    monkeypatch.setattr(ocr, "mss", type("M", (), {"mss": staticmethod(fake_mss)}))
    assert ocr.list_monitors() == fake.monitors


# --- capture backend selection -------------------------------------------------


def test_background_method_defaults_to_mss(monkeypatch) -> None:
    monkeypatch.setattr(ocr, "sys", type("S", (), {"platform": "linux"}))
    assert ocr._background_method() == "mss"


def test_background_method_wayland_uses_portal(monkeypatch) -> None:
    monkeypatch.setattr(ocr, "sys", type("S", (), {"platform": "linux"}))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert ocr._background_method() == "portal"


def test_background_method_forced_and_unknown(monkeypatch) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("GORGON_TRACKER_SCREEN_METHOD", "mss")
    assert ocr._background_method() == "mss"

    monkeypatch.setenv("GORGON_TRACKER_SCREEN_METHOD", "kms")
    with pytest.raises(ocr.ScreenCaptureError):
        ocr._background_method()


# --- full-screen grab + crop ---------------------------------------------------


def test_grab_region_crops_and_caches(monkeypatch) -> None:
    from PIL import Image

    calls = {"n": 0}
    full = Image.new("RGB", (100, 80), (10, 20, 30))

    def fake_full():
        calls["n"] += 1
        return full, (10, 5)

    monkeypatch.setattr(ocr, "_mss_grab_full", fake_full)
    monkeypatch.setattr(ocr, "_background_method", lambda: "mss")

    got = ocr.grab_region([20, 15, 30, 20])
    assert got.size == (30, 20)
    assert calls["n"] == 1
    assert ocr.grab_region([0, 0, 5, 5]).size == (5, 5)  # served by the cache
    assert calls["n"] == 1


def test_grab_region_ttl_refreshes(monkeypatch) -> None:
    from PIL import Image

    calls = {"n": 0}
    full = Image.new("RGB", (100, 80), (10, 20, 30))

    def fake_full():
        calls["n"] += 1
        return full, (0, 0)

    monkeypatch.setattr(ocr, "_mss_grab_full", fake_full)
    monkeypatch.setattr(ocr, "_background_method", lambda: "mss")
    monkeypatch.setenv("GORGON_TRACKER_SCREEN_TTL", "0")

    ocr.grab_region([0, 0, 4, 4])
    ocr.grab_region([0, 0, 4, 4])
    assert calls["n"] == 2


def test_crop_full_pads_out_of_bounds(monkeypatch) -> None:
    from PIL import Image

    full = Image.new("RGB", (10, 10), (255, 0, 0))

    inside = ocr._crop_full(full, (0, 0), [2, 2, 4, 4])
    assert inside.size == (4, 4)

    partial = ocr._crop_full(full, (0, 0), [-3, -3, 6, 6])
    assert partial.size == (6, 6)
    assert partial.getpixel((0, 0)) == (0, 0, 0)  # out-of-desktop padding
    assert partial.getpixel((3, 3)) == (255, 0, 0)  # visible desktop pixels

    far = ocr._crop_full(full, (0, 0), [50, 50, 4, 4])
    assert far.size == (4, 4)
    assert far.getpixel((0, 0)) == (0, 0, 0)


def test_crop_full_negative_origin(monkeypatch) -> None:
    from PIL import Image

    full = Image.new("RGB", (10, 10), (255, 0, 0))
    # Desktop origin at (-5, -5): desktop x=0 maps to image column 5.
    got = ocr._crop_full(full, (-5, -5), [0, 0, 3, 3])
    assert got.size == (3, 3)
    assert got.getpixel((0, 0)) == (255, 0, 0)


def test_capture_failure_surfaced(monkeypatch) -> None:
    monkeypatch.setattr(ocr, "_background_method", lambda: "portal")

    def boom():
        raise ocr.ScreenCaptureError("no display")

    monkeypatch.setattr(ocr, "_portal_grab_full", boom)
    with pytest.raises(ocr.ScreenCaptureError, match="no display"):
        ocr.grab_region([0, 0, 4, 4])


# --- portal screenshot parsing -------------------------------------------------


def _install_fake_jeepney(monkeypatch, conn) -> None:
    import sys
    import types

    class FakeMessageType:
        method_return = "method_return"
        signal = "signal"

    class FakeHeaderFields:
        member = "member"
        path = "path"

    class FakeDBusErrorResponse(Exception):
        pass

    jeepney = types.ModuleType("jeepney")
    jeepney.MessageType = FakeMessageType
    jeepney.HeaderFields = FakeHeaderFields
    jeepney.DBusErrorResponse = FakeDBusErrorResponse
    jeepney.DBusAddress = lambda *a, **k: a
    jeepney.new_method_call = lambda *a, **k: ("call", a)

    io_blocking = types.ModuleType("jeepney.io.blocking")
    io_blocking.open_dbus_connection = lambda **k: conn

    monkeypatch.setitem(sys.modules, "jeepney", jeepney)
    monkeypatch.setitem(sys.modules, "jeepney.io", types.ModuleType("jeepney.io"))
    monkeypatch.setitem(sys.modules, "jeepney.io.blocking", io_blocking)


class _FakeConn:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False

    def send_message(self, msg):
        self.sent.append(msg)

    def receive(self, timeout=None):
        if not self.replies:
            raise TimeoutError
        return self.replies.pop(0)

    def close(self):
        self.closed = True


def _portal_msgs(tmp_path, token_suffix="gorgon_1234000", status=0):
    from PIL import Image

    path = tmp_path / "shot.png"
    Image.new("RGB", (8, 6), (40, 80, 120)).save(path)

    class _Header:
        def __init__(self, message_type, fields=None):
            self.message_type = message_type
            self.fields = fields or {}

    class _Msg:
        def __init__(self, message_type, body, fields=None):
            self.header = _Header(message_type, fields)
            self.body = body

    request_path = f"/org/freedesktop/portal/desktop/request/1_256/{token_suffix}"
    reply = _Msg(
        "method_return", (request_path,), {}
    )
    response = _Msg(
        "signal",
        (status, {"uri": ("s", f"file://{path}")}),
        {"member": "Response", "path": request_path},
    )
    return reply, response, path


def test_portal_grab_parses_response(tmp_path, monkeypatch) -> None:
    reply, response, path = _portal_msgs(tmp_path)
    conn = _FakeConn([reply, response])

    monkeypatch.setattr(ocr, "mss", type("M", (), {"mss": staticmethod(lambda: _FakeMss())}))
    monkeypatch.setattr(ocr.time, "time", lambda: 1234.0)

    def fake_unlink(p):
        assert p == str(path)

    monkeypatch.setattr(ocr.os, "unlink", fake_unlink)
    _install_fake_jeepney(monkeypatch, conn)

    image, origin = ocr._portal_grab_full()
    assert image.size == (8, 6)
    assert image.mode == "RGB"
    assert origin == (0, 0)
    assert conn.closed


def test_portal_grab_reports_status(tmp_path, monkeypatch) -> None:
    reply, response, _path = _portal_msgs(tmp_path, status=1)
    conn = _FakeConn([reply, response])

    monkeypatch.setattr(ocr, "mss", type("M", (), {"mss": staticmethod(lambda: _FakeMss())}))
    monkeypatch.setattr(ocr.time, "time", lambda: 1234.0)
    monkeypatch.setattr(ocr.os, "unlink", lambda p: None)
    _install_fake_jeepney(monkeypatch, conn)

    with pytest.raises(ocr.ScreenCaptureError, match="status 1"):
        ocr._portal_grab_full()


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


def test_produce_skips_screen_capture_errors(monkeypatch) -> None:
    cfg = TrackerConfig()
    cfg.ocr.targets.interval_s = 0.02

    def fake_capture(cfg_, region):
        raise ocr.ScreenCaptureError("no display")

    monkeypatch.setattr(ocr_sources, "capture_text", fake_capture)
    collected = []
    stop = threading.Event()

    def runner():
        ocr_sources.produce_region(
            cfg, cfg.ocr.targets, lambda t, n: TargetSighting(time_ms=n, name=t), collected.append, stop
        )

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    time.sleep(0.15)
    stop.set()
    thread.join(timeout=3)
    assert collected == []


def test_parse_region() -> None:
    from gorgon_tracker.calibrate import parse_region

    assert parse_region("1680,0,180,50") == [1680, 0, 180, 50]