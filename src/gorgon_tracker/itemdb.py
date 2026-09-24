"""Item name identity helpers.

Project Gorgon reports the same loot item under different spellings depending
on the source:

* the chat log uses the user-facing display name ("Good Armor Patch Kit",
  "Gottak's Calling Card");
* the Unity ``Player.log`` uses an internal slug plus a numeric variant code
  ("ArmorPatchKit3", "GoblinCallingCard15").

``LootEvent`` carries the raw per-source name and (for Unity) the trait that
real pickups share with chat lines is the *anchored whole-second timestamp*.
The correlator reconciles the two facts and resolves a canonical display name
(see ``correlator.reconcile``). This module provides the deterministic pieces:
splitting off the numeric code and inflating the internal slug.
"""

from __future__ import annotations

import re

# ``ArmorPatchKit3`` -> (base="ArmorPatchKit", code="3"); chat names keep code "".
_CODED_NAME_RE = re.compile(r"^(?P<base>.*?[A-Za-z])(?P<code>\d+)$")


def split_item_name(raw: str) -> tuple[str, str]:
    """Split a Unity-internal name into ``(base, item_code)``.

    ``CamelCaseThanABit`` below -> ("CamelCaseTh", "anABit") is avoided by
    requiring the base to end on a letter; chat display names (codes absent)
    simply return ``(raw, "")``.
    """
    match = _CODED_NAME_RE.match(raw)
    if not match:
        return raw, ""
    return match.group("base"), match.group("code")


def infer_display(raw: str) -> str:
    """Best-effort inflation of an internal name into a human display name.

    Drops the numeric variant code, then inserts a space before each embedded
    uppercase letter: ``ImpressiveGoblinSkull`` -> "Impressive Goblin Skull".
    Chat display names are returned unchanged (no embedded capitals to split).
    """
    base, _ = split_item_name(raw)
    inflated = re.sub(r"(?=[A-Z])", " ", base).strip().split()
    # Re-join single tokens that were previously glued (e.g. "GoblinCallingCard").
    if len(inflated) <= 1:
        return base if base == raw else inflated[0]
    return " ".join(inflated)