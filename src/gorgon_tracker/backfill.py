"""Rebuild encounter rows and per-encounter activities from raw events.

Sessions captured before activity tracking lack ``encounter_activities`` rows
and only have drop-derived encounters. This module replays each session's own
raw event stream through the correlator and writes the missing encounter
ledger. Rebuilt encounters are matched to existing rows by (monster, drop
times), so the per-activity denominators become available for historical data
without rewriting any loot row.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import db
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
    SourceEvent,
    TargetSighting,
    ZoneChange,
)


def _correlator_from_snapshot(snapshot: dict[str, Any] | None) -> Correlator:
    """Build a correlator with the session's own tuning, if the snapshot has it."""
    values = (snapshot or {}).get("correlate") or {}
    return Correlator(
        buffer_seconds=values.get("buffer_seconds", 10.0),
        session_timeout=values.get("session_timeout", 3.0),
        retroactive_threshold=values.get("retroactive_threshold", 0.9),
        target_fallback_seconds=values.get("target_fallback_seconds", 3.0),
        search_corroboration_seconds=values.get("search_corroboration_seconds", 2.0),
        activity_window_seconds=values.get("activity_window_seconds", 2.0),
    )


def _to_event(captured_at: int, source: str, payload: dict[str, Any]) -> object | None:
    if source == "packet":
        return SourceEvent(
            time_ms=captured_at,
            monster=payload["monster"],
            can_skin=bool(payload.get("can_skin")),
            can_butcher=bool(payload.get("can_butcher")),
            can_extract=bool(payload.get("can_extract")),
        )
    if source in ("chat", "unity"):
        if "item" in payload:
            return LootEvent(
                time_ms=captured_at,
                item=payload["item"],
                amount=int(payload.get("amount") or 1),
                instance_id=payload.get("instance_id"),
                entity_id=payload.get("entity_id"),
                source_class=source,
                item_code_id=payload.get("item_code_id"),
                missed=bool(payload.get("missed")),
            )
        if "activity" in payload:
            return ActivityEvent(time_ms=captured_at, activity=payload["activity"])
        return BuryEvent(time_ms=captured_at)
    if source == "unity_interaction":
        return InteractionStart(time_ms=captured_at, entity_id=payload["entity_id"])
    if source == "unity_corpse":
        return CorpseSearch(
            time_ms=captured_at,
            monster=payload["monster"],
            entity_id=payload.get("entity_id"),
            killer=payload.get("killer"),
            participants=payload.get("participants"),
            extractions=payload.get("extractions"),
        )
    if source == "unity_item_code":
        return ItemCode(time_ms=captured_at, instance_id=payload["instance_id"], code=payload["code"])
    if source == "ocr_target":
        return TargetSighting(time_ms=captured_at, name=payload["name"])
    if source == "ocr_zone":
        return ZoneChange(time_ms=captured_at, zone=payload["zone"])
    return None


def _feed(correlator: Correlator, event: object) -> None:
    if isinstance(event, ZoneChange):
        correlator.ingest_zone_change(event)
    elif isinstance(event, TargetSighting):
        correlator.ingest_target(event)
    elif isinstance(event, LootEvent):
        correlator.ingest_loot(event)
    elif isinstance(event, BuryEvent):
        correlator.ingest_bury(event)
    elif isinstance(event, ActivityEvent):
        correlator.ingest_activity(event)
    elif isinstance(event, SourceEvent):
        correlator.ingest_source(event)
    elif isinstance(event, InteractionStart):
        correlator.ingest_interaction(event)
    elif isinstance(event, CorpseSearch):
        correlator.ingest_corpse_search(event)
    else:
        assert isinstance(event, ItemCode)
        correlator.note_item_code(event)


def _existing_drop_times(conn: sqlite3.Connection, session_id: int) -> dict[int, list[int]]:
    rows = conn.execute(
        "SELECT encounter_id, captured_at FROM loot_drops"
        " WHERE session_id = ? AND encounter_id IS NOT NULL ORDER BY captured_at",
        (session_id,),
    ).fetchall()
    times: dict[int, list[int]] = {}
    for row in rows:
        times.setdefault(int(row["encounter_id"]), []).append(int(row["captured_at"]))
    return times


def backfill_session(conn: sqlite3.Connection, session_id: int) -> dict[str, int]:
    """Rebuild the encounter ledger for one session; returns result counts."""
    snapshot_row = conn.execute(
        "SELECT config_snapshot_json FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    snapshot: dict[str, Any] = {}
    if snapshot_row is not None and snapshot_row["config_snapshot_json"]:
        try:
            snapshot = json.loads(snapshot_row["config_snapshot_json"])
        except ValueError:
            snapshot = {}

    # Extractions live on corpse_searches, not the raw payload; join them back.
    extra_by_raw: dict[int, dict[str, str]] = {}
    for row in conn.execute(
        "SELECT raw_event_id, extractions_json FROM corpse_searches"
        " WHERE session_id = ? AND raw_event_id IS NOT NULL",
        (session_id,),
    ):
        try:
            extra_by_raw[int(row["raw_event_id"])] = json.loads(row["extractions_json"])
        except (ValueError, TypeError):
            extra_by_raw[int(row["raw_event_id"])] = {}

    correlator = _correlator_from_snapshot(snapshot)
    begins: dict[str, EncounterBegin] = {}
    activities: dict[str, list[EncounterActivity]] = {}
    ends: dict[str, int] = {}

    rows = conn.execute(
        "SELECT id, source, captured_at, payload_json FROM raw_events"
        " WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except ValueError:
            continue
        event = _to_event(int(row["captured_at"]), row["source"], payload)
        if event is None:
            continue
        if isinstance(event, CorpseSearch):
            extra = extra_by_raw.get(int(row["id"]))
            if extra:
                event = CorpseSearch(
                    time_ms=event.time_ms,
                    monster=event.monster,
                    entity_id=event.entity_id,
                    killer=event.killer,
                    participants=event.participants,
                    extractions=extra,
                )
        _feed(correlator, event)
        for enc_event in correlator.take_encounter_events():
            if isinstance(enc_event, EncounterBegin):
                begins[enc_event.encounter_uuid] = enc_event
            elif isinstance(enc_event, EncounterActivity):
                activities.setdefault(enc_event.encounter_uuid, []).append(enc_event)
            else:
                assert isinstance(enc_event, EncounterEnd)
                ends[enc_event.encounter_uuid] = enc_event.time_ms

    rebuilt_drops: dict[str, list[int]] = {}
    for drop in correlator.finalize():
        rebuilt_drops.setdefault(drop.encounter_uuid, []).append(drop.time_ms)

    existing_times = _existing_drop_times(conn, session_id)
    existing_by_times: dict[tuple[str, tuple[int, ...]], int] = {}
    # For zero-drop encounters the uuid regenerates every run, so the start
    # time (same event stream) acts as the stable identity.
    existing_by_start: dict[tuple[str, str, int], int] = {}
    for row in conn.execute(
        "SELECT id, monster, started_at, zone FROM encounters WHERE session_id = ?", (session_id,)
    ):
        enc_id = int(row["id"])
        drop_times = existing_times.get(enc_id, [])
        if drop_times:
            existing_by_times[(row["monster"], tuple(drop_times))] = enc_id
        else:
            existing_by_start[(row["monster"], row["zone"], int(row["started_at"]))] = enc_id

    created = 0
    matched = 0
    activity_count = 0
    with conn:
        for uuid, begin in begins.items():
            key = (begin.monster, tuple(rebuilt_drops.get(uuid, [])))
            encounter_id = existing_by_times.get(key)
            if encounter_id is None and not rebuilt_drops.get(uuid):
                encounter_id = existing_by_start.get((begin.monster, begin.zone, begin.time_ms))
            if encounter_id is None:
                encounter_id = db.insert_encounter(
                    conn,
                    session_id,
                    uuid,
                    begin.monster,
                    begin.time_ms,
                    ended_at=ends.get(uuid),
                    zone=begin.zone,
                )
                created += 1
            else:
                matched += 1
                conn.execute(
                    "UPDATE encounters SET started_at = MIN(started_at, ?),"
                    " ended_at = MAX(COALESCE(ended_at, ?), ?),"
                    " zone = CASE WHEN zone = 'Unknown' THEN ? ELSE zone END"
                    " WHERE id = ?",
                    (begin.time_ms, begin.time_ms, ends.get(uuid, begin.time_ms), begin.zone, encounter_id),
                )
            for act in activities.get(uuid, []):
                db.insert_encounter_activity(
                    conn, session_id, encounter_id, act.activity, act.time_ms
                )
                activity_count += 1
    return {"encounters_created": created, "encounters_matched": matched, "activities": activity_count}


def backfill_all(
    conn: sqlite3.Connection, session_id: int | None = None
) -> list[dict[str, Any]]:
    """Rebuild encounter ledgers for the given session, or for every session."""
    if session_id is not None:
        return [{"session_id": session_id, **backfill_session(conn, session_id)}]
    rows = conn.execute(
        "SELECT id FROM sessions WHERE EXISTS (SELECT 1 FROM raw_events WHERE raw_events.session_id = sessions.id)"
        " ORDER BY id"
    ).fetchall()
    results = []
    for row in rows:
        sid = int(row["id"])
        results.append({"session_id": sid, **backfill_session(conn, sid)})
    return results