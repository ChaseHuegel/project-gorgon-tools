"""Command-line entrypoint for gorgon-tracker."""

from __future__ import annotations

import signal
import sqlite3
import sys
import threading
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from . import db as database
from .config import load_config

app = typer.Typer(
    name="gorgon-tracker",
    help="Project Gorgon loot/drop-rate tracker (cross-platform).",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def _main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", "-c", help="Path to a gorgon-tracker.toml file."),
) -> None:
    ctx.obj = load_config(config)


def _apply_db(ctx: typer.Context, db_path: str | None) -> None:
    if db_path:
        ctx.obj.db.path = str(Path(db_path).expanduser().resolve())


def _connect(db_path: str) -> sqlite3.Connection:
    conn = database.connect(Path(db_path).expanduser().resolve())
    database.migrate(conn)
    return conn


def _install_signal_stop(stop_event: threading.Event) -> None:
    def handler(signum: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


@app.command()
def run(
    ctx: typer.Context,
    oneshot: bool = typer.Option(False, help="Open a session and exit immediately (used for testing)."),
    daemon: bool = typer.Option(False, help="Detach into the background (implemented in Phase 5)."),
    db_path: str | None = typer.Option(None, "--db", help="Override the SQLite database path."),
) -> None:
    """Open a capture session and run until stopped (Ctrl-C)."""
    del daemon
    _apply_db(ctx, db_path)
    conn = _connect(ctx.obj.db.path)
    session_id = database.open_or_new_session(conn, sys.platform, ctx.obj.model_dump())
    console.print(f"[green]Session {session_id}[/green] open at {ctx.obj.db.path}")
    if oneshot:
        database.close_session(conn, session_id)
        console.print("[green]Session closed.[/green]")
        conn.close()
        return
    stop_event = threading.Event()
    _install_signal_stop(stop_event)
    console.print("[yellow]Press Ctrl-C to stop.[/yellow]")
    # Phase 5: the capture pipeline will run here.
    while not stop_event.wait(0.5):
        pass
    database.close_session(conn, session_id)
    console.print("[green]Session closed cleanly.[/green]")
    conn.close()


@app.command()
def status(
    ctx: typer.Context,
    db_path: str | None = typer.Option(None, "--db", help="Override the SQLite database path."),
) -> None:
    """Show sessions and per-source event counts for the open session."""
    _apply_db(ctx, db_path)
    conn = _connect(ctx.obj.db.path)
    overview = database.status_overview(conn)

    table = Table(title="gorgon-tracker status")
    table.add_column("Total sessions")
    table.add_row(str(overview["sessions_total"]))
    console.print(table)

    sid = overview["open_session_id"]
    if sid is not None:
        counts = overview["open_session_counts"]
        counts_table = Table(title=f"Open session {sid} event counts")
        counts_table.add_column("table")
        counts_table.add_column("count")
        for name, count in counts.items():
            counts_table.add_row(name, str(count))
        console.print(counts_table)
    else:
        console.print("[yellow]No open session.[/yellow]")
    conn.close()


@app.command()
def stop() -> None:
    """Stop a running daemon (implemented in Phase 5)."""
    console.print("[yellow]stop: not implemented yet.[/yellow]")


@app.command()
def find_ports() -> None:
    """Detect the game's network ports and print a capture BPF filter."""
    from . import ports

    tcp_ports, udp_ports = ports.discover_ports()
    if not tcp_ports and not udp_ports:
        console.print("[yellow]No Project Gorgon process found. Start the game and retry.[/yellow]")
        raise typer.Exit(1)
    table = Table(title="Project Gorgon ports")
    table.add_column("protocol")
    table.add_column("ports")
    table.add_row("tcp", ", ".join(str(p) for p in sorted(tcp_ports)) or "-")
    table.add_row("udp", ", ".join(str(p) for p in sorted(udp_ports)) or "-")
    console.print(table)
    console.print("[green]" + ports.build_bpf(tcp_ports, udp_ports) + "[/green]")
    console.print("Copy the filter into [codeml][capture] bpf[/codeml] or use [b]run --auto-ports[/b].")


@app.command()
def calibrate() -> None:
    """Interactively tune OCR capture regions (implemented in Phase 4)."""
    console.print("[yellow]calibrate: not implemented yet.[/yellow]")


@app.command()
def replay(
    ctx: typer.Context,
    captures: list[Path] = typer.Argument(  # noqa: B008 - required by typer
        ..., help=".pcapng / pre-extracted .json / chat .txt/.log / zone or target .csv inputs."
    ),
    chat_dir: Path | None = typer.Option(  # noqa: B008 - required by typer
        None, "--chat-dir", help="Directory of Project Gorgon chat logs."
    ),
    db_path: str | None = typer.Option(None, "--db", help="Override the SQLite database path."),
) -> None:
    """Offline-ingest historical captures through the same parser and correlator."""
    from . import replay as replay_mod

    _apply_db(ctx, db_path)
    conn = _connect(ctx.obj.db.path)
    inputs = replay_mod.expand_inputs(captures)
    try:
        stats = replay_mod.run_replay(conn, ctx.obj, inputs, chat_dir, sys.platform)
    finally:
        conn.close()
    console.print("[green]Replay complete.[/green]")
    table = Table(title="Replay summary")
    for key, value in stats.items():
        table.add_row(key, str(value))
    console.print(table)


@app.command()
def migrate(
    ctx: typer.Context,
    files: list[Path] = typer.Argument(  # noqa: B008 - required by typer
        ..., help="Legacy CSV/JSON output files to import."
    ),
    kind: str | None = typer.Option(
        None,
        help="Force import kind: loot, zones, targets, chat-json, packets-json.",
    ),
    db_path: str | None = typer.Option(None, "--db", help="Override the SQLite database path."),
) -> None:
    """Import legacy CSV/JSON outputs as historical sessions."""
    from . import migrate as migrate_mod

    _apply_db(ctx, db_path)
    conn = _connect(ctx.obj.db.path)
    try:
        rows = []
        for path in files:
            stats = migrate_mod.import_bundle(conn, ctx.obj, path, kind, sys.platform)
            rows.append((str(path), stats["kind"], stats["imported"], stats["session_id"]))
    finally:
        conn.close()
    console.print("[green]Migration complete.[/green]")
    table = Table(title="Migrated files")
    table.add_column("file")
    table.add_column("kind")
    table.add_column("imported")
    table.add_column("session")
    for row in rows:
        table.add_row(row[0], row[1], str(row[2]), str(row[3]))
    console.print(table)


@app.command()
def export(
    since: str | None = typer.Option(None, help="Only export loot_drops at or after this ISO time."),
) -> None:
    """Backwards-compatible CSV export (implemented in Phase 6)."""
    console.print(f"[yellow]export: not implemented yet. since={since}[/yellow]")


@app.command()
def serve() -> None:
    """Web UI over the database (implemented in Phase 6)."""
    console.print("[yellow]serve: not implemented yet.[/yellow]")


@app.command()
def config(
    ctx: typer.Context,
    db_path: str | None = typer.Option(None, "--db", help="Override the SQLite database path."),
) -> None:
    """Print the effective configuration."""
    _apply_db(ctx, db_path)
    console.print(ctx.obj.model_dump_json(indent=2))


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)