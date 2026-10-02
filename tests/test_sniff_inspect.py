from pathlib import Path

from gorgon_tracker.config import TrackerConfig
from gorgon_tracker.sniff_inspect import (
    FIELD_ARGS,
    analyze,
    analyze_pcap,
    build_field_args,
    capture_live,
    decode_payload,
    direction_of,
    finalize_analysis,
    parse_field_line,
    tokenize,
    write_report,
    write_stream_dumps,
)

_HEX = ":".join(f"{ord(ch):02x}" for ch in "Search Corpse of Rat\nSkin Corpse\n")


def _line(
    epoch: str = "1768161602.5",
    stream: str = "17",
    frame: str = "42",
    payload: str = _HEX,
) -> str:
    return "\t".join([frame, epoch, stream, "10.0.0.5", "10.0.0.9", "45000", "45001", payload, "\t"])


def test_build_field_args_are_stable() -> None:
    assert build_field_args() == FIELD_ARGS
    assert "frame.time_epoch" in FIELD_ARGS
    assert "tcp.stream" in FIELD_ARGS
    assert "data.data" in FIELD_ARGS


def test_parse_field_line_extracts_fields() -> None:
    record = parse_field_line(_line())
    assert record is not None
    assert record.frame_number == 42
    assert record.time_ms == 1768161602500
    assert record.stream == "17"
    assert record.srcport == "45000"
    assert record.payload_hex == _HEX


def test_parse_field_line_handles_udp_and_malformed() -> None:
    udp = "\t".join(["7", "1768161603.0", "", "10.0.0.5", "10.0.0.9", "", "", "", _HEX])
    record = parse_field_line(udp)
    assert record is not None
    assert record.stream is not None  # defaults to "0"
    assert record.payload_hex == _HEX

    assert parse_field_line("") is None
    assert parse_field_line("only\tthree\tfields") is None
    assert parse_field_line("\t".join(["1", "2", "3", "4", "5", "6", "7", "", ""])) is None


def test_decode_and_tokenize() -> None:
    text = decode_payload(_HEX)
    assert "Search Corpse of Rat" in text
    assert tokenize(text) == ["Search Corpse of Rat", "Skin Corpse"]
    assert tokenize("ab\x00\x01cd") == []  # binary noise has no >=4 printable runs


def test_direction_of_uses_game_ports() -> None:
    record = parse_field_line(_line())
    assert record is not None
    assert direction_of(record, {45000}) == "c>s"
    assert direction_of(record, {45001}) == "s>c"
    assert direction_of(record, None) == "unknown"
    assert direction_of(record, {9999}) == "unknown"


def test_analyze_aggregates_tokens_and_stream_text() -> None:
    records = [parse_field_line(_line(stream="1")), parse_field_line(_line(stream="2"))]
    assert records[0] is not None and records[1] is not None
    analysis = analyze([r for r in records if r], {45000})
    assert analysis["tokens"]["Search Corpse of Rat"].count == 2
    assert ("1", "c>s") in analysis["stream_text"]
    assert "Search Corpse of Rat" in analysis["decoded"][42]


def test_write_report_and_stream_dumps(tmp_path: Path) -> None:
    record = parse_field_line(_line())
    assert record is not None
    analysis = analyze([record], {45000})

    strings_file = write_report(tmp_path, analysis["tokens"])
    assert strings_file.name == "strings.csv"
    content = strings_file.read_text()
    assert "Search Corpse of Rat" in content
    assert content.splitlines()[0] == "token,count,first_ms,last_ms,streams,directions"

    streams_dir = write_stream_dumps(tmp_path, analysis)
    dump = streams_dir / "17_c>s.txt"
    assert dump.is_file()
    assert "Search Corpse of Rat" in dump.read_text()


def test_finalize_analysis_summary(tmp_path: Path) -> None:
    record = parse_field_line(_line())
    assert record is not None
    summary = finalize_analysis(tmp_path, [record], Path("fake.pcapng"), {45000})
    assert summary["frames"] == 1
    assert summary["unique_tokens"] == 2
    assert summary["streams"] == 1
    assert summary["top_strings"][0]["token"] == "Search Corpse of Rat"
    assert summary["strings_file"].endswith("strings.csv")


def test_analyze_pcap_offline(tmp_path: Path, monkeypatch) -> None:
    fake_pcap = tmp_path / "old.pcapng"
    fake_pcap.write_text("not really a pcap")
    lines = "\n".join([_line(stream="5"), _line(stream="5", epoch="1768161604.0")]) + "\n"

    def fake_run(args, capture_output=True, text=True):
        class _Result:
            returncode = 0
            stdout = lines
            stderr = ""

        return _Result()

    monkeypatch.setattr("gorgon_tracker.sniff_inspect.subprocess.run", fake_run)
    summary = analyze_pcap(TrackerConfig(), fake_pcap, tmp_path / "out")
    assert summary["frames"] == 2
    assert summary["top_strings"][0]["token"] == "Search Corpse of Rat"

    (tmp_path / "out" / "strings.csv").is_file()


def test_analyze_pcap_surfaces_tshark_failure(tmp_path: Path, monkeypatch) -> None:
    fake_pcap = tmp_path / "bad.pcapng"
    fake_pcap.write_text("x")

    def fake_run(args, capture_output=True, text=True):
        class _Result:
            returncode = 2
            stdout = ""
            stderr = "tshark: no such file"

        return _Result()

    monkeypatch.setattr("gorgon_tracker.sniff_inspect.subprocess.run", fake_run)
    import pytest

    with pytest.raises(RuntimeError, match="tshark failed"):
        analyze_pcap(TrackerConfig(), fake_pcap, tmp_path / "out")


def test_capture_live_writes_pcap_and_stops_on_event(tmp_path: Path, monkeypatch) -> None:
    import threading

    lines = iter([_line(frame="1"), _line(stream="7", frame="2")])  # EOF after two lines ends the loop

    class _Stdout:
        def readline(self):
            return next(lines, "")

    class _FakeProc:
        def __init__(self):
            self.stdout = _Stdout()

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    captured_args: dict = {}

    def fake_popen(args, stdout=None, text=False, bufsize=-1, stderr=None):
        captured_args["args"] = args
        return _FakeProc()

    monkeypatch.setattr("gorgon_tracker.sniff_inspect.subprocess.Popen", fake_popen)
    monkeypatch.setattr("gorgon_tracker.sniff_inspect.tshark_live.resolve_interface", lambda cfg: "eth0")
    monkeypatch.setattr("gorgon_tracker.sniff_inspect.tshark_live.build_bpf_filter", lambda cfg: "tcp.port == 45000")
    monkeypatch.setattr("gorgon_tracker.sniff_inspect.time.time", lambda: 123.0)

    out_dir = tmp_path / "sniff"
    summary = capture_live(TrackerConfig(), out_dir, threading.Event(), game_tcp_ports={45000})
    assert summary["frames"] == 2
    assert summary["source_file"] == str(out_dir / "capture-123.pcapng")
    assert "-w" in captured_args["args"]
    assert (out_dir / "strings.csv").is_file()
    assert (out_dir / "streams" / "17_c>s.txt").is_file()