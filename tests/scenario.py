"""Builds the deterministic Phase-1 golden scenario (timezone-independent).

All absolute times are defined relative to a fixed UTC base ``B``. Wall-clock
strings are rendered in a way the supported formats expect:

* chat log lines use local two-digit-year wall time (`yy-MM-dd HH:mm:ss`);
* OCR zone/target CSVs use UTC wall time with milliseconds (`yyyy-MM-dd HH:mm:ss.fff`);
* the Unity ``Player.log`` fixture stamps `[HH:MM:SS]` UTC with a login anchor.

This keeps the golden output identical on any host timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

BASE_MS = int(datetime(2026, 1, 11, 20, 0, 0, tzinfo=UTC).timestamp() * 1000)


def at(seconds: float) -> int:
    return BASE_MS + round(seconds * 1000)


def local_wall(seconds: float, with_ms: bool = False) -> str:
    dt = datetime.fromtimestamp(at(seconds) / 1000)
    if with_ms:
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return dt.strftime("%y-%m-%d %H:%M:%S")


def utc_wall(seconds: float, with_ms: bool = True) -> str:
    dt = datetime.fromtimestamp(at(seconds) / 1000, tz=UTC)
    if with_ms:
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def pl(seconds: float, body: str) -> str:
    """Render one ``Player.log`` line with a ``[HH:MM:SS]`` UTC stamp."""
    return f"[{utc_wall(seconds, with_ms=False).split()[1]}] {body}"


def interaction(seconds: float, entity_id: int) -> str:
    return pl(seconds, f'LocalPlayer: ProcessStartInteraction({entity_id}, 13.5, 0, False, "")')


def corpse_search(seconds: float, entity_id: int, monster: str) -> str:
    return pl(
        seconds,
        f'LocalPlayer: ProcessTalkScreen({entity_id}, "Search Corpse of {monster}", '
        '"", "", [], System.String[], 1, Corpse)',
    )


def bury(seconds: float) -> str:
    return pl(seconds, 'LocalPlayer: ProcessScreenText(GeneralInfo, "You bury the corpse.")')


LOGIN = (
    "Logged in as character Tester. Time UTC=01/11/2026 20:00:00. Timezone Offset +00:00:00."
)

# Timeline: corpse windows open with an interaction, name the monster on a
# corpse-search screen, and close with a bury.
PLAYER_LOG_LINES = [
    pl(0.0, LOGIN),
    interaction(1.0, 501),
    corpse_search(2.0, 501, "Giant Bat"),
    bury(6.0),
    interaction(7.0, 502),
    corpse_search(8.0, 502, "Dire Wolf"),
    corpse_search(10.0, 502, "Dire Wolf"),
    bury(13.0),
    interaction(16.0, 503),
    corpse_search(20.0, 503, "Giant Bat"),
    corpse_search(21.0, 503, "Giant Bat"),
    interaction(30.0, 504),
    corpse_search(31.0, 504, "Deer"),
    bury(34.0),
    interaction(40.0, 505),
    corpse_search(41.0, 505, "Deer"),
    bury(43.0),
]

ZONE_ROWS = [
    (0.0, "Old Graveyard"),
    (7.0, "Fairy Glen"),
]

TARGET_ROWS = [
    (1.0, "Giant Bat"),
    (12.0, "Dire Wolf"),
]

# Chat log lines are whole-second resolution (legacy format).
# (seconds, item, amount, marker) where marker is None, "bury", or a verb.
CHAT_LINES = [
    (3.0, "Bat Guano", 1, None),
    (9.0, "Wolf Pelt", 2, None),
    (12.0, "Ground Twig", 1, None),
    (20.0, "Bat Wing", 1, None),
    (32.0, None, None, "skin"),
    (33.0, "Crude Animal Skin", 1, None),
    (42.0, None, None, "skin"),
    (60.0, "PostWindow Item", 1, None),
]


@dataclass
class ScenarioFiles:
    base_ms: int
    player_log: Path
    chat_log: Path
    zones_csv: Path
    targets_csv: Path


def build(tmp_path: Path) -> ScenarioFiles:
    tmp_path.mkdir(parents=True, exist_ok=True)
    player_log = tmp_path / "Player.log"
    player_log.write_text("\n".join(PLAYER_LOG_LINES) + "\n")

    chat = tmp_path / "chatsession.log"
    lines = []
    verbs = {"skin": "skin", "butcher": "butcher", "extract": "extract"}
    for seconds, item, amount, marker in CHAT_LINES:
        if marker == "bury":
            lines.append(f"{local_wall(seconds)} [Status] You bury the corpse.")
        elif marker:
            lines.append(f"{local_wall(seconds)} [Status] You {verbs[marker]} the corpse.")
        else:
            lines.append(f"{local_wall(seconds)} [Status] {item} x{amount} added to inventory.")
    chat.write_text("\n".join(lines) + "\n")

    zones = tmp_path / "zones.csv"
    zones.write_text(
        "Time,Text\n" + "\n".join(f"{utc_wall(seconds)},{zone}" for seconds, zone in ZONE_ROWS) + "\n"
    )

    targets = tmp_path / "targets.csv"
    targets.write_text(
        "Time,Text\n" + "\n".join(f"{utc_wall(seconds)},{name}" for seconds, name in TARGET_ROWS) + "\n"
    )

    return ScenarioFiles(base_ms=BASE_MS, player_log=player_log, chat_log=chat, zones_csv=zones, targets_csv=targets)