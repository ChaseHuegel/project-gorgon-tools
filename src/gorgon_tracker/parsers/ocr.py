"""OCR helpers: screen grab, grayscale preprocess, and tesseract text extraction."""

from __future__ import annotations

import contextlib
import os
import re
import sys
import threading
import time
import urllib.parse
from collections.abc import Sequence
from typing import Any

import mss
import pytesseract
from PIL import Image

from ..config import TrackerConfig

_SANITIZE_RE = re.compile(r"[^a-zA-Z\s]")

# How long a full-screen grab is reused before a fresh capture is taken. Short
# enough that OCR never falls too far behind, long enough that a single capture
# serves every consumer (zones, targets, calibration UI).
_DEFAULT_SCREEN_TTL_S = 1.0


class _FullScreenCache:
    def __init__(self) -> None:
        self.image: Image.Image | None = None
        self.origin: tuple[int, int] | None = None
        self.ts: float = 0.0


_FULL_SCREEN_CACHE = _FullScreenCache()
_CACHE_LOCK = threading.Lock()


class ScreenCaptureError(RuntimeError):
    """Raised when no screen-capture backend can produce an image."""


def grayscale(image: Image.Image) -> Image.Image:
    """Convert to luminance using the same weights as the legacy pipeline."""
    return image.convert("L")


def list_monitors() -> list[dict[str, int]]:
    """Return mss monitor bounds; index 0 is the combined virtual screen."""
    with mss.mss() as monitor:
        return [dict(m) for m in monitor.monitors]


def grab_region(region: Sequence[int]) -> Image.Image:
    """Grab the screen region [x, y, width, height] as an RGB image.

    The full display is captured (from the backend best suited to the current
    session) and cropped, so regions are expressed in absolute screen
    coordinates independent of the capture path.
    """
    image, (origin_x, origin_y) = _get_full_screen()
    return _crop_full(image, (origin_x, origin_y), region)


def _background_method() -> str:
    """Pick the capture backend for this environment unless overridden."""
    method = os.environ.get("GORGON_TRACKER_SCREEN_METHOD", "auto").strip().lower()
    if method in ("mss", "portal"):
        return method
    if method != "auto":
        raise ScreenCaptureError(f"unknown GORGON_TRACKER_SCREEN_METHOD: {method!r}")
    # mss reads the X server; under Wayland that only reaches XWayland and
    # returns black frames, so route to the desktop portal instead.
    if sys.platform.startswith("linux") and os.environ.get("WAYLAND_DISPLAY"):
        return "portal"
    return "mss"


def _get_full_screen() -> tuple[Image.Image, tuple[int, int]]:
    """Return the latest full-display grab plus its top-left screen origin.

    Grabber and consumers share a single cached frame; a refresh happens at
    most every ``GORGON_TRACKER_SCREEN_TTL`` seconds (default 1.0).
    """
    ttl = float(os.environ.get("GORGON_TRACKER_SCREEN_TTL", _DEFAULT_SCREEN_TTL_S))
    with _CACHE_LOCK:
        now = time.monotonic()
        cached = _FULL_SCREEN_CACHE
        if cached.image is None or now - cached.ts >= ttl:
            method = _background_method()
            if method == "portal":
                cached.image, cached.origin = _portal_grab_full()
            else:
                cached.image, cached.origin = _mss_grab_full()
            cached.ts = now
        assert cached.image is not None and cached.origin is not None
        return cached.image, cached.origin


def _mss_grab_full() -> tuple[Image.Image, tuple[int, int]]:
    """Capture the combined virtual screen via mss (X11/Windows/macOS)."""
    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            origin = (sct.monitors[0]["left"], sct.monitors[0]["top"])
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX"), origin
    except Exception as exc:  # noqa: BLE001 - mss raises several display-specific types
        raise ScreenCaptureError(f"mss screen capture failed: {exc}") from exc


def _portal_grab_full() -> tuple[Image.Image, tuple[int, int]]:
    """Capture the full screen through the XDG desktop portal (Wayland).

    jeepney is imported lazily so non-Linux installs never need a DBus stack.
    """
    try:
        from jeepney import (  # type: ignore[import-untyped]
            DBusAddress,
            DBusErrorResponse,
            new_method_call,
        )
        from jeepney.io.blocking import open_dbus_connection  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on install environment
        raise ScreenCaptureError("jeepney is required for Wayland screen capture") from exc

    address = DBusAddress(
        "/org/freedesktop/portal/desktop",
        bus_name="org.freedesktop.portal.Desktop",
        interface="org.freedesktop.portal.Screenshot",
    )
    token = f"gorgon_{int(time.time() * 1000)}"
    options = {
        "handle_token": ("s", token),
        "interactive": ("b", False),
        "modal": ("b", False),
    }
    conn = None
    try:
        conn = open_dbus_connection(bus="SESSION")
        conn.send_message(new_method_call(address, "Screenshot", "sa{sv}", ("", options)))
        _wait_for_request(conn, token, timeout=10.0)
        uri, status = _wait_for_response(conn, token, timeout=10.0)
    except ScreenCaptureError:
        raise
    except DBusErrorResponse as exc:
        raise ScreenCaptureError(f"desktop portal screenshot failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - jeepney/portal errors are surfaced verbatim
        raise ScreenCaptureError(f"desktop portal screenshot failed: {exc}") from exc
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()

    if status != 0:
        raise ScreenCaptureError(f"desktop portal screenshot returned status {status}")

    path = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    try:
        with Image.open(path) as fh:
            image = fh.convert("RGB")
    except Exception as exc:  # noqa: BLE001
        raise ScreenCaptureError(f"could not read portal screenshot at {path}: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)

    return image, _desktop_origin()


def _desktop_origin() -> tuple[int, int]:
    """Top-left of the virtual desktop, matching mss absolute coordinates."""
    with mss.mss() as sct:
        top = sct.monitors[0]
        return (top["left"], top["top"])


def _wait_for_request(conn: Any, token: str, timeout: float) -> None:
    """Consume the Screenshot method reply carrying this request's object path."""
    from jeepney import MessageType

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = conn.receive(timeout=deadline - time.monotonic())
        except TimeoutError:
            break
        if (
            msg.header.message_type == MessageType.method_return
            and str(msg.body[0]).endswith(token)
        ):
            return
    raise ScreenCaptureError("timed out waiting for portal screenshot request")


def _wait_for_response(conn: Any, token: str, timeout: float) -> tuple[str, int]:
    """Wait for the portal's async Response signal and return (uri, status)."""
    from jeepney import HeaderFields, MessageType

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = conn.receive(timeout=deadline - time.monotonic())
        except TimeoutError:
            break
        if (
            msg.header.message_type == MessageType.signal
            and msg.header.fields.get(HeaderFields.member) == "Response"
            and str(msg.header.fields.get(HeaderFields.path, "")).endswith(token)
        ):
            status = int(msg.body[0])
            results = msg.body[1] or {}
            uri = str(results["uri"][1]) if "uri" in results else ""
            return uri, status
    raise ScreenCaptureError("timed out waiting for portal screenshot")


def _crop_full(
    image: Image.Image, origin: tuple[int, int], region: Sequence[int]
) -> Image.Image:
    """Crop ``region`` out of a full-desktop grab, padding out-of-bounds black."""
    x, y, width, height = (int(v) for v in region)
    ox, oy = origin
    x0, y0 = x - ox, y - oy
    img_w, img_h = image.size
    if width <= 0 or height <= 0:
        return Image.new("RGB", (width, height), (0, 0, 0))
    left = max(0, x0)
    top = max(0, y0)
    right = min(img_w, x0 + width)
    bottom = min(img_h, y0 + height)
    if left >= right or top >= bottom:
        return Image.new("RGB", (width, height), (0, 0, 0))
    crop = image.crop((left, top, right, bottom))
    if crop.size == (width, height):
        return crop
    canvas = Image.new("RGB", (width, height), (0, 0, 0))
    canvas.paste(crop, (max(0, -x0), max(0, -y0)))
    return canvas


def ocr_image(image: Image.Image, tesseract_cmd: str, lang: str) -> str:
    """Run tesseract over a (preprocessed) image and return raw text."""
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    return "".join(pytesseract.image_to_string(image, lang=lang))


def sanitize_text(text: str) -> str:
    """Normalize whitespace and drop non-alpha characters (matches legacy output)."""
    return _SANITIZE_RE.sub("", " ".join(text.split())).strip()


def capture_text(cfg: TrackerConfig, region: Sequence[int]) -> str:
    """Grab + preprocess + OCR a screen region into clean text."""
    return sanitize_text(raw_capture_text(cfg, region))


def raw_capture_text(cfg: TrackerConfig, region: Sequence[int]) -> str:
    """Grab + preprocess + OCR a screen region, returning raw tesseract output."""
    return ocr_image(grayscale(grab_region(region)), cfg.ocr.tesseract_path, cfg.ocr.lang)