"""Offline replay of historical captures through the same parser and correlator."""

from __future__ import annotations

import glob
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import db
from .config import TrackerConfig
from .correlator import (
    ActivityEvent,
    BuryEvent,
    CorpseSearch,
    Correlator,
    EncounterActivity,
    EncounterBegin,
    EncounterEnd,
    InteractionStart,
    ItemCode,
    LootEvent,
    TargetSighting,
    ZoneChange,
)
from .ingest import DbWriter
from .parsers import chat as chat_parser
from .parsers import csvs as csv_parser
from .parsers import playerlog as playerlog_parser

_CHAT_SUFFIXES = (".log", ".txt")
_PLAYERLOG_NAMES = ("Player.log", "Player-prev.log")
_PLAYERLOG_FIRST_RE = re.compile(r"^\[\d\d:\d\d:\d\d\].*LocalPlayer: Process")


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
    if path.name in _PLAYERLOG_NAMES:
        return "playerlog"
    suffix = path.suffix.lower()
    if suffix in _CHAT_SUFFIXES or suffix == "":
        # Player.log snapshots use the same `.log` suffix; sniff the header.
        with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
            first = fh.readline()
        if _PLAYERLOG_FIRST_RE.match(first):
            return "playerlog"
        return "chat"
    if suffix == ".csv":
        return "csv"
    return "unknown"


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
        target_fallback_seconds=cfg.correlate.target_fallback_seconds,
        search_corroboration_seconds=cfg.correlate.search_corroboration_seconds,
        activity_window_seconds=cfg.correlate.activity_window_seconds,
    )

    loot_events: list[LootEvent] = []
    bury_events: list[BuryEvent] = []
    activity_events: list[ActivityEvent] = []
    zone_changes: list[ZoneChange] = []
    target_sightings: list[TargetSighting] = []
    interactions: list[InteractionStart] = []
    corpse_searches: list[CorpseSearch] = []
    item_codes: list[ItemCode] = []
    parsed_files = 0

    for path in sources:
        kind = _classify(path)
        if not path.exists():
            raise FileNotFoundError(f"replay input not found: {path}")
        if kind == "chat":
            for event in chat_parser.parse_chat_file(path):
                _route_chat_event(event, loot_events, bury_events, activity_events)
            parsed_files += 1
        elif kind == "playerlog":
            for plog_event in playerlog_parser.parse_player_log_file(path):
                _route_event(
                    plog_event,
                    loot_events,
                    bury_events,
                    zone_changes,
                    interactions,
                    corpse_searches,
                    item_codes,
                )
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
                _route_chat_event(event, loot_events, bury_events, activity_events)

    # Merge everything into one timeline (loot sorts before state changes at equal time).
    timeline: list[tuple[int, int, object]] = []
    for zone_change in zone_changes:
        timeline.append((zone_change.time_ms, 0, zone_change))
    for sighting in target_sightings:
        timeline.append((sighting.time_ms, 0, sighting))
    for loot_evt in loot_events:
        timeline.append((loot_evt.time_ms, 1, loot_evt))
    for bury_evt in bury_events:
        timeline.append((bury_evt.time_ms, 2, bury_evt))
    for activity_evt in activity_events:
        timeline.append((activity_evt.time_ms, 2, activity_evt))
    for interaction in interactions:
        timeline.append((interaction.time_ms, 2, interaction))
    for corpse_search in corpse_searches:
        timeline.append((corpse_search.time_ms, 2, corpse_search))
    for item_code in item_codes:
        timeline.append((item_code.time_ms, 2, item_code))
    timeline.sort(key=lambda item: (item[0], item[1]))

    encounters = 0
    encounter_activities = 0
    for _, _, timeline_event in timeline:
        _ingest_timeline_event(timeline_event, writer, correlator)
        for encounter_event in correlator.take_encounter_events():
            if isinstance(encounter_event, EncounterBegin):
                writer.encounter_begin(encounter_event)
                encounters += 1
            elif isinstance(encounter_event, EncounterActivity):
                writer.encounter_activity(encounter_event)
                encounter_activities += 1
            else:
                assert isinstance(encounter_event, EncounterEnd)
                writer.encounter_end(encounter_event)

    drops = correlator.finalize()
    for drop in drops:
        writer.drop(drop)
    writer.close_encounters()
    db.close_session(conn, session_id)  # replay sessions are retrospective
    writer.commit()

    return {
        "session_id": session_id,
        "parsed_files": parsed_files,
        "loot_kept": len(loot_events),
        "zones": len(zone_changes),
        "targets": len(target_sightings),
        "burials": len(bury_events),
        "activities": len(activity_events),
        "encounters": encounters,
        "encounter_activities": encounter_activities,
        "drops": len(drops),
    }


def _ingest_timeline_event(
    timeline_event: object, writer: DbWriter, correlator: Correlator
) -> None:
    if isinstance(timeline_event, ZoneChange):
        writer.zone(timeline_event)
        correlator.ingest_zone_change(timeline_event)
    elif isinstance(timeline_event, TargetSighting):
        writer.target(timeline_event)
        correlator.ingest_target(timeline_event)
    elif isinstance(timeline_event, BuryEvent):
        writer.bury(timeline_event)
        correlator.ingest_bury(timeline_event)
    elif isinstance(timeline_event, ActivityEvent):
        writer.activity(timeline_event)
        correlator.ingest_activity(timeline_event)
    elif isinstance(timeline_event, LootEvent):
        writer.loot(timeline_event)
        correlator.ingest_loot(timeline_event)
    elif isinstance(timeline_event, InteractionStart):
        writer.interaction(timeline_event)
        correlator.ingest_interaction(timeline_event)
    elif isinstance(timeline_event, CorpseSearch):
        writer.corpse_search(timeline_event)
        correlator.ingest_corpse_search(timeline_event)
    else:
        assert isinstance(timeline_event, ItemCode)
        writer.raw_item_code(timeline_event)
        correlator.note_item_code(timeline_event)


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        first = fh.readline()
    return [col.strip() for col in first.split(",")]


def _route_event(
    event: object,
    loot_events: list[LootEvent],
    bury_events: list[BuryEvent],
    zone_changes: list[ZoneChange],
    interactions: list[InteractionStart],
    corpse_searches: list[CorpseSearch],
    item_codes: list[ItemCode],
) -> None:
    if isinstance(event, (LootEvent, ZoneChange, InteractionStart, CorpseSearch, ItemCode)):
        if isinstance(event, LootEvent):
            loot_events.append(event)
        elif isinstance(event, ZoneChange):
            zone_changes.append(event)
        elif isinstance(event, InteractionStart):
            interactions.append(event)
        elif isinstance(event, CorpseSearch):
            corpse_searches.append(event)
        else:
            item_codes.append(event)
    else:
        assert isinstance(event, BuryEvent)
        bury_events.append(event)


def _route_chat_event(
    event: object,
    loot_events: list[LootEvent],
    bury_events: list[BuryEvent],
    activity_events: list[ActivityEvent],
) -> None:
    if isinstance(event, LootEvent):
        loot_events.append(event)
    elif isinstance(event, ActivityEvent):
        activity_events.append(event)
    else:
        assert isinstance(event, BuryEvent)
        bury_events.append(event)
