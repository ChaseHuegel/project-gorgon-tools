from pathlib import Path

import pytest
from pydantic import ValidationError

from gorgon_tracker.config_write import (
    active_config_path,
    apply_updates,
    read_document,
    validate_document,
    write_updates,
)


def test_write_updates_preserves_comments_and_sibling_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config_file = tmp_path / "gorgon-tracker.toml"
    config_file.write_text(
        "# annotated sample keep me\n"
        "[db]\n"
        "path = 'data/gorgon.db'\n"
        "[capture]\n"
        "interface = 'auto'   # comment on interface\n"
        "bpf = ''\n"
    )

    cfg = write_updates({"capture.interface": "eth0", "db.path": "var/data.db"}, str(config_file))

    assert cfg.capture.interface == "eth0"
    assert cfg.db.path == str((tmp_path / "var/data.db").resolve())

    text = config_file.read_text()
    assert "# annotated sample keep me" in text
    assert "   # comment on interface" in text
    assert text.count("interface =") == 1  # single key updated, no duplication


def test_write_updates_nested_dict_and_creates_missing_section(tmp_path: Path) -> None:
    config_file = tmp_path / "c.toml"
    config_file.write_text("[db]\npath = 'x.db'\n")
    cfg = write_updates({"ocr.zones.region": [1, 2, 3, 4], "ocr.targets.interval_s": 1.0}, str(config_file))
    assert cfg.ocr.zones.region == [1, 2, 3, 4]
    assert cfg.ocr.targets.interval_s == 1.0
    assert "[ocr.zones]" in config_file.read_text()


def test_write_updates_rejects_invalid_region_without_touching_file(tmp_path: Path) -> None:
    config_file = tmp_path / "c.toml"
    original = "[db]\npath = 'x.db'\n"
    config_file.write_text(original)
    with pytest.raises(ValidationError):
        write_updates({"ocr.zones.region": [1, 2]}, str(config_file))
    assert config_file.read_text() == original


def test_active_config_path_discovery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    discovered = tmp_path / "gorgon-tracker.toml"
    discovered.write_text("[db]\npath = 'd.db'\n")
    assert active_config_path() == discovered


def test_active_config_path_creates_default_when_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert active_config_path() == (tmp_path / "gorgon-tracker.toml").resolve()


def test_apply_and_validate_preserve_unrelated_keys(tmp_path: Path) -> None:
    doc = read_document(tmp_path / "absent.toml")
    apply_updates(doc, {"capture.interface": "eth0"})
    cfg = validate_document(doc)
    assert cfg.capture.interface == "eth0"
    assert cfg.ocr.zones.region == [1680, 0, 180, 50]  # default preserved