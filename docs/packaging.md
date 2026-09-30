# Packaging

This doc describes how to turn gorgon-tracker into a standalone executable for Linux and Windows. It uses Nuitka. The build runs the full CLI in one file.

## What the executable contains

The executable bundles the Python package and its data:

- the item, zone, and name catalogs (`data/`)
- the database schema (`schema.sql`)
- the web UI static files (`static/`)
- the FastAPI server dependencies for the `web` and `serve` commands

The package installs via the Typer entry point `gorgon-tracker` (`pyproject.toml:39`). Nuitka compiles `src/gorgon_tracker/__main__.py`, which calls the same app (`__main__.py:6`).

## Required external binaries

The executable does not bundle tesseract. This binary must be installed on the target machine. Without it, the OCR commands do not work.

The tool looks up a configured path on PATH when the value is a bare command name, and uses an explicit path directly. The lookup lives in `src/gorgon_tracker/binpath.py`. A missing binary produces a warning with an install hint. The web UI shows the warning at `web.py:80` through `control.setup_warnings`.

| Binary | Config key | Purpose |
|---|---|---|
| tesseract | `ocr.tesseract_path` | Screen OCR for zones and targets |

To install the binary:

- Linux (APT): install `tesseract-ocr`.
- Windows: install the Tesseract installer. Set `[ocr] tesseract_path` when the installer does not add tesseract.exe to PATH.

## Build a single executable

Run the build on the target OS. Nuitka does not cross-compile: a Linux binary builds on Linux, and a Windows executable builds on Windows.

1. Install the package and Nuitka in a virtual environment.
2. Run the build wrapper from the repository root.

```sh
python -m venv buildenv
source buildenv/bin/activate
pip install -e ".[serve]" nuitka
python tools/build_exe.py
```

The wrapper writes the executable to `dist/bundle/`. It adds a `.exe` suffix on Windows. See `tools/build_exe.py` for the exact Nuitka arguments.

The wrapper follows the server imports that are loaded lazily inside functions. These are `fastapi`, `uvicorn`, `starlette`, `pydantic`, `httpx`, and `multipart`. It passes them as `--include-module` entries. The list lives in `tools/build_exe.py:22-28`.

After the build, test the executable:

```sh
dist/bundle/gorgon-tracker version
dist/bundle/gorgon-tracker export --out /tmp/out.csv
```

The one-file form unpacks to a temporary directory at startup. The schema load and the web UI read their data from that directory. Check them once on each platform.

## Build in CI

`.github/workflows/build.yml` builds both platforms on request. The workflow runs `tools/build_exe.py` on `ubuntu-latest` and `windows-latest`. It uploads one artifact per OS. The build triggers on a tag push or a manual dispatch.

## Notes

- The daemon command forks a process (`daemon.py:39`). It works on Linux. On Windows, the `web` UI starts capture itself (`control.py:32`).