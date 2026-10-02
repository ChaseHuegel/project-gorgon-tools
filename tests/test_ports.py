from gorgon_tracker import ports

TCP_SS = """\
ESTAB 0 0 127.0.0.1:45212 93.184.216.34:80 users:(("WindowsPlayer",pid=4012,fd=11))
ESTAB 0 0 127.0.0.1:45213 93.184.216.35:80 users:(("someother",pid=9999,fd=5))
ESTAB 0 0 127.0.0.1:45214 93.184.216.36:80 users:(("WindowsPlayer",pid=4012,fd=12))
"""
UDP_SS = """\
UNCONN 0 0 127.0.0.1:5123 0.0.0.0:* users:(("WindowsPlayer",pid=4012,fd=13))
UNCONN 0 0 127.0.0.1:5124 0.0.0.0:* users:(("other",pid=7,fd=1))
"""


def test_extract_ports_filters_by_pid() -> None:
    tcp, udp = ports.extract_ports_for_pids([4012], TCP_SS, UDP_SS)
    assert tcp == {45212, 45214}
    assert udp == {5123}


def test_build_bpf_formatting() -> None:
    assert ports.build_bpf({80, 443}, {53}) == "tcp.port == 80 or tcp.port == 443 or udp.port == 53"


def test_discover_bpf_none_when_no_process(monkeypatch) -> None:
    monkeypatch.setattr(ports, "find_game_pids", lambda: [])
    assert ports.discover_bpf() is None