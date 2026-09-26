# Spec: Game packet format (corpse-search frames)

This spec describes how the tracker reads Project Gorgon network packets and what it extracts from them. The game sends its corpse-search dialogue as plaintext inside TCP payloads; the tracker keys on the string `Search Corpse of `. This is the canonical reference for the packet format.

## What arrives on the wire

A corpse-search dialogue frame contains plaintext like:

```text
Search Corpse of Goblin Horsebeater
Skin Corpse
Butcher Corpse
You do not have permission to loot this corpse.
```

The `Skin Corpse`, `Butcher Corpse`, and `Extract Skull` substrings are the `can_*` flag sources. Frames containing `You do not have permission to loot this corpse.` are ignored (`packets.py:18`, `:117-118`).

## Offline decode (tshark JSON)

Parser: `src/gorgon_tracker/parsers/packets.py`.

The display filter hex for `Search Corpse of ` (`packets.py:15`):

```text
tcp.payload contains 53:65:61:72:63:68:20:43:6f:72:70:73:65:20:6f:66:20
```

Invocation (`packets.py:171-182`):

```sh
tshark -r <file> -2 -Y 'tcp.payload contains 53:65:...' -T json
```

Decode steps per frame:

1. Pull `tcp.payload` (fallback `data.data`) from the JSON `_source.layers` (`packets.py:68-76`).
2. `hex_payload_to_text`: split the `aa:bb:cc` hex on `:`, decode bytes as latin-1 so every byte maps to a character (`packets.py:56-60`).
3. `clean_ascii`: keep only printable ASCII plus `\n`/`\r` (`packets.py:63-65`).
4. `decode_corpse_search`: search for `Search Corpse of <name>`, strip the action-button sequences in order (`Autopsy`, `Skin Corpse`, `Butcher Corpse`, `Extract Skull`), then trim whitespace and `-` (`packets.py:110-129`).
5. Set flags from the raw (uncleaned) text: `can_skin` = contains `Skin Corpse`, `can_butcher` = `Butcher Corpse`, `can_extract` = `Extract Skull`.

Frame time: `frame.time_epoch` (seconds float) or the `frame.time` display string as fallback (`packets.py:79-107`).

## Live decode (tshark fields)

Source: `src/gorgon_tracker/sources/tshark_live.py`.

Command (`tshark_live.py:59-78`):

```text
tshark -i <iface> -Y <bpf> -T fields
       -E separator=<sep> -E occurrence=f
       -e frame.time_epoch -e tcp.payload -e data.data
```

Each line has three fields joined by the separator, in that order. `parse_live_line` splits on `\t`, picks `tcp_payload` (fallback `data_payload`), and drops lines with fewer than 3 fields, an empty epoch, or an empty payload (`tshark_live.py:81-108`). Epoch is float seconds rounded to ms.

Known quirk (suspect bug): `FIELD_SEPARATOR = "/t"` at `tshark_live.py:21` is the two-character literal `/t`, but `parse_live_line` splits on a real tab (`line.split("\t")`, `tshark_live.py:86`). tshark only expands the backslash escape `\t`. The live path may silently yield nothing. The offline path and the unit tests (which feed hand-built tab-separated lines) do not exercise the separator argument. First suspect if live capture produces no source events.

## Related tooling

- `gorgon-tracker sniff-inspect` uses a 9-field `-T fields` invocation with a real tab separator to inventory plaintext tokens (`sniff_inspect.py:32-55`, `:222-232`); live mode writes a raw pcap while printing fields.
- Port discovery: `src/gorgon_tracker/ports.py` reads the game process sockets via `ss` and builds a `tcp.port == X or udp.port == Y` display filter. See `ports.py:25-74`.

## Source of truth and tests

- Offline parser: `src/gorgon_tracker/parsers/packets.py`
- Live source: `src/gorgon_tracker/sources/tshark_live.py`
- Tests: `tests/test_packets.py`, `tests/test_tshark_live.py`, `tests/test_sniff_inspect.py`
- Scenario fixture frames: `tests/scenario.py:41-70`

Update this doc when the filter hex, the decode steps, the button-string flags, or the live field list change.