"""Streaming correlator: links loot drops to monster sources (port of CompileLootEvents)."""

from __future__ import annotations

import math
import uuid
from collections import deque
from dataclasses import dataclass

GROUND = "Ground/Unknown"
_INF = math.inf


@dataclass(frozen=True)
class SourceEvent:
    time_ms: int
    monster: str
    can_skin: bool
    can_butcher: bool
    can_extract: bool


@dataclass(frozen=True)
class LootEvent:
    time_ms: int
    item: str
    amount: int


@dataclass(frozen=True)
class BuryEvent:
    time_ms: int


@dataclass(frozen=True)
class TargetSighting:
    time_ms: int
    name: str


@dataclass(frozen=True)
class ZoneChange:
    time_ms: int
    zone: str


@dataclass(frozen=True)
class LootDrop:
    time_ms: int
    source: str
    encounter_uuid: str
    activity: str
    item: str
    amount: int
    status: str
    lag_ms: int
    zone: str


class Correlator:
    """Reproduces the legacy PowerShell correlation rules on a live/offline event stream.

    Constants map to the historical behavior:

    * ``buffer_seconds``: how recent a monster source (or target sighting) must be
      to explain a loot drop (10s in the legacy scripts).
    * ``session_timeout``: max seconds between body-state packets to still count as
      the same encounter (3s).
    * ``retroactive_threshold``: max seconds a drop may precede a state-change packet
      to be attributed to Skinning/Butchering/Extracting (0.9s).
    """

    def __init__(
        self,
        buffer_seconds: float = 10.0,
        session_timeout: float = 3.0,
        retroactive_threshold: float = 0.9,
    ) -> None:
        self.buffer_seconds = buffer_seconds
        self.session_timeout = session_timeout
        self.retroactive_threshold = retroactive_threshold

        self.pending: list[LootEvent] = []
        self.sightings: deque[TargetSighting] = deque()
        self.drops: list[LootDrop] = []

        self.current_encounter_uuid: str = str(uuid.uuid4())
        self.current_monster: str | None = None
        self.last_packet_time: int | None = None
        self.last_skin = False
        self.last_butcher = False
        self.last_extract = False
        self.current_zone = "Unknown"

    # -- external event ingestion ------------------------------------------------

    def ingest_zone_change(self, change: ZoneChange) -> None:
        self.current_zone = change.zone

    def ingest_target(self, sighting: TargetSighting) -> None:
        self.sightings.append(sighting)
        self._prune_sightings()

    def ingest_loot(self, event: LootEvent) -> None:
        self.pending.append(event)

    def ingest_bury(self, event: BuryEvent) -> None:
        # A bury ends the encounter: flush pending drops against the last monster.
        self._flush(event.time_ms)
        self.current_encounter_uuid = str(uuid.uuid4())
        self.current_monster = None
        self.last_packet_time = event.time_ms
        self.last_skin = False
        self.last_butcher = False
        self.last_extract = False

    def ingest_source(self, event: SourceEvent) -> None:
        time_since_last = (
            _INF
            if self.last_packet_time is None
            else (event.time_ms - self.last_packet_time) / 1000.0
        )

        is_same_encounter = event.monster == self.current_monster and time_since_last <= self.session_timeout
        just_skinned = is_same_encounter and self.last_skin and not event.can_skin
        just_butchered = is_same_encounter and self.last_butcher and not event.can_butcher
        just_extracted = is_same_encounter and self.last_extract and not event.can_extract

        self._flush(event.time_ms, just_skinned, just_butchered, just_extracted)

        if not is_same_encounter:
            self.current_encounter_uuid = str(uuid.uuid4())
            self.current_monster = event.monster

        self.last_skin = event.can_skin
        self.last_butcher = event.can_butcher
        self.last_extract = event.can_extract
        self.last_packet_time = event.time_ms

    def take_drops(self) -> list[LootDrop]:
        """Return and clear every drop produced so far (for live streaming)."""
        drops = list(self.drops)
        self.drops.clear()
        return drops

    def flush_expired(self, now_ms: int) -> list[LootDrop]:
        """Flush pending drops that failed to correlate within the buffer window.

        A drop older than ``buffer_seconds`` is no longer attributable to a
        monster encounter, so it is emitted as a lone/orphaned drop instead of
        waiting for the stream to end.
        """
        cutoff = now_ms - int(self.buffer_seconds * 1000)
        expired: list[LootEvent] = []
        remaining: list[LootEvent] = []
        for drop in self.pending:
            if drop.time_ms < cutoff:
                expired.append(drop)
            else:
                remaining.append(drop)
        if not expired:
            return []
        produced = [self._orphan_drop(d) for d in expired]
        self.pending = remaining
        return produced

    def finalize(self) -> list[LootDrop]:
        """Flush any remaining pending drops (end of stream)."""
        for drop in self.pending:
            self.drops.append(
                LootDrop(
                    time_ms=drop.time_ms,
                    source=self.current_monster or GROUND,
                    encounter_uuid=self.current_encounter_uuid,
                    activity="Looting",
                    item=drop.item,
                    amount=drop.amount,
                    status="Linked",
                    lag_ms=0,
                    zone=self.current_zone,
                )
            )
        self.pending.clear()
        return list(self.drops)

    # -- internal helpers ---------------------------------------------------------

    def _prune_sightings(self) -> None:
        if not self.pending:
            return
        oldest_drop = min(drop.time_ms for drop in self.pending)
        cutoff = oldest_drop - int(self.buffer_seconds * 1000)
        while self.sightings and self.sightings[0].time_ms < cutoff:
            self.sightings.popleft()

    def _orphan_source(self, drop_time_ms: int) -> tuple[str, float]:
        """Best matching target sighting within the buffer, else Ground/Unknown."""
        best_name = GROUND
        best_lag = _INF
        for sighting in self.sightings:
            lag = (drop_time_ms - sighting.time_ms) / 1000.0
            if 0.0 <= lag <= self.buffer_seconds and lag < best_lag:
                best_name = sighting.name
                best_lag = lag
        return best_name, best_lag

    def _orphan_drop(self, drop: LootEvent) -> LootDrop:
        """Build a lone/orphaned drop using the nearest target sighting."""
        orphan_name, orphan_lag = self._orphan_source(drop.time_ms)
        status = "Linked" if orphan_name != GROUND else "Orphaned"
        lag_ms = round(orphan_lag * 1000) if orphan_lag != _INF else 0
        return LootDrop(
            time_ms=drop.time_ms,
            source=orphan_name,
            encounter_uuid=str(uuid.uuid4()),
            activity="Looting",
            item=drop.item,
            amount=drop.amount,
            status=status,
            lag_ms=lag_ms,
            zone=self.current_zone,
        )

    def _flush(
        self,
        ref_time_ms: int,
        just_skinned: bool = False,
        just_butchered: bool = False,
        just_extracted: bool = False,
    ) -> None:
        for drop in self.pending:
            if self.current_monster is not None and ref_time_ms is not None:
                monster_lag = (ref_time_ms - drop.time_ms) / 1000.0
            else:
                monster_lag = _INF
            orphan_name, orphan_lag = self._orphan_source(drop.time_ms)

            if monster_lag <= self.buffer_seconds and monster_lag < orphan_lag:
                activity = "Looting"
                if just_skinned and monster_lag <= self.retroactive_threshold:
                    activity = "Skinning"
                elif just_butchered and monster_lag <= self.retroactive_threshold:
                    activity = "Butchering"
                elif just_extracted and monster_lag <= self.retroactive_threshold:
                    activity = "Extracting"
                self.drops.append(
                    LootDrop(
                        time_ms=drop.time_ms,
                        source=self.current_monster or GROUND,
                        encounter_uuid=self.current_encounter_uuid,
                        activity=activity,
                        item=drop.item,
                        amount=drop.amount,
                        status="Linked",
                        lag_ms=round(monster_lag * 1000),
                        zone=self.current_zone,
                    )
                )
            else:
                self.drops.append(self._orphan_drop(drop))
        self.pending.clear()