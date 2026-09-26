# Spec: Screen OCR capture pipeline

This spec describes how the tracker captures screen regions, runs OCR, and emits zone/target events. It is the canonical reference for OCR behavior.

## Source and regions

Two producers run under `[ocr] enabled` (`sources/ocr.py`):

| Producer | Config | Default region `[x, y, w, h]` | Default interval |
|---|---|---|---|
| `produce_zones` | `[ocr.zones]` | `[1680, 0, 180, 50]` | `5.0 s` (heartbeat `30.0 s`) |
| `produce_targets` | `[ocr.targets]` | `[1021, 691, 213, 114]` | `0.5 s` (no heartbeat) |

Region is validated as `[x, y, width, height]` with non-negative integers (`config.py:48-53`).

## Capture path

`parsers/ocr.py`:

1. **Grab**: `grab_region` captures the full display and crops, so regions are absolute screen coordinates (`ocr.py:55-63`).
2. **Preprocess**: `grayscale` converts to luminance (`L` mode), matching the legacy pipeline (`ocr.py:44-46`).
3. **OCR**: tesseract via `pytesseract.image_to_string` (`ocr.py:242-245`).
4. **Sanitize**: `sanitize_text` keeps only `[a-zA-Z\s]` — no digits or punctuation reach change detection (`ocr.py:248-250`).

### Capture backend

`_background_method` (`ocr.py:66-77`) picks the backend:

- `GORGON_TRACKER_SCREEN_METHOD=auto` (default): `mss` on X11/Windows; the XDG desktop portal (via jeepney) when `WAYLAND_DISPLAY` is set, because mss reaches only XWayland and returns black frames under Wayland.
- Override with `mss` or `portal`.

All consumers share a single cached full-screen grab, refreshed at most every `GORGON_TRACKER_SCREEN_TTL` seconds (default `1.0`) under a lock (`ocr.py:80-98`).

## Emission semantics

`produce_region` (`sources/ocr.py:36-75`):

- Empty OCR reads are skipped (matches the legacy "no text found" path).
- Text is name-corrected (see below) before change detection.
- A change (`text != last_text`) emits an event and updates the emit time.
- A heartbeat re-emits unchanged text when `[heartbeat_s]` (zones only, default `30.0`) elapses, so the UI keeps seeing the current zone/target.
- `ScreenCaptureError` warns and skips. Any other exception treats OCR as empty text, so tesseract hiccups never kill the source.

## Name correction

Wired at `sources/ocr.py:20-33`: `NameCorrector.correct(text, "zones")` or `"monsters"`, with the zone alias table applied for zones. The corrector hot-reloads name lists on mtime change. Thresholds and rules live in `specs/cdn-catalog.md`.

## Calibration

`gorgon-tracker calibrate` (source `src/gorgon_tracker/calibrate.py`) and the web Calibrate page (`GET /api/calibrate/*`) snapshot a region, run raw OCR preview, and save a tuned region into config via `POST /api/calibrate/region` (see `docs/api.md`).

## Source of truth and tests

- Capture + OCR helpers: `src/gorgon_tracker/parsers/ocr.py`
- Producers: `src/gorgon_tracker/sources/ocr.py`
- Calibration: `src/gorgon_tracker/calibrate.py`
- Tests: `tests/test_ocr.py` (headless CI uses mocks; on-display verification needs a display)

Update this doc when the capture backend, sanitize rules, change detection, or heartbeat behavior changes.