"""Live capture pipeline: producer threads -> queue -> correlator -> sqlite."""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable
from sqlite3 import Connection

from . import db
from .config import TrackerConfig
from .correlator import (
    BuryEvent,
    Correlator,
    LootEvent,
    SourceEvent,
    TargetSighting,
    ZoneChange,
)
from .ingest import DbWriter
from .sources import chat_tail as chat_source
from .sources import ocr as ocr_source
from .sources import tshark_live as packet_source
from .timeutil import utc_now_ms

logger = logging.getLogger("gorgon_tracker.pipeline")

Producer = Callable[[threading.Event], None]


def _run_producer(name: str, producer: Producer, stop_event: threading.Event) -> None:
    try:
        producer(stop_event)
    except Exception as exc:  # noqa: BLE001 - a dead source must not kill the pipeline
        logger.warning("source '%s' stopped unexpectedly: %s", name, exc)


def _dispatch(event: object, writer: DbWriter, correlator: Correlator) -> str:
    """Route one event to the DB writer and correlator; returns the event kind."""
    if isinstance(event, ZoneChange):
        writer.zone(event)
        correlator.ingest_zone_change(event)
        return "zone"
    if isinstance(event, TargetSighting):
        writer.target(event)
        correlator.ingest_target(event)
        return "target"
    if isinstance(event, BuryEvent):
        writer.bury(event)
        correlator.ingest_bury(event)
        return "bury"
    if isinstance(event, LootEvent):
        writer.loot(event)
        correlator.ingest_loot(event)
        return "loot"
    if isinstance(event, SourceEvent):
        writer.source(event)
        correlator.ingest_source(event)
        return "source"
    raise TypeError(f"unhandled event type: {type(event).__name__}")


def has_capture_ok(cfg: TrackerConfig) -> bool:
    """Whether the packet source can be started (tshark present, filter resolvable)."""
    try:
        packet_source.build_bpf_filter(cfg)
        return True
    except RuntimeError:
        return False


def build_producers(cfg: TrackerConfig, emit: Callable[[object], None]) -> list[tuple[str, Producer]]:
    producers: list[tuple[str, Producer]] = []

    if cfg.capture.enabled:
        producers.append(("packet", lambda stop: packet_source.produce(cfg, emit, stop)))

    if cfg.chat.tail:
        chat_dir = cfg.chat.log_dir
        if chat_dir:
            producers.append(("chat", lambda stop: chat_source.produce(cfg, emit, stop)))
        else:
            logger.warning("chat tailing skipped: no chat log directory configured/discovered")

    if cfg.ocr.enabled:
        producers.append(("zone", lambda stop: ocr_source.produce_zones(cfg, emit, stop)))
        producers.append(("target", lambda stop: ocr_source.produce_targets(cfg, emit, stop)))

    if not producers:
        logger.warning("no capture sources enabled; run will idle until stopped")
    return producers


def run_pipeline(
    cfg: TrackerConfig,
    platform: str,
    stop_event: threading.Event,
    status_cb: Callable[[Counter[str]], None] | None = None,
    on_session: Callable[[int], None] | None = None,
) -> tuple[int, Counter[str]]:
    """Run all configured sources until ``stop_event`` fires, then finalize.

    Owns its own SQLite connection so the DB is only ever touched from the
    thread that runs this function.
    """
    conn = db.connect(cfg.db.path)
    db.migrate(conn)
    try:
        session_id = db.open_or_new_session(conn, platform, cfg.model_dump())
        if on_session is not None:
            on_session(session_id)
        counters = _run_pipeline_inner(cfg, conn, session_id, stop_event, status_cb)
    finally:
        db.close_session(conn, session_id)
        conn.close()
    return session_id, counters


def _run_pipeline_inner(
    cfg: TrackerConfig,
    conn: Connection,
    session_id: int,
    stop_event: threading.Event,
    status_cb: Callable[[Counter[str]], None] | None,
) -> Counter[str]:
    work_queue: queue.Queue[object] = queue.Queue(maxsize=10000)

    def emit(event: object) -> None:
        work_queue.put(event)

    producers = build_producers(cfg, emit)
    threads = [
        threading.Thread(target=_run_producer, args=(name, producer, stop_event), daemon=True, name=name)
        for name, producer in producers
    ]
    for thread in threads:
        thread.start()

    writer = DbWriter(conn, session_id)
    correlator = Correlator(
        buffer_seconds=cfg.correlate.buffer_seconds,
        session_timeout=cfg.correlate.session_timeout,
        retroactive_threshold=cfg.correlate.retroactive_threshold,
    )
    counters: Counter[str] = Counter()
    last_status = time.monotonic()
    last_flush = time.monotonic()
    COMMIT_INTERVAL = 1.0

    while not stop_event.is_set():
        now = time.monotonic()
        if now - last_flush >= COMMIT_INTERVAL:
            for drop in correlator.flush_expired(utc_now_ms()):
                writer.drop(drop)
                counters["loot_drop"] += 1
            writer.commit()
            last_flush = now
        try:
            event = work_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        kind = _dispatch(event, writer, correlator)
        counters[kind] += 1
        for drop in correlator.take_drops():
            writer.drop(drop)
            counters["loot_drop"] += 1
        if status_cb is not None:
            now = time.monotonic()
            if now - last_status >= 30.0:
                status_cb(counter_snapshot(counters))
                last_status = now

    # Signal fired: stop producers, drain the queue, then finalize correlation.
    for thread in threads:
        thread.join(timeout=5)
    while True:
        try:
            event = work_queue.get_nowait()
        except queue.Empty:
            break
        kind = _dispatch(event, writer, correlator)
        counters[kind] += 1

    for drop in correlator.finalize():
        writer.drop(drop)
        counters["loot_drop"] += 1
    writer.close_encounters()
    writer.commit()
    return counters


def counter_snapshot(counters: Counter[str]) -> Counter[str]:
    return Counter(counters)