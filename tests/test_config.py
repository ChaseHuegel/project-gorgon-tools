from pathlib import Path

import pytest
from pydantic import ValidationError

from gorgon_tracker.config import TrackerConfig, load_config


def test_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert isinstance(cfg, TrackerConfig)
    assert cfg.db.path == str((tmp_path / "data/gorgon.db").resolve())
    assert cfg.capture.interface == "auto"
    assert cfg.ocr.zones.region == [1680, 0, 180, 50]
    assert cfg.ocr.targets.interval_s == 0.5
    assert cfg.correlate.buffer_seconds == 10.0


def test_load_file_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "custom.toml"
    config_file.write_text(
        "[db]\npath = 'var/other.db'\n"
        "[ocr.zones]\nregion = [10, 20, 30, 40]\n"
        "[correlate]\nbuffer_seconds = 5.0\n"
    )
    cfg = load_config(str(config_file))
    assert cfg.db.path == str(tmp_path / "var" / "other.db")
    assert cfg.ocr.zones.region == [10, 20, 30, 40]
    assert cfg.correlate.buffer_seconds == 5.0
    # Untouched sections keep defaults.
    assert cfg.ocr.targets.region == [1021, 691, 213, 114]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.toml"))


def test_bad_region_is_rejected(tmp_path: Path) -> None:
    config_file = tmp_path / "bad.toml"
    config_file.write_text("[ocr.zones]\nregion = [1, 2]\n")
    with pytest.raises(ValidationError):
        load_config(str(config_file))


def test_auto_config_discovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg_file = tmp_path / "gorgon-tracker.toml"
    cfg_file.write_text("[db]\npath = 'discovered.db'\n")
    cfg = load_config()
    assert cfg.db.path == str(tmp_path / "discovered.db")


def test_legacy_output_not_picked_up_as_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # An unrelated fixture file must not affect config loading.
    monkeypatch.setenv("GORGON_TRACKER_CONFIG", str(tmp_path / "absent.toml"))
    with pytest.raises(FileNotFoundError):
        load_config()