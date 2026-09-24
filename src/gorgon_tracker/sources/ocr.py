"""Screen-OCR producers: zone names and target names, with change detection."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TypeVar

from ..config import OcrRegionConfig, TrackerConfig
from ..correlator import TargetSighting, ZoneChange
from ..parsers.ocr import ScreenCaptureError, capture_text
from ..timeutil import utc_now_ms

E = TypeVar("E")
logger = logging.getLogger("gorgon_tracker.sources.ocr")


def produce_region(
    cfg: TrackerConfig,
    region_cfg: OcrRegionConfig,
    make_event: Callable[[str, int], E],
    emit: Callable[[E], None],
    stop_event: threading.Event,
) -> None:
    """Poll ``region_cfg`` and emit events on change (plus an optional heartbeat).

    Empty OCR reads are skipped (matches the legacy "no text found" path).
    """
    heartbeat_ms = int(region_cfg.heartbeat_s * 1000) if region_cfg.heartbeat_s else None
    last_text: str | None = None
    last_emit_ms: int | None = None

    while not stop_event.wait(region_cfg.interval_s):
        try:
            text = capture_text(cfg, region_cfg.region)
        except ScreenCaptureError:
            logger.warning("screen capture failed; skipping OCR read", exc_info=True)
            continue
        except Exception:  # OCR/tesseract hiccups should not kill capture
            text = ""
        if not text:
            continue
        now = utc_now_ms()
        if text != last_text:
            emit(make_event(text, now))
            last_text = text
            last_emit_ms = now
        elif heartbeat_ms is not None and (
            last_emit_ms is None or now - last_emit_ms >= heartbeat_ms
        ):
            emit(make_event(text, now))
            last_emit_ms = now


def produce_zones(
    cfg: TrackerConfig, emit: Callable[[ZoneChange], None], stop_event: threading.Event
) -> None:
    produce_region(cfg, cfg.ocr.zones, lambda text, now: ZoneChange(time_ms=now, zone=text), emit, stop_event)


def produce_targets(
    cfg: TrackerConfig, emit: Callable[[TargetSighting], None], stop_event: threading.Event
) -> None:
    produce_region(
        cfg,
        cfg.ocr.targets,
        lambda text, now: TargetSighting(time_ms=now, name=text),
        emit,
        stop_event,
    )