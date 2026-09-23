"""Builds the deterministic Phase-1 golden scenario (timezone-independent).

All absolute times are defined relative to a fixed UTC base ``B``. Wall-clock
strings are rendered in a way the legacy formats expect:

* chat log lines use local two-digit-year wall time (`yy-MM-dd HH:mm:ss`);
* OCR zone/target CSVs use UTC wall time with milliseconds (`yyyy-MM-dd HH:mm:ss.fff`);
* packet JSON frames carry an absolute ``frame.time_epoch``.

This keeps the golden output identical on any host timezone.
"""

from __future__ import annotations

import json
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


def hexify(text: str) -> str:
    return ":".join(f"{ord(ch):02x}" for ch in text)


def frame_json(seconds: float, payload: str) -> dict:
    epoch = at(seconds) / 1000
    display = datetime.fromtimestamp(epoch).strftime("%b %d, %Y %H:%M:%S.%f")
    return {
        "_source": {
            "layers": {
                "frame": {
                    "frame.time": display,
                    "frame.time_epoch": f"{epoch:.9f}",
                },
                "tcp": {"tcp.payload": hexify(payload)},
            }
        }
    }


# Timeline: (seconds, kind, detail)
CAPTURE_FRAMES = [
    frame_json(2.0, "Search Corpse of Giant Bat\nSkin Corpse\n"),
    frame_json(4.0, "Search Corpse of Giant Bat\n"),
    frame_json(8.0, "Search Corpse of Dire Wolf\nButcher Corpse\n"),
    frame_json(10.0, "Search Corpse of Dire Wolf\n"),
    frame_json(16.0, "Search Corpse of Giant Bat\nSkin Corpse\n"),
    frame_json(20.0, "Search Corpse of Giant Bat\nSkin Corpse\n"),
    frame_json(21.0, "Search Corpse of Giant Bat\n"),
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
CHAT_LINES = [
    (1.0, "PreWindow Item", 1),
    (3.0, "Bat Guano", 1),
    (6.0, None, None),  # bury
    (9.0, "Wolf Pelt", 2),
    (12.0, "Ground Twig", 1),
    (13.0, None, None),  # bury
    (20.0, "Bat Wing", 1),
    (35.0, "PostWindow Item", 1),
]


@dataclass
class ScenarioFiles:
    base_ms: int
    capture_json: Path
    chat_log: Path
    zones_csv: Path
    targets_csv: Path


def build(tmp_path: Path) -> ScenarioFiles:
    tmp_path.mkdir(parents=True, exist_ok=True)
    capture = tmp_path / "capture.json"
    capture.write_text("[\n" + ",\n".join(f"  {json.dumps(frame)}" for frame in CAPTURE_FRAMES) + "\n]\n")

    chat = tmp_path / "chatsession.log"
    lines = []
    for seconds, item, amount in CHAT_LINES:
        if item is None:
            lines.append(f"{local_wall(seconds)} [Status] You bury the corpse.")
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

    return ScenarioFiles(base_ms=BASE_MS, capture_json=capture, chat_log=chat, zones_csv=zones, targets_csv=targets)