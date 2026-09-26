"""Configuration loading and validation for gorgon-tracker."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DbConfig(BaseModel):
    path: str = "data/gorgon.db"


class CaptureConfig(BaseModel):
    enabled: bool = True
    tshark_path: str = "tshark"
    interface: str = "auto"
    ports: list[int] = Field(default_factory=list)
    bpf: str = ""


class ChatConfig(BaseModel):
    log_dir: str = ""
    tail: bool = True
    poll_interval_s: float = 1.0
    tail_from_start: bool = False


class PlayerLogConfig(BaseModel):
    """Unity ``Player.log`` tailing (authoritative loot facts, corpse attribution)."""

    path: str = ""
    tail: bool = True
    poll_interval_s: float = 1.0
    tail_from_start: bool = False
    backfill_prev: bool = False


class OcrRegionConfig(BaseModel):
    region: list[int] = Field(default_factory=lambda: [0, 0, 100, 100])
    interval_s: float = 5.0
    heartbeat_s: float | None = None

    @field_validator("region")
    @classmethod
    def _region_must_be_x_y_w_h(cls, v: list[int]) -> list[int]:
        if len(v) != 4 or any(x < 0 for x in v):
            raise ValueError("region must be [x, y, width, height] with non-negative integers")
        return v


class OcrConfig(BaseModel):
    enabled: bool = True
    tesseract_path: str = "tesseract"
    lang: str = "eng"
    zones: OcrRegionConfig = Field(
        default_factory=lambda: OcrRegionConfig(region=[1680, 0, 180, 50], interval_s=5.0, heartbeat_s=30.0)
    )
    targets: OcrRegionConfig = Field(
        default_factory=lambda: OcrRegionConfig(region=[1021, 691, 213, 114], interval_s=0.5, heartbeat_s=None)
    )


class CorrelateConfig(BaseModel):
    buffer_seconds: float = 10.0
    session_timeout: float = 3.0
    retroactive_threshold: float = 0.9
    # How close to a corpse-description transition (Unity Player.log `skinned/
    # butchered/extracted` line) or a chat status marker a drop must be to inherit
    # that activity. The Unity log stamps whole seconds, so a pickup and the
    # description update naming the action can be ~1s apart (the 0.9s retroactive
    # threshold is tuned to packet timing and stays for the packet path).
    activity_window_seconds: float = 2.0
    # How stale a target sighting may be to compete with (or substitute for) a
    # monster source. Looting/harvesting targets the entity being looted, so a
    # fresh sighting is strong evidence; old sightings are coincidence risk.
    target_fallback_seconds: float = 3.0
    # A target-linked drop within this many seconds of a same-name corpse search
    # is considered corpse loot rather than a harvestable.
    search_corroboration_seconds: float = 2.0


class NamesKindConfig(BaseModel):
    ratio: float = 90.0
    partial_ratio: float = 85.0

    @field_validator("ratio", "partial_ratio")
    @classmethod
    def _ratio_percent(cls, v: float) -> float:
        if not 0 < v <= 100:
            raise ValueError("ratio must be a percentage in (0, 100]")
        return v


class NamesConfig(BaseModel):
    enabled: bool = True
    data_dir: str = ""
    zones: NamesKindConfig = Field(default_factory=NamesKindConfig)
    monsters: NamesKindConfig = Field(default_factory=NamesKindConfig)


class CatalogConfig(BaseModel):
    """Canonical item/zone catalog snapshots from the official game data CDN.

    Bundled snapshots ship with the package; a per-user snapshot can pin a
    specific game data version when ``data_dir`` is set (see ``update-catalog``).
    """

    data_dir: str = ""


class TrackerConfig(BaseModel):
    db: DbConfig = Field(default_factory=DbConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    playerlog: PlayerLogConfig = Field(default_factory=PlayerLogConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    correlate: CorrelateConfig = Field(default_factory=CorrelateConfig)
    names: NamesConfig = Field(default_factory=NamesConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)


_PROTON_CHAT_SUFFIX = (
    "steamapps/compatdata/342940/pfx/drive_c/users/steamuser/"
    "AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
)

_PLAYERLOG_RELATIVE = Path("AppData/LocalLow/Elder Game/Project Gorgon/Player.log")
_PROTON_PLAYERLOG_SUFFIX = f"steamapps/compatdata/342940/pfx/drive_c/users/steamuser/{_PLAYERLOG_RELATIVE}"

_CONFIG_FILE_CANDIDATES = (Path("gorgon-tracker.toml"), Path.home() / ".config/gorgon-tracker/config.toml")


def _vdf_library_paths(text: str) -> list[str]:
    """Parse Steam's ``libraryfolders.vdf`` into its library root paths."""
    paths: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('"path"'):
            continue
        start = stripped.find('"', len('"path"'))
        if start == -1:
            continue
        end = stripped.find('"', start + 1)
        if end == -1:
            continue
        paths.append(stripped[start + 1 : end].replace("\\\\", "\\"))
    return paths


def _steam_roots(platform: str) -> list[Path]:
    """Candidate Steam install/library roots for the given platform."""
    if platform == "win32":
        userprofile = os.environ.get("USERPROFILE")
        return [Path(userprofile)] if userprofile else []
    home = Path.home()
    return [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
        home / "Games/Steam",
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / "snap/steam/common/.local/share/Steam",
    ]


def default_chat_log_dir(platform: str = "auto") -> str:
    """Return the first existing Project Gorgon chat-log directory, or empty string.

    On Windows the chat logs live natively under ``%USERPROFILE%\\AppData\\LocalLow``.
    On Linux/macOS the game runs under Proton, so we probe every Steam library root
    (default install dirs plus any additional folders listed in
    ``steamapps/libraryfolders.vdf``) for the compatdata prefix.
    """
    if platform == "auto":
        platform = sys.platform
    if platform == "win32":
        for base in _steam_roots(platform):
            candidate = base / "AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
            if candidate.is_dir():
                return str(candidate)
        return ""
    for base in _steam_library_candidates(platform):
        candidate = base / _PROTON_CHAT_SUFFIX
        if candidate.is_dir():
            return str(candidate)
    return ""


def default_player_log_path(platform: str = "auto") -> str:
    """Return the game's Unity ``Player.log`` path, or empty string when unknown.

    Derived from the discovered chat-log directory when possible; otherwise the
    standard Steam/Proton install roots are probed directly.
    """
    if platform == "auto":
        platform = sys.platform
    chat_dir = default_chat_log_dir(platform)
    if chat_dir:
        candidate = Path(chat_dir).parent / "Player.log"
        if candidate.is_file():
            return str(candidate)
    if platform == "win32":
        for base in _steam_roots(platform):
            candidate = base / _PLAYERLOG_RELATIVE
            if candidate.is_file():
                return str(candidate)
        return ""
    for base in _steam_library_candidates(platform):
        candidate = base / _PROTON_PLAYERLOG_SUFFIX
        if candidate.is_file():
            return str(candidate)
    return ""


def _steam_library_candidates(platform: str) -> list[Path]:
    """Steam library roots plus any additional folders from libraryfolders.vdf."""
    candidates: list[Path] = []
    for steam_root in _steam_roots(platform):
        candidates.append(steam_root)
        vdf = steam_root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for path in _vdf_library_paths(vdf.read_text(encoding="utf-8", errors="replace")):
                if path:
                    candidates.append(Path(path))
    seen: set[Path] = set()
    resolved_candidates: list[Path] = []
    for base in candidates:
        resolved = base.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        resolved_candidates.append(resolved)
    return resolved_candidates


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def config_from_dict(data: dict[str, Any]) -> TrackerConfig:
    """Build and validate a :class:`TrackerConfig` from raw TOML data (merged over defaults)."""
    merged = _merge(TrackerConfig().model_dump(), data)
    chat = merged["chat"]
    if not chat.get("log_dir"):
        chat["log_dir"] = default_chat_log_dir()
    playerlog = merged["playerlog"]
    if not playerlog.get("path"):
        playerlog["path"] = default_player_log_path()
    cfg = TrackerConfig.model_validate(merged)
    cfg.db.path = str(Path(cfg.db.path).expanduser().resolve())
    return cfg


def load_config(path: str | None = None) -> TrackerConfig:
    """Load configuration from an explicit path, env var, or the default candidates."""
    explicit: str | None = path
    if explicit is None:
        explicit = os.environ.get("GORGON_TRACKER_CONFIG")

    data: dict[str, Any] = {}
    if explicit:
        config_path = Path(explicit).expanduser()
        if not config_path.is_file():
            raise FileNotFoundError(f"config file not found: {config_path}")
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
    else:
        for candidate in _CONFIG_FILE_CANDIDATES:
            if candidate.is_file():
                with candidate.open("rb") as fh:
                    data = tomllib.load(fh)
                break

    return config_from_dict(data)


def effective_config_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return the effective (defaults-merged) config as a plain dict, for JSON APIs."""
    return config_from_dict(data).model_dump()