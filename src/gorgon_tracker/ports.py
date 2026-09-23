"""Network port discovery for Project Gorgon (Proton/Wine aware)."""

from __future__ import annotations

import subprocess

GAME_PROCESS_NAMES = ("WindowsPlayer", "ProjectGorgon", "ProjectGorgon.exe")


def find_game_pids() -> list[int]:
    """Return PIDs of the game process using pgrep (Linux/macOS)."""
    for name in GAME_PROCESS_NAMES:
        try:
            proc = subprocess.run(
                ["pgrep", "-f", name], capture_output=True, text=True, timeout=10
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        pids = [int(x) for x in proc.stdout.split()]
        if pids:
            return pids
    return []


def _extract_port(local_address: str) -> int | None:
    port_part = local_address.rsplit(":", 1)[-1]
    return int(port_part) if port_part.isdigit() else None


def _ports_for_ss_processes(text: str, pids: list[int]) -> set[int]:
    ports: set[int] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        process_field = parts[-1]
        if not any(f"pid={pid}" in process_field for pid in pids):
            continue
        port = _extract_port(parts[3])
        if port is not None:
            ports.add(port)
    return ports


def extract_ports_for_pids(pids: list[int], netstat_tcp: str, netstat_udp: str) -> tuple[set[int], set[int]]:
    """Extract (tcp, udp) port sets from raw `ss` output for the given PIDs."""
    tcp_ports = _ports_for_ss_processes(netstat_tcp, pids)
    udp_ports = _ports_for_ss_processes(netstat_udp, pids)
    return tcp_ports, udp_ports


def _run_ss(kind: str) -> str:
    try:
        proc = subprocess.run(
            ["ss", f"-{kind}nHtp"], capture_output=True, text=True, timeout=10
        )
        return proc.stdout or ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def discover_ports() -> tuple[set[int], set[int]]:
    """Discover the game's live ports via ss (Linux)."""
    pids = find_game_pids()
    if not pids:
        return set(), set()
    return extract_ports_for_pids(pids, _run_ss("t"), _run_ss("u"))


def build_bpf(tcp_ports: list[int] | set[int], udp_ports: list[int] | set[int]) -> str:
    """Compose a BPF display filter from TCP/UDP port sets."""
    clauses = [f"tcp.port == {p}" for p in sorted(tcp_ports)]
    clauses += [f"udp.port == {p}" for p in sorted(udp_ports)]
    return " or ".join(clauses)


def discover_bpf() -> str | None:
    tcp, udp = discover_ports()
    if not tcp and not udp:
        return None
    return build_bpf(tcp, udp)