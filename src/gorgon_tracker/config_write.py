"""TOML read/write helpers that preserve comments and formatting (tomlkit).

The web UI edits configuration without destroying the annotated sample file:
we parse with :mod:`tomlkit`, apply only the specific keys the user changed,
validate the whole result with pydantic, and only then write it back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import Table

from .config import _CONFIG_FILE_CANDIDATES, TrackerConfig, config_from_dict


def active_config_path(explicit: str | None = None) -> Path:
    """Resolve the config file to read/write.

    Precedence: an explicit path (if it exists), then the first discovered
    candidate file, then a fresh ``gorgon-tracker.toml`` in the CWD.
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    for candidate in _CONFIG_FILE_CANDIDATES:
        resolved = candidate.expanduser().resolve()
        if resolved.is_file():
            return resolved
    return Path("gorgon-tracker.toml").expanduser().resolve()


def load_config_path(explicit: str | None = None) -> TrackerConfig:
    """Return the *effective* config for the active file path (validate on read)."""
    return config_from_dict(read_document(active_config_path(explicit)).unwrap())


def read_document(path: Path) -> tomlkit.TOMLDocument:
    """Parse an existing file into a :class:`tomldocument`, or start a blank one."""
    if path.is_file():
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    return tomlkit.document()


def _is_table(value: Any) -> bool:
    return isinstance(value, (dict, Table))


def _set_path(doc: tomlkit.TOMLDocument, parts: list[str], value: Any) -> None:
    """Set a dotted key path, descending into/nesting tables, preserving siblings."""
    container: Any = doc
    for part in parts[:-1]:
        if part in container and _is_table(container[part]):
            container = container[part]
        else:
            container[part] = tomlkit.table()
            container = container[part]
    container[parts[-1]] = value


def apply_updates(doc: tomlkit.TOMLDocument, updates: dict[str, Any]) -> None:
    """Apply ``{"section.key": value}`` updates onto ``doc``, in-place.

    ``value`` may be a scalar, an array, or a nested dict (which is expanded
    into dotted keys for comment-preserving navigation).
    """
    for dotted_key, value in updates.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                parts = f"{dotted_key}.{sub_key}".split(".")
                _set_path(doc, parts, sub_value)
        else:
            _set_path(doc, dotted_key.split("."), value)


def validate_document(doc: tomlkit.TOMLDocument) -> TrackerConfig:
    """Validate a (possibly just-updated) document against the pydantic schema."""
    return config_from_dict(doc.unwrap())


def write_updates(updates: dict[str, Any], explicit: str | None = None) -> TrackerConfig:
    """Validate and persist ``updates`` onto the active config file.

    Only the keys present in ``updates`` are touched; all other keys, comments,
    and ordering are preserved. Raises ``pydantic.ValidationError`` (and writes
    nothing) if the result is invalid.
    """
    path = active_config_path(explicit)
    doc = read_document(path)
    apply_updates(doc, updates)
    cfg = validate_document(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return cfg