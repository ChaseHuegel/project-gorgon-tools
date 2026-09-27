"""Parse Project Gorgon's Unity ``Player.log`` into loot-correlation events.

The game writes ``Player.log`` (sibling of ``ChatLogs/``, rotated to
``Player-prev.log`` at every launch) in *UTC* wall time, so line stamps are
converted to absolute epoch milliseconds using the session's own clock anchor::

    [03:12:22] Logged in as character Mennelaia. Time UTC=09/24/2026 03:12:22.
               Timezone Offset -04:00:00

.. note:: The live source seeds this anchor from the file's existing login line
   at start and on rotation. A file with no login line (partial replay) falls
   back to the current UTC wall-clock date so absolute times stay plausible.

Most of the file is asset/appearance download noise; only the small set of
``LocalPlayer: Process*`` lines plus the session/area markers are kept.

Corpse loot arrives as a tight window (verified against real sessions)::

    ProcessStartInteraction(996594, 13.5, 0, False, "")
    ProcessAddItem(GoblinCallingCard15(-1719916789), -1, True)   # picked into inventory
    ProcessRemoveLoot(-1719916789)                               # removed off the corpse
    ProcessTalkScreen(996594, "Search Corpse of Goblin Horsebeater", "...", ..., Corpse)
    ProcessScreenText(GeneralInfo, "You bury the corpse.")

The third ``ProcessAddItem`` argument distinguishes real pickups (``True``)
from login-time inventory loads (``False``). A corpse item whose ``RemoveLoot``
iid never matches a pickup during the window was NOT collected (inventory
full) and becomes ``LootEvent(missed=True)``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..correlator import BuryEvent, CorpseSearch, InteractionStart, LootEvent, ZoneChange

LOGIN_RE = re.compile(
    r"Logged in as character (?P<name>[A-Za-z' ]+)\. "
    r"Time UTC=(?P<utc>\d\d/\d\d/\d{4} \d\d:\d\d:\d\d)\. "
    r"Timezone Offset (?P<off>[+-]?\d\d):(?P<off_min>\d\d)\.?"
)
STAMP_RE = re.compile(r"^\[(?P<h>\d\d):(?P<m>\d\d):(?P<s>\d\d)\]")

ADD_ITEM_RE = re.compile(
    r"LocalPlayer: ProcessAddItem\((?P<item>[^(]+)\((?P<iid>-?\d+)\),\s*-1,\s*(?P<new>True|False)\)"
)
REMOVE_LOOT_RE = re.compile(r"LocalPlayer: ProcessRemoveLoot\((?P<iid>-?\d+)\)")
START_INTERACTION_RE = re.compile(
    r"LocalPlayer: ProcessStartInteraction\((?P<eid>-?\d+),\s*[\d.]+,\s*0,\s*\w+,\s*\"[^\"]*\"\)"
)
TALK_SCREEN_TITLE_RE = re.compile(
    r'LocalPlayer: ProcessTalkScreen\((?P<eid>-?\d+),\s*"(?P<title>Search Corpse of [^"]+)"'
)
KILLER_RE = re.compile(r"<em>Killer:</em>\s*([^<;\n]+)")
PARTICIPANT_RE = re.compile(
    r"\s*([^:\n]+):\s*(\d+) health dmg(?: (\d+) armor dmg)?\.\s*Aggro \(at death\):\s*([\d.]+)%?"
)
EXTRACT_RE = re.compile(r"\s*(\S+) (extracted|skinned|butchered|harvested) (.+?) from the corpse\b")
REWARD_RE = re.compile(r"\s*(\S+) (skinned|butchered|extracted) the corpse\b.*?\band obtained (?P<items>[^\"().]+)")
ERROR_MESSAGE_RE = re.compile(r'LocalPlayer: ProcessErrorMessage\((InventoryFull),\s*"[^"]*"\)')
SCREEN_TEXT_RE = re.compile(
    r'LocalPlayer: ProcessScreenText\((GeneralInfo|CombatInfo),\s*"(?P<msg>[^"]*)"\)'
)
BURY_MSG = "You bury the corpse."
COINS_RE = re.compile(r"You searched the corpse and found (?P<n>\d+) coins?\.?$")
LOADING_LEVEL_RE = re.compile(r"LOADING LEVEL (?P<area>Area[\w ']+)$")

_area_names_cache: dict[str, str] | None = None


def _area_name_map() -> dict[str, str]:
    """Internal area id -> friendly name from the bundled zone catalog (memoized)."""
    global _area_names_cache
    if _area_names_cache is None:
        from .. import catalog as catalog_mod

        _area_names_cache = {
            area_id: zone.name for area_id, zone in catalog_mod.zone_catalog().by_id.items()
        }
    return _area_names_cache


@dataclass
class _Window:
    entity_id: int | None
    # iids removed off the corpse (via RemoveLoot) not yet confirmed in inventory.
    removals: set[int] = field(default_factory=set)
    # iids seen in both RemoveLoot and a pickup; excluded from missed detection.
    collected: set[int] = field(default_factory=set)


class PlayerLogParser:
    """Stateful parser for a continuous Player.log stream.

    One instance should live for the lifetime of the followed game session:
    the UTC anchor date, corpse-interaction window, and pending removals are
    tracked across ``feed`` calls so live tailing and offline replay behave
    identically.

    ``area_names`` (internal area id -> friendly name) defaults to the bundled
    zone catalog so ``LOADING LEVEL AreaSerbule2`` is reported as its
    player-visible name (``Serbule Hills``) rather than a raw id.
    """

    def __init__(self, area_names: dict[str, str] | None = None) -> None:
        self._anchor: datetime | None = None
        self._last_epoch_ms: int | None = None
        self._window: _Window | None = None
        self._area_names = area_names

    # -- clock ---------------------------------------------------------------

    def _line_ms(self, h: int, m: int, s: int) -> int:
        # No login line seen (e.g. live capture started mid-session, or a partial
        # replay): anchor the date to the current UTC wall clock so absolute
        # timestamps are plausible for cross-source merging.
        base_date = datetime.now(UTC).date() if self._anchor is None else self._anchor.date()
        base = datetime(base_date.year, base_date.month, base_date.day, h, m, s, tzinfo=UTC)
        if self._last_epoch_ms is not None and base.timestamp() * 1000 < self._last_epoch_ms - 60_000:
            base = base + timedelta(days=1)
        ms = round(base.timestamp() * 1000)
        self._last_epoch_ms = ms
        return ms

    def set_anchor_from(self, lines: Iterable[str]) -> None:
        """Seed the UTC date anchor from the last login line in ``lines``.

        A Player.log holds one or more sessions; the final login line names the
        date the current session started. ``lines`` are scanned only for the
        anchor and not emitted, so tailing from the file end stays correct
        without re-capturing already-seen events.
        """
        anchor: datetime | None = None
        for line in lines:
            match = LOGIN_RE.search(line)
            if match:
                anchor = datetime.strptime(match.group("utc"), "%m/%d/%Y %H:%M:%S").replace(
                    tzinfo=UTC
                )
        if anchor is not None:
            self._anchor = anchor
            self._last_epoch_ms = round(anchor.timestamp() * 1000)

    def _anchor_from(self, line: str) -> bool:
        match = LOGIN_RE.search(line)
        if not match:
            return False
        self._anchor = datetime.strptime(match.group("utc"), "%m/%d/%Y %H:%M:%S").replace(tzinfo=UTC)
        self._last_epoch_ms = round(self._anchor.timestamp() * 1000)
        return True

    # -- parsing -------------------------------------------------------------

    def feed(self, line: str) -> list[object]:
        """Parse one raw log line into zero or more correlation events."""
        line = line.rstrip("\n")
        stamp = STAMP_RE.match(line)
        if stamp is None:
            if LOGIN_RE.search(line):
                self._anchor_from(line)
            return []
        time_ms = self._line_ms(int(stamp["h"]), int(stamp["m"]), int(stamp["s"]))
        if LOGIN_RE.search(line):
            self._anchor_from(line)
            return []
        if "LocalPlayer" not in line:
            if area := LOADING_LEVEL_RE.search(line):
                return [ZoneChange(time_ms=time_ms, zone=self._zone_name(area["area"]))]
            return []
        return self._process_local(line, time_ms)

    def _zone_name(self, area: str) -> str:
        """Map a ``LOADING LEVEL`` area id to its friendly name, else strip ``Area``."""
        area = area.strip()
        names = self._area_names
        if names is None:
            names = _area_name_map()
        return names.get(area) or (area.removeprefix("Area").strip() or area)

    def _process_local(self, line: str, time_ms: int) -> list[object]:
        if add := ADD_ITEM_RE.search(line):
            return self._process_add_item(add, time_ms)
        if remove := REMOVE_LOOT_RE.search(line):
            self._process_remove_loot(int(remove["iid"]))
            return []
        if m := START_INTERACTION_RE.search(line):
            return self._open_interaction(int(m["eid"]), time_ms)
        if m := TALK_SCREEN_TITLE_RE.search(line):
            killer, participants, activities, reward_items = _parse_talk_details(line)
            return self._open_corpse_search(
                int(m["eid"]), m["title"], killer, participants, activities, reward_items, time_ms
            )
        if ERROR_MESSAGE_RE.search(line):
            return self._close_window(time_ms)
        if screen := SCREEN_TEXT_RE.search(line):
            msg = screen["msg"]
            if msg == BURY_MSG:
                events = self._close_window(time_ms)
                events.append(BuryEvent(time_ms=time_ms))
                return events
            if coins := COINS_RE.search(msg):
                return [
                    LootEvent(
                        time_ms=time_ms,
                        item="Coins",
                        amount=int(coins["n"]),
                        entity_id=self._window.entity_id if self._window else None,
                        source_class="unity",
                    )
                ]
        return []

    def _process_add_item(self, add: re.Match[str], time_ms: int) -> list[object]:
        if add["new"] != "True":
            return []
        iid = int(add["iid"])
        if self._window is not None:
            self._window.removals.discard(iid)
            self._window.collected.add(iid)
        return [
            LootEvent(
                time_ms=time_ms,
                item=add["item"].strip(),
                amount=1,
                instance_id=iid,
                entity_id=self._window.entity_id if self._window else None,
                source_class="unity",
            )
        ]

    def _process_remove_loot(self, iid: int) -> None:
        if self._window is None:
            return
        if iid not in self._window.collected:
            self._window.removals.add(iid)

    def _open_interaction(self, entity_id: int, time_ms: int) -> list[object]:
        events = self._close_window(time_ms)
        self._window = _Window(entity_id=entity_id)
        events.append(InteractionStart(time_ms=time_ms, entity_id=entity_id))
        return events

    def _open_corpse_search(
        self,
        entity_id: int,
        title: str,
        killer: str | None,
        participants: dict[str, dict[str, int | float]],
        activities: dict[str, str],
        reward_items: list[str] | None,
        time_ms: int,
    ) -> list[object]:
        # A reward screen ("<you> skinned the corpse ... and obtained <items>")
        # is the local player's own skinning/butchering action. Its items were
        # collected via the reward path, not stocked through a ProcessAddItem in
        # the loot window, so the window's unmatched removals are those rewards,
        # not inventory-full losses. Suppress the phantom missed emission.
        reward_same_corpse = bool(reward_items) and bool(
            self._window and self._window.entity_id == entity_id
        )
        expected = self._close_window(time_ms, suppress_missed=reward_same_corpse)
        monster = title.removeprefix("Search Corpse of ").strip()
        self._window = _Window(entity_id=entity_id)
        events = expected
        events.append(
            CorpseSearch(
                time_ms=time_ms,
                monster=monster,
                entity_id=entity_id,
                killer=killer,
                participants=participants,
                extractions=activities,
                reward_items=reward_items,
            )
        )
        return events

    def _close_window(self, time_ms: int, suppress_missed: bool = False) -> list[object]:
        """Emit missed-loot for removals that never reached inventory."""
        if self._window is None:
            return []
        events: list[object] = []
        if not suppress_missed:
            for iid in sorted(self._window.removals):
                events.append(
                    LootEvent(
                        time_ms=time_ms,
                        item="Unknown",
                        amount=1,
                        instance_id=iid,
                        entity_id=self._window.entity_id,
                        source_class="unity",
                        missed=True,
                    )
                )
        self._window = None
        return events

    def close(self) -> list[object]:
        return self._close_window(self._last_epoch_ms or 0)


def _parse_talk_details(
    line: str,
) -> tuple[str | None, dict[str, dict[str, int | float]], dict[str, str], list[str] | None]:
    """Parse a corpse-search talk screen into killer, participants, activities, reward items.

    The screen may carry one of two action descriptions:
    * ``<name> extracted <item> from the corpse.`` (any corpse's pre-existing state);
    * ``<name> <verb> the corpse (...) and obtained <item> xN plus <item>`` — the
      local player's own skinning/butchering reward, whose item names we return so
      the correlator can label drops per item.
    """
    # Unity escapes real newlines as literal backslash-n inside the logged text.
    line = line.replace("\\n", "\n")
    killer = None
    if match := KILLER_RE.search(line):
        killer = match.group(1).strip()
    participants: dict[str, dict[str, int | float]] = {}
    for match in PARTICIPANT_RE.finditer(line):
        name = match.group(1).strip()
        if not name:
            continue
        participants[name] = {
            "health": int(match.group(2)),
            "armor": int(match.group(3)) if match.group(3) else 0,
            "aggro": float(match.group(4)),
        }
    activities: dict[str, str] = {}
    reward_items: list[str] | None = None
    for match in REWARD_RE.finditer(line):
        verb = match.group(2)
        items_text = match.group("items").strip()
        activities[verb] = items_text
        names = [p.strip() for p in items_text.split(" plus ") if p.strip()]
        reward_items = [re.sub(r"\s+x\d+$", "", n) for n in names]
    for match in EXTRACT_RE.finditer(line):
        # The named-from-the-corpse form only fires when no reward form matched.
        if match.group(2) not in activities:
            activities[match.group(2)] = match.group(3).strip()
    return killer, participants, activities, reward_items


def parse_player_log_lines(lines: Iterator[str], parser: PlayerLogParser | None = None) -> Iterator[object]:
    """Parse streaming log lines into events; a persistent parser spans polls."""
    if parser is None:
        parser = PlayerLogParser()
    for line in lines:
        yield from parser.feed(line)


def parse_player_log_file(path: Path) -> list[object]:
    """Parse a whole Player.log file (opening and closing it as one session)."""
    parser = PlayerLogParser()
    events: list[object] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            events.extend(parser.feed(line))
    events.extend(parser.close())
    return events