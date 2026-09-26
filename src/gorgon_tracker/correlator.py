"""Streaming correlator: links loot drops to monster sources (port of CompileLootEvents)."""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import deque
from dataclasses import dataclass

from rapidfuzz import fuzz

from .itemdb import infer_display

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
    amount: int = 1
    instance_id: int | None = None
    entity_id: int | None = None
    source_class: str = "chat"  # "chat" | "unity"
    item_code_id: int | None = None
    display_name: str | None = None
    missed: bool = False


@dataclass(frozen=True)
class BuryEvent:
    time_ms: int


@dataclass(frozen=True)
class ActivityEvent:
    """A chat status marker (`You skin the corpse.`) naming a corpse action."""

    time_ms: int
    activity: str  # "Skinning" | "Butchering" | "Extracting"


@dataclass(frozen=True)
class TargetSighting:
    time_ms: int
    name: str


@dataclass(frozen=True)
class ZoneChange:
    time_ms: int
    zone: str


@dataclass(frozen=True)
class InteractionStart:
    time_ms: int
    entity_id: int


@dataclass(frozen=True)
class CorpseSearch:
    time_ms: int
    monster: str
    entity_id: int | None
    killer: str | None = None
    participants: dict[str, dict[str, int | float]] | None = None  # name -> {"health","armor","aggro"}
    extractions: dict[str, str] | None = None  # action -> item


@dataclass(frozen=True)
class ItemCode:
    time_ms: int
    instance_id: int
    code: int


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
    # -- evidence (audit trail for how this drop was attributed) --------------
    linked_via: str = "monster"  # "monster" | "target" | "orphan"
    monster_name: str | None = None
    monster_lag_ms: int | None = None
    target_name: str | None = None
    target_lag_ms: int | None = None
    corroborated_by_search: bool = False
    # -- unity provenance ------------------------------------------------------
    instance_id: int | None = None
    entity_id: int | None = None
    item_code_id: int | None = None
    item_display: str | None = None
    missed: bool = False
    killer_json: str | None = None


@dataclass
class _Reconciled:
    """One loot fact after deduplicating chat/unity reports for the same pickup."""

    time_ms: int
    item: str
    amount: int
    source_class: str
    instance_id: int | None
    entity_id: int | None
    item_code_id: int | None
    display_name: str | None
    missed: bool


_TOKENS_RE = re.compile(r"[^a-z0-9]")


def _token(name: str) -> str:
    return _TOKENS_RE.sub("", name.lower())


def _fuzzy_score(left: str, right: str) -> float:
    return max(
        fuzz.ratio(left, right),
        fuzz.partial_ratio(left, right),
        fuzz.token_sort_ratio(left, right),
    )


def _missed_copy(drop: LootDrop) -> LootDrop:
    """Return ``drop`` with status forced to Missed (used for uncollected loot)."""
    return LootDrop(
        time_ms=drop.time_ms,
        source=drop.source,
        encounter_uuid=drop.encounter_uuid,
        activity=drop.activity,
        item=drop.item,
        amount=drop.amount,
        status="Missed",
        lag_ms=drop.lag_ms,
        zone=drop.zone,
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
        missed=True,
        killer_json=drop.killer_json,
    )


class Correlator:
    """Reproduces the legacy PowerShell correlation rules on a live/offline event stream.

    Constants map to the historical behavior:

    * ``buffer_seconds``: how recent a monster source (or target sighting) must be
      to explain a loot drop (10s in the legacy scripts).
    * ``session_timeout``: max seconds between body-state packets to still count as
      the same encounter (3s).
    * ``retroactive_threshold``: max seconds a drop may precede a state-change packet
      to be attributed to Skinning/Butchering/Extracting (0.9s).
    * ``activity_window_seconds``: how close to a corpse-description transition (or
      chat activity marker) a drop must be to inherit its activity. Grid is wider
      than ``retroactive_threshold`` because the Unity log stamps whole seconds, so
      a pickup and the description update that names the action can be ~1s apart.
      Only a verb that *newly* appears on a previously-seen corpse counts — a corpse
      that already shows skinned (someone else did it, or a re-search) never relabels.
    * ``target_fallback_seconds``: how stale a target sighting may be to compete with
      (or substitute for) a monster source. Looting targets the entity being looted,
      so fresh sightings are strong evidence; old ones are coincidence risk.
    * ``search_corroboration_seconds``: a target-linked drop within this many seconds
      of a same-name corpse-search packet is treated as corpse loot rather than a
      harvestable (flowers/logs/apples have no corpse-search packet).

    Unity ``Player.log`` events enrich the mix: ``CorpseSearch`` names the corpse by
    its entity id, ``InteractionStart`` opens the looting window, and loot facts from
    chat and the Unity log are reconciled per ``(canonical item, whole second)`` so
    the same reported pickup never double-counts.
    """

    def __init__(
        self,
        buffer_seconds: float = 10.0,
        session_timeout: float = 3.0,
        retroactive_threshold: float = 0.9,
        target_fallback_seconds: float = 3.0,
        search_corroboration_seconds: float = 2.0,
        activity_window_seconds: float = 2.0,
    ) -> None:
        self.buffer_seconds = buffer_seconds
        self.session_timeout = session_timeout
        self.retroactive_threshold = retroactive_threshold
        self.target_fallback_seconds = target_fallback_seconds
        self.search_corroboration_seconds = search_corroboration_seconds
        self.activity_window_seconds = activity_window_seconds

        self.pending: list[LootEvent] = []
        self.sightings: deque[TargetSighting] = deque()
        self.sources: deque[SourceEvent] = deque()
        self.drops: list[LootDrop] = []

        self.current_encounter_uuid: str = str(uuid.uuid4())
        self.current_monster: str | None = None
        self.last_packet_time: int | None = None
        self.last_skin = False
        self.last_butcher = False
        self.last_extract = False
        self.current_zone = "Unknown"

        self.current_window_entity: int | None = None
        self.entity_monsters: dict[int, str] = {}
        self.killer: str | None = None
        self.participants: dict[str, dict[str, int | float]] | None = None
        self.item_codes: dict[int, int] = {}

        # entity_id -> (last-seen corpse description extractions, time_ms).
        # Used to detect when a verb (skinned/butchered/extracted) newly appears.
        self._corpse_extra: dict[int, tuple[dict[str, str], int]] = {}
        # (activity, time_ms) marked by a chat status line; applies to nearby drops.
        self._activity_hint: tuple[str, int] | None = None

    # -- external event ingestion ------------------------------------------------

    def ingest_zone_change(self, change: ZoneChange) -> None:
        self.current_zone = change.zone

    def ingest_target(self, sighting: TargetSighting) -> None:
        self.sightings.append(sighting)
        self._prune_sightings()

    def ingest_loot(self, event: LootEvent) -> None:
        if event.instance_id is not None and event.instance_id in self.item_codes:
            event = LootEvent(
                time_ms=event.time_ms,
                item=event.item,
                amount=event.amount,
                instance_id=event.instance_id,
                entity_id=event.entity_id,
                source_class=event.source_class,
                item_code_id=self.item_codes[event.instance_id],
                display_name=event.display_name,
                missed=event.missed,
            )
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
        self._activity_hint = None
        if self.current_window_entity is not None:
            self._corpse_extra.pop(self.current_window_entity, None)

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

        self.sources.append(event)
        self._prune_sources()

        if not is_same_encounter:
            self.current_encounter_uuid = str(uuid.uuid4())
            self.current_monster = event.monster

        self.last_skin = event.can_skin
        self.last_butcher = event.can_butcher
        self.last_extract = event.can_extract
        self.last_packet_time = event.time_ms

    def ingest_interaction(self, event: InteractionStart) -> None:
        """A new corpse-looting window opens: flush any prior window's pending loot."""
        if self.current_monster is not None:
            self._flush(event.time_ms)
        self.current_window_entity = event.entity_id
        if event.entity_id in self.entity_monsters:
            monster = self.entity_monsters[event.entity_id]
            if self.current_monster != monster:
                self.current_encounter_uuid = str(uuid.uuid4())
            self.current_monster = monster

    def ingest_activity(self, event: ActivityEvent) -> None:
        """A chat status marker (e.g. ``You skin the corpse.``) pins a corpse action.

        The marker applies to drops flushed now and to any arriving within the
        activity window, so the ``x added to inventory.`` line immediately before
        or after it is labeled regardless of which line was written first.
        """
        self._activity_hint = (event.activity, event.time_ms)
        self._flush(event.time_ms)

    def ingest_corpse_search(self, event: CorpseSearch) -> None:
        """A corpse-search dialogue names the looted corpse's monster and killer.

        The talk-screen description grows a line like ``Mennelaia skinned a Pelt
        from the corpse.`` each time an action is performed on the body. A verb
        (*skinned* / *butchered* / *extracted*) that newly appears on a
        previously-seen corpse means that action happened since the last search,
        so the loot flushed here inherits that activity. A corpse first seen
        already showing the verb -- or searched twice with it unchanged -- is not
        a fresh action and stays ``Looting``.
        """
        new_extra = event.extractions or {}
        seen_before = False
        prev_extra: dict[str, str] = {}
        if event.entity_id is not None:
            self.entity_monsters[event.entity_id] = event.monster
            if event.entity_id in self._corpse_extra:
                seen_before = True
                prev_extra, _ = self._corpse_extra[event.entity_id]
            self._corpse_extra[event.entity_id] = (new_extra, event.time_ms)
        self._prune_corpse_extra(event.time_ms)
        if event.entity_id is not None and event.entity_id != self.current_window_entity:
            # A corpse we never opened a window for; record the mapping only.
            return
        just_skinned = seen_before and "skinned" in new_extra and "skinned" not in prev_extra
        just_butchered = seen_before and "butchered" in new_extra and "butchered" not in prev_extra
        just_extracted = seen_before and "extracted" in new_extra and "extracted" not in prev_extra
        self.killer = event.killer
        self.participants = event.participants
        if self.current_monster != event.monster:
            self.current_encounter_uuid = str(uuid.uuid4())
            self.current_monster = event.monster
        self.last_packet_time = event.time_ms
        self._flush(
            event.time_ms,
            just_skinned=just_skinned,
            just_butchered=just_butchered,
            just_extracted=just_extracted,
            activity_window_s=self.activity_window_seconds,
        )

    def note_item_code(self, event: ItemCode) -> None:
        self.item_codes[event.instance_id] = event.code

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
        produced = [self._orphan_drop(r) for r in self._reconcile(expired)]
        self.pending = remaining
        return produced

    def finalize(self) -> list[LootDrop]:
        """Flush any remaining pending drops (end of stream)."""
        for fact in self._reconcile(self.pending):
            self.drops.append(
                LootDrop(
                    time_ms=fact.time_ms,
                    source=self.current_monster or GROUND,
                    encounter_uuid=self.current_encounter_uuid,
                    activity=self._hint_activity(fact.time_ms) or "Looting",
                    item=fact.item,
                    amount=fact.amount,
                    status=("Linked" if self.current_monster is not None else "Missed" if fact.missed else "Linked"),
                    lag_ms=0,
                    zone=self.current_zone,
                    linked_via="monster" if self.current_monster is not None else "orphan",
                    monster_name=self.current_monster,
                    monster_lag_ms=0,
                    instance_id=fact.instance_id,
                    entity_id=fact.entity_id,
                    item_code_id=fact.item_code_id,
                    item_display=fact.display_name,
                    missed=fact.missed,
                    killer_json=self._killer_json() if self.current_monster is not None else None,
                )
            )
        self.pending.clear()
        return list(self.drops)

    # -- internal helpers ---------------------------------------------------------

    def _killer_json(self) -> str | None:
        if not self.participants:
            return None
        return json.dumps({"killer": self.killer, "participants": self.participants}, sort_keys=True)

    def _item_code(self, instance_id: int | None) -> int | None:
        if instance_id is None:
            return None
        return self.item_codes.get(instance_id)

    def _prune_sightings(self) -> None:
        if not self.pending:
            return
        oldest_drop = min(drop.time_ms for drop in self.pending)
        cutoff = oldest_drop - int(self.buffer_seconds * 1000)
        while self.sightings and self.sightings[0].time_ms < cutoff:
            self.sightings.popleft()

    def _prune_sources(self) -> None:
        if not self.pending:
            return
        oldest_drop = min(drop.time_ms for drop in self.pending)
        window_ms = int(max(self.buffer_seconds, self.search_corroboration_seconds) * 1000)
        cutoff = oldest_drop - window_ms
        while self.sources and self.sources[0].time_ms < cutoff:
            self.sources.popleft()

    def _corroborated_by_search(self, drop_time_ms: int, name: str) -> bool:
        """Whether a same-name corpse-search packet precedes the drop within the window."""
        window_ms = int(self.search_corroboration_seconds * 1000)
        for source in self.sources:
            lag = drop_time_ms - source.time_ms
            if 0 <= lag <= window_ms and source.monster == name:
                return True
        return False

    def _prune_corpse_extra(self, now_ms: int) -> None:
        """Forget corpse-description state older than the buffer window."""
        window = int(max(self.buffer_seconds, self.activity_window_seconds) * 1000)
        stale = [eid for eid, (_, seen_at) in self._corpse_extra.items() if now_ms - seen_at > window]
        for eid in stale:
            del self._corpse_extra[eid]

    def _hint_activity(self, drop_time_ms: int) -> str | None:
        """Activity marked by a recent chat status line, if the drop is within the window."""
        if self._activity_hint is None:
            return None
        activity, marker_ms = self._activity_hint
        window = int(self.activity_window_seconds * 1000)
        if abs(drop_time_ms - marker_ms) <= window:
            return activity
        return None

    def _orphan_source(self, drop_time_ms: int) -> tuple[str, float]:
        """Best matching target sighting within the fallback window, else Ground/Unknown."""
        best_name = GROUND
        best_lag = _INF
        window = min(self.buffer_seconds, self.target_fallback_seconds)
        for sighting in self.sightings:
            lag = (drop_time_ms - sighting.time_ms) / 1000.0
            if 0.0 <= lag <= window and lag < best_lag:
                best_name = sighting.name
                best_lag = lag
        return best_name, best_lag

    def _orphan_drop(self, fact: _Reconciled, activity_override: str | None = None) -> LootDrop:
        """Build a lone/orphaned drop using the nearest target sighting.

        ``activity_override`` pins the drop's activity (e.g. to a chat activity
        marker) regardless of whether the corpse-search corroboration classifies
        it as corpse loot or a harvestable.
        """
        orphan_name, orphan_lag = self._orphan_source(fact.time_ms)
        linked = orphan_name != GROUND
        corroborated = linked and self._corroborated_by_search(fact.time_ms, orphan_name)
        if activity_override is None:
            activity = self._hint_activity(fact.time_ms)
            if activity is None:
                activity = "Looting" if corroborated else "Harvesting"
        else:
            activity = activity_override
        status = "Linked" if linked else "Orphaned"
        lag_ms = round(orphan_lag * 1000) if orphan_lag != _INF else 0
        return LootDrop(
            time_ms=fact.time_ms,
            source=orphan_name,
            encounter_uuid=str(uuid.uuid4()),
            activity=activity,
            item=fact.item,
            amount=fact.amount,
            status=status,
            lag_ms=lag_ms,
            zone=self.current_zone,
            linked_via="target" if linked else "orphan",
            monster_name=self.current_monster,
            monster_lag_ms=None,
            target_name=None if orphan_name == GROUND else orphan_name,
            target_lag_ms=None if orphan_lag == _INF else round(orphan_lag * 1000),
            corroborated_by_search=corroborated,
            instance_id=fact.instance_id,
            entity_id=fact.entity_id,
            item_code_id=fact.item_code_id,
            item_display=fact.display_name,
            missed=fact.missed,
        )

    def _reconcile(self, events: list[LootEvent]) -> list[_Reconciled]:
        """Deduplicate chat and Unity reports of the same pickup.
    
        Chat and Unity facts for the same physical pickup share a whole-second
        timestamp. Within each second bucket we pair them up (order-preserving
        when the counts match, otherwise by fuzzy token similarity) so the
        canonical display name and quantity from chat are joined to the Unity
        instance/entity identity. Unmatched facts pass through unchanged.
        """
        if not events:
            return []
        buckets: dict[int, list[LootEvent]] = {}
        for event in events:
            buckets.setdefault(event.time_ms - event.time_ms % 1000, []).append(event)
    
        reconciled: list[_Reconciled] = []
        for events_in_second in buckets.values():
            chats = [e for e in events_in_second if e.source_class == "chat" and not e.missed]
            unis = [e for e in events_in_second if e.source_class == "unity" and not e.missed]
            missed = [e for e in events_in_second if e.missed]
    
            pairs: list[tuple[LootEvent, LootEvent]] = []
            used_chat: set[int] = set()
            used_uni: set[int] = set()
    
            # Pass 1: exact token matches.
            for i, uni in enumerate(unis):
                for j, chat in enumerate(chats):
                    if j in used_chat or i in used_uni:
                        continue
                    if _token(uni.item) == _token(chat.item):
                        pairs.append((chat, uni))
                        used_chat.add(j)
                        used_uni.add(i)
                        break
    
            # Pass 2: single remaining each -> same pickup.
            rem_uni = [i for i in range(len(unis)) if i not in used_uni]
            rem_chat = [j for j in range(len(chats)) if j not in used_chat]
            if len(rem_uni) == len(rem_chat) and len(rem_uni) == 1:
                pairs.append((chats[rem_chat[0]], unis[rem_uni[0]]))
                used_uni.add(rem_uni[0])
                used_chat.add(rem_chat[0])
    
            # Pass 3: fuzzy best-match for the remainder.
            for i in list(rem_uni):
                best_j, best_score = None, 0.0
                for j in rem_chat:
                    if j in used_chat:
                        continue
                    score = _fuzzy_score(unis[i].item, chats[j].item)
                    if score > best_score:
                        best_score, best_j = score, j
                if best_j is not None and best_score >= 85.0:
                    pairs.append((chats[best_j], unis[i]))
                    used_uni.add(i)
                    used_chat.add(best_j)

            rem_uni = [i for i in rem_uni if i not in used_uni]
            rem_chat = [j for j in rem_chat if j not in used_chat]

            for chat, uni in pairs:
                reconciled.append(
                    _Reconciled(
                        time_ms=chat.time_ms,
                        item=chat.item,
                        amount=max(chat.amount, uni.amount),
                        source_class="unity",
                        instance_id=uni.instance_id,
                        entity_id=uni.entity_id or chat.entity_id,
                        item_code_id=uni.item_code_id or self._item_code(uni.instance_id),
                        display_name=uni.item,
                        missed=False,
                    )
                )
            for j in rem_chat:
                chat = chats[j]
                reconciled.append(
                    _Reconciled(
                        time_ms=chat.time_ms,
                        item=chat.item,
                        amount=chat.amount,
                        source_class="chat",
                        instance_id=chat.instance_id,
                        entity_id=chat.entity_id,
                        item_code_id=chat.item_code_id,
                        display_name=None,
                        missed=chat.missed,
                    )
                )
            for i in rem_uni:
                uni = unis[i]
                reconciled.append(
                    _Reconciled(
                        time_ms=uni.time_ms,
                        item=infer_display(uni.item),
                        amount=uni.amount,
                        source_class="unity",
                        instance_id=uni.instance_id,
                        entity_id=uni.entity_id,
                        item_code_id=uni.item_code_id or self._item_code(uni.instance_id),
                        display_name=uni.item,
                        missed=False,
                    )
                )
            for event in missed:
                reconciled.append(
                    _Reconciled(
                        time_ms=event.time_ms,
                        item=event.item,
                        amount=event.amount,
                        source_class=event.source_class,
                        instance_id=event.instance_id,
                        entity_id=event.entity_id,
                        item_code_id=event.item_code_id,
                        display_name=event.display_name,
                        missed=True,
                    )
                )
        return reconciled

    def _flush(
        self,
        ref_time_ms: int,
        just_skinned: bool = False,
        just_butchered: bool = False,
        just_extracted: bool = False,
        activity_window_s: float | None = None,
    ) -> None:
        # Packet can_skin/butcher/extract transitions keep the legacy 0.9s retro
        # window; corpse-description transitions (whole-second Player.log stamps)
        # use the wider activity window.
        window_s = self.retroactive_threshold if activity_window_s is None else activity_window_s
        self._prune_sources()
        for fact in self._reconcile(self.pending):
            if self.current_monster is not None and ref_time_ms is not None:
                monster_lag = (ref_time_ms - fact.time_ms) / 1000.0
            else:
                monster_lag = _INF
            hint_activity = self._hint_activity(fact.time_ms)
            orphan_name, orphan_lag = self._orphan_source(fact.time_ms)

            if monster_lag <= self.buffer_seconds and monster_lag < orphan_lag:
                activity = "Looting"
                if just_skinned and monster_lag <= window_s:
                    activity = "Skinning"
                elif just_butchered and monster_lag <= window_s:
                    activity = "Butchering"
                elif just_extracted and monster_lag <= window_s:
                    activity = "Extracting"
                elif hint_activity is not None and monster_lag <= self.activity_window_seconds:
                    activity = hint_activity
                self.drops.append(
                    LootDrop(
                        time_ms=fact.time_ms,
                        source=self.current_monster or GROUND,
                        encounter_uuid=self.current_encounter_uuid,
                        activity=activity,
                        item=fact.item,
                        amount=fact.amount,
                        status="Linked" if not fact.missed else "Missed",
                        lag_ms=round(monster_lag * 1000),
                        zone=self.current_zone,
                        linked_via="monster",
                        monster_name=self.current_monster,
                        monster_lag_ms=round(monster_lag * 1000),
                        target_name=None if orphan_name == GROUND else orphan_name,
                        target_lag_ms=None if orphan_lag == _INF else round(orphan_lag * 1000),
                        instance_id=fact.instance_id,
                        entity_id=fact.entity_id,
                        item_code_id=fact.item_code_id,
                        item_display=fact.display_name,
                        missed=fact.missed,
                        killer_json=self._killer_json() if self.current_monster is not None else None,
                    )
                )
            else:
                drop = self._orphan_drop(fact, activity_override=hint_activity)
                if fact.missed:
                    drop = _missed_copy(drop)
                self.drops.append(drop)
        self.pending.clear()