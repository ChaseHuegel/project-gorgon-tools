"""Offline replay of historical captures through the same parser and correlator."""

from __future__ import annotations

import glob
import sqlite3
from pathlib import Path
from typing import Any

from . import db
from .config import TrackerConfig
from .correlator import BuryEvent, Correlator, LootEvent, SourceEvent, TargetSighting, ZoneChange
from .ingest import DbWriter
from .parsers import chat as chat_parser
from .parsers import csvs as csv_parser
from .parsers import packets as packet_parser

_CAPTURE_SUFFIXES = (".pcapng", ".pcap", ".cap")
_JSON_SUFFIXES = (".json",)
_CHAT_SUFFIXES = (".log", ".txt")


def expand_inputs(paths: list[Path]) -> list[Path]:
    expanded: list[Path] = []
    for path in paths:
        text = str(path)
        if glob.has_magic(text):
            expanded.extend(Path(p) for p in glob.glob(str(Path(text).expanduser())))
        else:
            expanded.append(Path(text).expanduser())
    return sorted(expanded)


def _classify(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _CAPTURE_SUFFIXES:
        return "pcap"
    if suffix in _JSON_SUFFIXES:
        return "json"
    if suffix in _CHAT_SUFFIXES or suffix == "":
        return "chat"
    if suffix == ".csv":
        return "csv"
    return "unknown"


def _is_window_valid(windows: list[tuple[int, int]], time_ms: int, buffer_seconds: float) -> bool:
    buffer_ms = int(buffer_seconds * 1000)
    return any(start <= time_ms <= end + buffer_ms for start, end in windows)


def run_replay(
    conn: sqlite3.Connection,
    cfg: TrackerConfig,
    sources: list[Path],
    chat_dir: Path | None = None,
    platform: str = "linux",
) -> dict[str, Any]:
    """Parse the input bundle and write a fully correlated session into the database."""
    session_id = db.new_session(conn, platform, cfg.model_dump())
    writer = DbWriter(conn, session_id)
    correlator = Correlator(
        buffer_seconds=cfg.correlate.buffer_seconds,
        session_timeout=cfg.correlate.session_timeout,
        retroactive_threshold=cfg.correlate.retroactive_threshold,
    )

    windows: list[tuple[int, int]] = []
    source_events: list[SourceEvent] = []
    loot_events: list[LootEvent] = []
    bury_events: list[BuryEvent] = []
    zone_changes: list[ZoneChange] = []
    target_sightings: list[TargetSighting] = []
    parsed_files = 0

    for path in sources:
        kind = _classify(path)
        if not path.exists():
            raise FileNotFoundError(f"replay input not found: {path}")
        if kind == "pcap":
            doc = packet_parser.extract_pcap(
                path, tshark_path=cfg.capture.tshark_path
            )
            windows.append((doc.start_ms, doc.end_ms))
            source_events.extend(
                SourceEvent(
                    time_ms=ev.time_ms,
                    monster=ev.monster,
                    can_skin=ev.can_skin,
                    can_butcher=ev.can_butcher,
                    can_extract=ev.can_extract,
                )
                for ev in doc.events
            )
            parsed_files += 1
        elif kind == "json":
            doc = packet_parser.parse_capture_doc(packet_parser.load_json_doc(path))
            windows.append((doc.start_ms, doc.end_ms))
            source_events.extend(
                SourceEvent(
                    time_ms=ev.time_ms,
                    monster=ev.monster,
                    can_skin=ev.can_skin,
                    can_butcher=ev.can_butcher,
                    can_extract=ev.can_extract,
                )
                for ev in doc.events
            )
            parsed_files += 1
        elif kind == "chat":
            for event in chat_parser.parse_chat_file(path):
                if isinstance(event, LootEvent):
                    loot_events.append(event)
                else:
                    bury_events.append(event)
            parsed_files += 1
        elif kind == "csv":
            csv_path = path
            header = _read_header(csv_path)
            if "Text" in header and "zone" in csv_path.name.lower():
                zone_changes.extend(csv_parser.read_zone_changes(csv_path))
            elif "Text" in header and "target" in csv_path.name.lower():
                target_sightings.extend(csv_parser.read_target_sightings(csv_path))
            else:
                for row in csv_parser.read_legacy_loot_csv(csv_path):
                    loot_events.append(LootEvent(time_ms=row["time_ms"], item=row["item"], amount=row["amount"]))
            parsed_files += 1

    if chat_dir is not None:
        for path in sorted(chat_dir.glob("*.log")) + sorted(chat_dir.glob("*.txt")):
            for event in chat_parser.parse_chat_file(path):
                if isinstance(event, LootEvent):
                    loot_events.append(event)
                else:
                    bury_events.append(event)

    # Drop validity: only loot that falls inside a packet-capture window is kept.
    filtered = 0
    if windows:
        kept: list[LootEvent] = []
        for event in loot_events:
            if _is_window_valid(windows, event.time_ms, cfg.correlate.buffer_seconds):
                kept.append(event)
            else:
                filtered += 1
        loot_events = kept

    # Merge everything into one timeline (loot sorts before state changes at equal time).
    timeline: list[tuple[int, int, object]] = []
    for zone_change in zone_changes:
        timeline.append((zone_change.time_ms, 0, zone_change))
    for sighting in target_sightings:
        timeline.append((sighting.time_ms, 0, sighting))
    for loot_evt in loot_events:
        timeline.append((loot_evt.time_ms, 1, loot_evt))
    for source_evt in source_events:
        timeline.append((source_evt.time_ms, 2, source_evt))
    for bury_evt in bury_events:
        timeline.append((bury_evt.time_ms, 2, bury_evt))
    timeline.sort(key=lambda item: (item[0], item[1]))

    for _, _, timeline_event in timeline:
        if isinstance(timeline_event, ZoneChange):
            writer.zone(timeline_event)
            correlator.ingest_zone_change(timeline_event)
        elif isinstance(timeline_event, TargetSighting):
            writer.target(timeline_event)
            correlator.ingest_target(timeline_event)
        elif isinstance(timeline_event, BuryEvent):
            writer.bury(timeline_event)
            correlator.ingest_bury(timeline_event)
        elif isinstance(timeline_event, LootEvent):
            writer.loot(timeline_event)
            correlator.ingest_loot(timeline_event)
        else:
            assert isinstance(timeline_event, SourceEvent)
            writer.source(timeline_event)
            correlator.ingest_source(timeline_event)

    drops = correlator.finalize()
    for drop in drops:
        writer.drop(drop)
    writer.close_encounters()
    db.close_session(conn, session_id)  # replay sessions are retrospective
    writer.commit()

    return {
        "session_id": session_id,
        "parsed_files": parsed_files,
        "windows": len(windows),
        "sources": len(source_events),
        "loot_kept": len(loot_events),
        "loot_filtered": filtered,
        "zones": len(zone_changes),
        "targets": len(target_sightings),
        "burials": len(bury_events),
        "drops": len(drops),
    }


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        first = fh.readline()
    return [col.strip() for col in first.split(",")]