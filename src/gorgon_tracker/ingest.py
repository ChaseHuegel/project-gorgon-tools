"""DB writer: maps parsed/correlated events onto the SQLite schema."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import db
from .correlator import (
    BuryEvent,
    LootDrop,
    LootEvent,
    SourceEvent,
    TargetSighting,
    ZoneChange,
)


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
        raw_id = self._raw("chat", event.time_ms, {"item": event.item, "amount": event.amount})
        return db.insert_loot(self.conn, self.session_id, raw_id, event.time_ms, event.item, event.amount)

    def bury(self, event: BuryEvent) -> int:
        raw_id = self._raw("chat", event.time_ms, {})
        return db.insert_burial(self.conn, self.session_id, raw_id, event.time_ms)

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
        )

    def close_encounters(self) -> None:
        for encounter_uuid, ended_at in self._encounter_end.items():
            encounter_id = self._encounter_ids[encounter_uuid]
            self.conn.execute(
                "UPDATE encounters SET ended_at = ? WHERE id = ?", (ended_at, encounter_id)
            )

    def commit(self) -> None:
        self.conn.commit()