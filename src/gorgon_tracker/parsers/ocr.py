"""OCR helpers: screen grab, grayscale preprocess, and tesseract text extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence

import mss
import pytesseract
from PIL import Image

from ..config import TrackerConfig

_SANITIZE_RE = re.compile(r"[^a-zA-Z\s]")


def grayscale(image: Image.Image) -> Image.Image:
    """Convert to luminance using the same weights as the legacy pipeline."""
    return image.convert("L")


def grab_region(region: Sequence[int]) -> Image.Image:
    """Grab the screen region [x, y, width, height] as an RGB image."""
    x, y, width, height = region
    with mss.mss() as monitor:
        shot = monitor.grab({"left": x, "top": y, "width": width, "height": height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def list_monitors() -> list[dict[str, int]]:
    """Return mss monitor bounds; index 0 is the combined virtual screen."""
    with mss.mss() as monitor:
        return [dict(m) for m in monitor.monitors]


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