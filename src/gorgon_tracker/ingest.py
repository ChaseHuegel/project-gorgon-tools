"""DB writer: maps parsed/correlated events onto the SQLite schema."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from . import db
from .correlator import (
    ActivityEvent,
    BuryEvent,
    CorpseSearch,
    InteractionStart,
    ItemCode,
    LootDrop,
    LootEvent,
    SourceEvent,
    TargetSighting,
    ZoneChange,
)
from .itemdb import split_item_name


def _dedup_hash(event: LootEvent) -> str:
    """Deterministic hash over the loot fact's dedup key.

    Both the chat and Unity report of the same pickup share the item, quantity,
    and whole-second timestamp, so the hash is identical for the pair — that is
    the reconciliation signal persisted on ``raw_events.dedup_hash``.
    """
    second = event.time_ms - event.time_ms % 1000
    key = f"{event.source_class}|{event.item}|{event.amount}|{second}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


class DbWriter:
    """Write events from one session into the database, deduplicating encounters."""

    def __init__(self, conn: sqlite3.Connection, session_id: int) -> None:
        self.conn = conn
        self.session_id = session_id
        self._encounter_ids: dict[str, int] = {}
        self._encounter_end: dict[str, int] = {}

    def _raw(self, source: str, captured_at: int, payload: dict[str, Any]) -> int:
        return db.insert_raw_event(self.conn, self.session_id, source, captured_at, payload)

    def loot(self, event: LootEvent) -> int:
        source_class = event.source_class if event.source_class in ("chat", "unity") else "chat"
        raw_id = db.insert_raw_event(
            self.conn,
            self.session_id,
            source_class,
            event.time_ms,
            {
                "item": event.item,
                "amount": event.amount,
                "instance_id": event.instance_id,
                "entity_id": event.entity_id,
                "item_code_id": event.item_code_id,
                "missed": event.missed,
            },
            dedup_hash=_dedup_hash(event),
        )
        return db.insert_loot(
            self.conn,
            self.session_id,
            raw_id,
            event.time_ms,
            event.item,
            event.amount,
            instance_id=event.instance_id,
            entity_id=event.entity_id,
            source_class=source_class,
        )

    def bury(self, event: BuryEvent) -> int:
        raw_id = self._raw("chat", event.time_ms, {})
        return db.insert_burial(self.conn, self.session_id, raw_id, event.time_ms)

    def interaction(self, event: InteractionStart) -> int:
        return self._raw("unity_interaction", event.time_ms, {"entity_id": event.entity_id})

    def corpse_search(self, event: CorpseSearch) -> int:
        raw_id = self._raw(
            "unity_corpse",
            event.time_ms,
            {
                "monster": event.monster,
                "entity_id": event.entity_id,
                "killer": event.killer,
                "participants": event.participants or {},
            },
        )
        return db.insert_corpse_search(
            self.conn,
            self.session_id,
            raw_id,
            event.time_ms,
            event.entity_id,
            event.monster,
            killer=event.killer,
            participants=event.participants,
            extractions=event.extractions,
        )

    def activity(self, event: ActivityEvent) -> int:
        return self._raw("chat", event.time_ms, {"activity": event.activity})

    def raw_item_code(self, event: ItemCode) -> int:
        return self._raw(
            "unity_item_code", event.time_ms, {"instance_id": event.instance_id, "code": event.code}
        )

    def source(self, event: SourceEvent) -> int:
        raw_id = self._raw(
            "packet",
            event.time_ms,
            {
                "monster": event.monster,
                "can_skin": event.can_skin,
                "can_butcher": event.can_butcher,
                "can_extract": event.can_extract,
            },
        )
        return db.insert_source(
            self.conn,
            self.session_id,
            raw_id,
            event.time_ms,
            event.monster,
            event.can_skin,
            event.can_butcher,
            event.can_extract,
        )

    def target(self, sighting: TargetSighting) -> int:
        raw_id = self._raw("ocr_target", sighting.time_ms, {"name": sighting.name})
        return db.insert_target_sighting(
            self.conn, self.session_id, raw_id, sighting.time_ms, sighting.name
        )

    def zone(self, change: ZoneChange) -> int:
        raw_id = self._raw("ocr_zone", change.time_ms, {"zone": change.zone})
        return db.insert_zone_change(self.conn, self.session_id, raw_id, change.time_ms, change.zone)

    def drop(self, drop: LootDrop) -> int:
        encounter_id = self._encounter_ids.get(drop.encounter_uuid)
        if encounter_id is None:
            encounter_id = db.insert_encounter(
                self.conn, self.session_id, drop.encounter_uuid, drop.source, drop.time_ms
            )
            self._encounter_ids[drop.encounter_uuid] = encounter_id
        self._encounter_end[drop.encounter_uuid] = drop.time_ms
        self._learn_item(drop)
        return db.insert_loot_drop(
            self.conn,
            self.session_id,
            encounter_id,
            drop.time_ms,
            drop.source,
            drop.item,
            drop.amount,
            drop.activity,
            drop.zone,
            drop.status,
            drop.lag_ms,
            linked_via=drop.linked_via,
            monster_name=drop.monster_name,
            monster_lag_ms=drop.monster_lag_ms,
            target_name=drop.target_name,
            target_lag_ms=drop.target_lag_ms,
            corroborated_by_search=drop.corroborated_by_search,
            instance_id=drop.instance_id,
            entity_id=drop.entity_id,
            item_code_id=drop.item_code_id,
            item_display=drop.item_display,
            missed=drop.missed,
            killer_json=drop.killer_json,
        )

    def _learn_item(self, drop: LootDrop) -> None:
        """Persist the resolved internal-slug -> display-name mapping for the item."""
        raw = split_item_name(drop.item_display or drop.item)
        base_name, item_code = raw
        if not item_code:
            return
        db.record_item(
            self.conn,
            base_name,
            item_code,
            drop.item,
            drop.time_ms,
            inferred=drop.item_display is not None,
        )

    def close_encounters(self) -> None:
        for encounter_uuid, ended_at in self._encounter_end.items():
            encounter_id = self._encounter_ids[encounter_uuid]
            self.conn.execute(
                "UPDATE encounters SET ended_at = ? WHERE id = ?", (ended_at, encounter_id)
            )

    def commit(self) -> None:
        self.conn.commit()