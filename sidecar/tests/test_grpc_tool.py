"""The arduino-cli gRPC daemon backend — `hardware-interaction.md` §2.

Unit tests build protobuf messages directly, so the mapping and streaming
logic is exercised without a daemon. The invariant most worth pinning: the
gRPC path applies **exactly the same board filters** as the subprocess parser
— the two backends must be interchangeable behind `BoardTool`, and a board
that appears on one and not the other would be a haunting to debug.

Integration tests at the bottom drive a real `arduino-cli daemon` and are
skipped where the binary isn't installed.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import ephymeris_sidecar.boards.rpc  # noqa: F401 - stub tree onto sys.path
from cc.arduino.cli.commands.v1 import board_pb2, port_pb2

from ephymeris_sidecar.boards import create_board_tool
from ephymeris_sidecar.boards.cli_tool import ArduinoCliTool
from ephymeris_sidecar.boards.grpc_tool import (
    DaemonUnavailable,
    GrpcBoardTool,
    _LineSplitter,
    _boards_from_response,
    parse_daemon_address,
)
from ephymeris_sidecar.boards.tool import DetectedBoard


# --- daemon banner parsing --------------------------------------------------


def test_parses_the_json_banner() -> None:
    assert parse_daemon_address('{"IP":"127.0.0.1","Port":"50051"}') == "127.0.0.1:50051"


def test_parses_the_pretty_printed_json_banner() -> None:
    """The real 1.5.1 daemon pretty-prints the banner across several lines —
    a single readline sees only `{`, which is why the reader accumulates."""
    banner = '{\n  "IP": "127.0.0.1",\n  "Port": "50123"\n}\n'
    assert parse_daemon_address(banner) == "127.0.0.1:50123"
    assert parse_daemon_address("{\n") is None  # incomplete: keep reading


def test_parses_the_text_banner() -> None:
    line = "Daemon is now listening on 127.0.0.1:50052"
    assert parse_daemon_address(line) == "127.0.0.1:50052"


@pytest.mark.parametrize("line", ["", "starting up...", '{"IP":"127.0.0.1"}', "{}"])
def test_rejects_lines_that_are_not_a_banner(line: str) -> None:
    assert parse_daemon_address(line) is None


# --- board list mapping -----------------------------------------------------


def _serial_port(**overrides) -> board_pb2.DetectedPort:
    fields = {
        "address": "COM7",
        "protocol": "serial",
        "hardware_id": "95530343834351E020C0",
        "properties": {"vid": "0x2341", "pid": "0x0042"},
    }
    fields.update(overrides)
    return board_pb2.DetectedPort(port=port_pb2.Port(**fields))


def test_maps_a_mega_with_its_matching_board() -> None:
    detected = _serial_port()
    detected.matching_boards.add(name="Arduino Mega or Mega 2560", fqbn="arduino:avr:mega")
    response = board_pb2.BoardListResponse(ports=[detected])

    assert _boards_from_response(response) == [
        DetectedBoard(
            hardware_id="95530343834351E020C0",
            address="COM7",
            fqbn="arduino:avr:mega",
            label="Arduino Mega or Mega 2560",
        )
    ]


def test_applies_the_same_filters_as_the_subprocess_parser() -> None:
    """A board must never appear on one backend and not the other."""
    response = board_pb2.BoardListResponse(
        ports=[
            # Not serial: a network port.
            _serial_port(protocol="network"),
            # No vendor id: a Bluetooth endpoint or debug console.
            _serial_port(address="COM3", properties={}),
            # No hardware id anywhere: unbindable by definition.
            _serial_port(address="COM4", hardware_id="", properties={"vid": "0x2341"}),
            # hardware_id falls back to the serialNumber property — the same
            # fallback the JSON parser applies.
            _serial_port(
                address="COM5",
                hardware_id="",
                properties={"vid": "0x1A86", "serialNumber": "CH340SERIAL"},
            ),
            # A CH340 clone with no matching board: kept, with no FQBN.
            _serial_port(address="COM6", hardware_id="FTDIX", properties={"vid": "0x0403"}),
        ]
    )

    boards = _boards_from_response(response)
    assert [(b.address, b.hardware_id, b.fqbn) for b in boards] == [
        ("COM5", "CH340SERIAL", None),
        ("COM6", "FTDIX", None),
    ]


# --- stream line splitting --------------------------------------------------


def test_lines_split_across_chunks_are_reassembled() -> None:
    got: list[tuple[str, str]] = []
    splitter = _LineSplitter(lambda s, t: got.append((s, t)))

    splitter.feed("stdout", b"Compiling ")
    splitter.feed("stdout", b"sketch...\nLinking")
    splitter.feed("stderr", b"warning: unused\r\n")
    splitter.flush()

    assert got == [
        ("stdout", "Compiling sketch..."),
        ("stderr", "warning: unused"),
        ("stdout", "Linking"),  # the unterminated tail, released by flush
    ]


def test_streams_do_not_bleed_into_each_other() -> None:
    got: list[tuple[str, str]] = []
    splitter = _LineSplitter(lambda s, t: got.append((s, t)))

    splitter.feed("stdout", b"out-half")
    splitter.feed("stderr", b"err-line\n")
    splitter.feed("stdout", b"-rest\n")

    assert got == [("stderr", "err-line"), ("stdout", "out-half-rest")]


def test_blank_lines_are_dropped() -> None:
    got: list[tuple[str, str]] = []
    splitter = _LineSplitter(lambda s, t: got.append((s, t)))
    splitter.feed("stdout", b"\n\n  \nreal\n")
    splitter.flush()
    assert got == [("stdout", "real")]


# --- fallback behavior ------------------------------------------------------


class _FakeFallback:
    """Stands in for ArduinoCliTool: records calls, returns sentinels."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.binary = "arduino-cli"

    async def list_boards(self):
        self.calls.append("list")
        return [DetectedBoard(hardware_id="FAKE", address="COM9")]

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line):
        self.calls.append("compile")

    async def upload(self, sketch_dir, fqbn, address, on_line):
        self.calls.append("upload")


async def test_a_daemon_that_cannot_spawn_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    tool = GrpcBoardTool(binary="definitely-not-a-real-binary-xyz")
    fake = _FakeFallback()
    tool._fallback = fake  # type: ignore[assignment]

    async def no_spawn() -> None:
        raise DaemonUnavailable("no binary")

    monkeypatch.setattr(tool, "_spawn", no_spawn)

    boards = await tool.list_boards()
    assert [b.hardware_id for b in boards] == ["FAKE"]
    await tool.compile("/sk", "arduino:avr:mega", None, lambda s, t: None)
    await tool.upload("/sk", "arduino:avr:mega", "COM7", lambda s, t: None)
    assert fake.calls == ["list", "compile", "upload"]


async def test_the_factory_honours_the_escape_hatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EPHYMERIS_NO_GRPC_DAEMON", "1")
    assert isinstance(create_board_tool(), ArduinoCliTool)


async def test_the_factory_prefers_the_daemon_backend() -> None:
    assert isinstance(create_board_tool(), GrpcBoardTool)


# --- integration: a real daemon --------------------------------------------

requires_cli = pytest.mark.skipif(
    shutil.which("arduino-cli") is None, reason="arduino-cli not on PATH"
)


def _avr_core_installed() -> bool:
    try:
        out = subprocess.run(
            ["arduino-cli", "core", "list", "--format", "json"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        payload = json.loads(out or "{}")
        platforms = payload.get("platforms", payload) or []
        return any("arduino:avr" in json.dumps(p) for p in platforms)
    except Exception:  # noqa: BLE001 - no cli, no core, no test
        return False


@requires_cli
async def test_the_real_daemon_lists_boards_and_dies_with_close() -> None:
    tool = GrpcBoardTool()
    try:
        boards = await tool.list_boards()
        # No boards may be plugged into the dev machine — the type is the test.
        assert isinstance(boards, list)
        for board in boards:
            assert board.hardware_id and board.address
        daemon = tool._daemon
        assert daemon is not None and daemon.proc.returncode is None
    finally:
        await tool.close()
    assert tool._daemon is None
    assert daemon.proc.returncode is not None, "close() left the daemon running"


@requires_cli
async def test_a_killed_daemon_is_respawned_on_the_next_call() -> None:
    tool = GrpcBoardTool()
    try:
        await tool.list_boards()
        first = tool._daemon
        assert first is not None
        first.proc.kill()
        await first.proc.wait()

        boards = await tool.list_boards()  # this tick may serve via fallback
        assert isinstance(boards, list)
        await tool.list_boards()  # by now a fresh daemon must be up
        second = tool._daemon
        assert second is not None and second is not first
        assert second.proc.returncode is None
    finally:
        await tool.close()


@requires_cli
@pytest.mark.skipif(not _avr_core_installed(), reason="arduino:avr core not installed")
async def test_the_real_daemon_streams_a_compile_live(tmp_path: Path) -> None:
    """The migration's second deliverable: output during the compile, not a
    replay after it. Lines must arrive via the stream (out/err/progress)."""
    sketch = tmp_path / "Blink"
    sketch.mkdir()
    (sketch / "Blink.ino").write_text(
        "void setup() { pinMode(13, OUTPUT); }\n"
        "void loop() { digitalWrite(13, HIGH); delay(100); digitalWrite(13, LOW); delay(100); }\n",
        encoding="utf-8",
    )

    lines: list[tuple[str, str]] = []
    tool = GrpcBoardTool()
    try:
        await tool.compile(str(sketch), "arduino:avr:mega", None, lambda s, t: lines.append((s, t)))
    finally:
        await tool.close()

    assert lines, "expected streamed compiler output"
    text = "\n".join(t for _, t in lines)
    assert "Sketch uses" in text or "bytes" in text


@requires_cli
@pytest.mark.skipif(not _avr_core_installed(), reason="arduino:avr core not installed")
async def test_a_real_compile_error_names_the_error_line(tmp_path: Path) -> None:
    from ephymeris_sidecar.boards.tool import FlashFailed

    sketch = tmp_path / "Broken"
    sketch.mkdir()
    (sketch / "Broken.ino").write_text("void setup() { this is not C++ }\n", encoding="utf-8")

    tool = GrpcBoardTool()
    try:
        with pytest.raises(FlashFailed) as info:
            await tool.compile(str(sketch), "arduino:avr:mega", None, lambda s, t: None)
    finally:
        await tool.close()

    assert info.value.phase == "compile"
    assert "error" in info.value.message.lower()
