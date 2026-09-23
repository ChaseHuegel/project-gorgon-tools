"""Interactive OCR region calibration."""

from __future__ import annotations

import time
from collections.abc import Sequence
from itertools import count

from rich.console import Console

from .config import TrackerConfig
from .parsers import ocr

console = Console()


def parse_region(value: str) -> list[int]:
    """Parse 'x,y,width,height' into a list of four ints."""
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise ValueError("region must be x,y,width,height (e.g. 1680,0,180,50)")
    return [int(p) for p in parts]


def default_region(cfg: TrackerConfig, kind: str) -> list[int]:
    regions = {"zones": cfg.ocr.zones.region, "targets": cfg.ocr.targets.region}
    if kind not in regions:
        raise ValueError(f"unknown kind {kind!r}; expected one of zones, targets")
    return list(regions[kind])


def preview(cfg: TrackerConfig, region: Sequence[int], watch: bool, snapshot_path: str) -> None:
    """Capture once (or continuously with --watch) and print the OCR result."""
    console.print(f"[cyan]Region:[/cyan] {','.join(str(v) for v in region)}")
    console.print(
        f"[cyan]Snapshot path:[/cyan] {snapshot_path} "
        "(open it to verify what tesseract sees)"
    )
    iterator = count() if watch else range(1)
    try:
        for _ in iterator:
            image = ocr.grab_region(region)
            processed = ocr.grayscale(image)
            processed.save(snapshot_path)
            text = ocr.capture_text(cfg, region)
            console.print(f"[green]OCR:[/green] {text or '<EMPTY>'}")
            if watch:
                time.sleep(1.0)
    except KeyboardInterrupt:
        console.print("[yellow]Calibration stopped.[/yellow]")