"""Configuration loading and validation for gorgon-tracker."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DbConfig(BaseModel):
    path: str = "data/gorgon.db"


class CaptureConfig(BaseModel):
    tshark_path: str = "tshark"
    interface: str = "auto"
    ports: list[int] = Field(default_factory=list)
    bpf: str = ""


class ChatConfig(BaseModel):
    log_dir: str = ""
    tail: bool = True
    poll_interval_s: float = 1.0
    tail_from_start: bool = False


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


class TrackerConfig(BaseModel):
    db: DbConfig = Field(default_factory=DbConfig)
    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    ocr: OcrConfig = Field(default_factory=OcrConfig)
    correlate: CorrelateConfig = Field(default_factory=CorrelateConfig)


_PROTON_CHAT_SUFFIX = (
    "steamapps/compatdata/1118200/pfx/drive_c/users/steamuser/"
    "AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
)

_CONFIG_FILE_CANDIDATES = (Path("gorgon-tracker.toml"), Path.home() / ".config/gorgon-tracker/config.toml")


def default_chat_log_dir() -> str:
    """Return the first existing Proton chat-log directory found, or empty string."""
    for base in (
        Path.home() / ".local/share/Steam",
        Path.home() / ".steam/steam",
        Path.home() / ".steam/root",
        Path.home() / "Games/Steam",
    ):
        candidate: Path = base / _PROTON_CHAT_SUFFIX
        if candidate.is_dir():
            return str(candidate)
    return ""


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


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

    merged = _merge(TrackerConfig().model_dump(), data)
    chat = merged["chat"]
    if not chat.get("log_dir"):
        chat["log_dir"] = default_chat_log_dir()
    cfg = TrackerConfig.model_validate(merged)
    cfg.db.path = str(Path(cfg.db.path).expanduser().resolve())
    return cfg