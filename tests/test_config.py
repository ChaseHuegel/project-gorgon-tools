from pathlib import Path

import pytest
from pydantic import ValidationError

from gorgon_tracker.config import TrackerConfig, _vdf_library_paths, default_chat_log_dir, load_config


def test_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert isinstance(cfg, TrackerConfig)
    assert cfg.db.path == str((tmp_path / "data/gorgon.db").resolve())
    assert cfg.capture.interface == "auto"
    assert cfg.ocr.zones.region == [1680, 0, 180, 50]
    assert cfg.ocr.targets.interval_s == 0.5
    assert cfg.correlate.buffer_seconds == 10.0
    assert cfg.correlate.target_fallback_seconds == 3.0
    assert cfg.correlate.search_corroboration_seconds == 2.0


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


def test_vdf_library_paths() -> None:
    text = (
        '"libraryfolders"\n'
        "{\n"
        '\t"0"\n'
        "\t{\n"
        '\t\t"path"\t\t"/home/chase/SteamLibrary"\n'
        '\t\t"label"\t\t""\n'
        "\t}\n"
        '\t"1"\n'
        "\t{\n"
        '\t\t"path"\t\t"C:\\\\Games\\\\Steam"\n'
        "\t}\n"
        "}\n"
    )
    assert _vdf_library_paths(text) == ["/home/chase/SteamLibrary", "C:\\Games\\Steam"]


def test_default_chat_log_dir_windows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    chat = tmp_path / "AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
    chat.mkdir(parents=True)
    assert default_chat_log_dir(platform="win32") == str(chat)


def test_default_chat_log_dir_proton_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    chat = (
        tmp_path
        / ".local/share/Steam"
        / "steamapps/compatdata/342940/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
    )
    chat.mkdir(parents=True)
    monkeypatch.setattr("gorgon_tracker.config.Path.home", lambda: tmp_path)
    assert default_chat_log_dir(platform="linux") == str(chat)


def test_default_chat_log_dir_discovers_vdf_library(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    steam = tmp_path / ".local/share/Steam"
    (steam / "steamapps").mkdir(parents=True)
    lib = tmp_path / "games" / "SteamLibrary"
    chat = (
        lib
        / "steamapps/compatdata/342940/pfx/drive_c/users/steamuser/AppData/LocalLow/Elder Game/Project Gorgon/ChatLogs"
    )
    chat.mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n"0"\n{{\n"path"\t\t"{lib}"\n}}\n}}\n'
    )
    monkeypatch.setattr("gorgon_tracker.config.Path.home", lambda: tmp_path)
    assert default_chat_log_dir(platform="linux") == str(chat)