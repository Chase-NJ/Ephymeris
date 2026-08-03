"""The table-upload path: PortLink framing/progress, and the UPLOADING bracket.

Deliberately does NOT retest the upload protocol itself — Task-Graph's
test_uploader.py already drives fourteen failure modes against the real
receiver. What is new here and therefore tested here: the Link built over a
serial port (framing, deadlines, progress extraction, mirror filtering), and
the port-ownership bracket around it.
"""

from __future__ import annotations

import asyncio

import pytest

from ephymeris_sidecar.boards.tool import DetectedBoard
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports import manager as manager_module
from ephymeris_sidecar.ports import upload as upload_module
from ephymeris_sidecar.ports.manager import FQBN, PortManager
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.ports.upload import PortLink
from ephymeris_sidecar.settings import SidecarSettings

HWID = "TESTBOARD01"
ADDRESS = "/dev/cu.faketest"


class ScriptedSerial:
    """A serial port that answers from a script, byte-granular like the real one."""

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate")
        self.written: list[str] = []
        self.pending = bytearray()
        self.closed = False

    def feed(self, *lines: str) -> None:
        for line in lines:
            self.pending.extend((line + "\r\n").encode())

    @property
    def in_waiting(self) -> int:
        # The handler's own reader loop asks; PortLink never does.
        return len(self.pending)

    def read(self, size: int = 1) -> bytes:
        if not self.pending:
            import time

            time.sleep(0.01)
            return b""
        take = min(size, len(self.pending))
        out = bytes(self.pending[:take])
        del self.pending[:take]
        return out

    def write(self, data: bytes) -> int:
        self.written.append(data.decode().rstrip("\n"))
        return len(data)

    def reset_input_buffer(self) -> None:
        self.pending.clear()

    def close(self) -> None:
        self.closed = True


@pytest.fixture()
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedSerial:
    port = ScriptedSerial(port=ADDRESS, baudrate=115200)
    monkeypatch.setattr(upload_module.serial, "Serial", lambda *a, **k: port)
    return port


# --- PortLink ----------------------------------------------------------------


def test_read_line_tolerates_every_line_ending(scripted: ScriptedSerial) -> None:
    link = PortLink(ADDRESS, 115200, reset=False)
    scripted.pending.extend(b"one\ntwo\r\nthree\rREADY\n")
    assert [link.read_line(0.5) for _ in range(4)] == ["one", "two", "three", "READY"]


def test_read_line_honours_its_deadline(scripted: ScriptedSerial) -> None:
    import time

    link = PortLink(ADDRESS, 115200, reset=False)
    started = time.monotonic()
    assert link.read_line(0.15) is None
    elapsed = time.monotonic() - started
    assert 0.1 < elapsed < 1.0, f"deadline was not honoured: {elapsed:.2f}s"


def test_progress_is_counted_at_the_boards_ack(scripted: ScriptedSerial) -> None:
    """A chunk leaving is hope; the ACK is progress the board confirmed."""
    events: list[tuple] = []
    link = PortLink(
        ADDRESS, 115200, reset=False,
        on_progress=lambda *a: events.append(a),
    )
    link.write_line("TABLE CHUNK 0 DEADBEEF 12345678")
    scripted.feed("TABLE ACK 1")
    assert link.read_line(0.5) == "TABLE ACK 1"
    assert ("transfer", 0, None, None) in events  # the chunk going out
    assert ("transfer", 1, None, None) in events  # the board's confirmation


def test_the_mirror_carries_headlines_and_never_hex(scripted: ScriptedSerial) -> None:
    mirrored: list[tuple[str, str]] = []
    link = PortLink(ADDRESS, 115200, reset=False, mirror=lambda d, t: mirrored.append((d, t)))

    link.write_line("TABLE BEGIN gonogo a598fb6cc57b8aab 372 0x78803eb5")
    link.write_line("TABLE CHUNK 0 4447544200010000DEADBEEF 87654321")
    link.write_line("TABLE END")
    scripted.feed("CAP PROTO=2", "READY", "TABLE ACK 1", "TABLE OK 0x78803eb5")
    for _ in range(4):
        link.read_line(0.5)

    texts = [t for _d, t in mirrored]
    assert any(t.startswith("TABLE BEGIN") for t in texts)
    assert any(t == "READY" for t in texts)
    assert any(t.startswith("TABLE OK") for t in texts)
    # The hex chunks and their ACKs are the 2000-line-cap blowout; excluded.
    assert not any("CHUNK" in t or "ACK" in t for t in texts)


# --- the UPLOADING bracket ---------------------------------------------------


async def _noop_output(_box, _lines):  # noqa: ANN001
    pass


async def _noop_presence(_boards):  # noqa: ANN001
    pass


def make_manager(monkeypatch: pytest.MonkeyPatch) -> tuple[PortManager, list[tuple]]:
    class IdleSerial(ScriptedSerial):
        pass

    monkeypatch.setattr(handler_module.serial, "Serial", IdleSerial)
    monkeypatch.setattr(manager_module.serial, "Serial", IdleSerial)
    states: list[tuple] = []
    manager = PortManager(
        loop=asyncio.get_event_loop(),
        tool=None,  # type: ignore[arg-type] - nothing here compiles or uploads via arduino-cli
        on_state_change=lambda *a: states.append(a),
        on_output=_noop_output,
        on_presence=_noop_presence,
    )
    manager.update_settings(
        SidecarSettings.from_payload(
            {"defaultBaud": 9600, "boxes": [{"box": 1, "hardwareId": HWID}]}
        )
    )
    manager._presence = {HWID: DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)}
    return manager, states


async def test_upload_bracket_from_idle_lands_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, states = make_manager(monkeypatch)

    def work(address: str, _handler) -> str:  # noqa: ANN001
        assert address == ADDRESS
        assert manager.handler(1).state is PortState.UPLOADING
        return "payload"

    state, resumed, outcome = await manager.with_port_for_upload(1, work)
    assert state is PortState.IDLE
    assert resumed is False
    assert outcome == "payload"
    # State-change notifications are handed to the loop (call_soon_threadsafe),
    # so give it one turn before reading them.
    await asyncio.sleep(0)
    assert [(s[1].value, s[2].value) for s in states] == [
        ("IDLE", "UPLOADING"),
        ("UPLOADING", "IDLE"),
    ]


async def test_upload_bracket_resumes_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, states = make_manager(monkeypatch)
    manager.handler(1).open_passthrough(ADDRESS, 9600)

    state, resumed, _ = await manager.with_port_for_upload(1, lambda _a, _h: None)
    assert state is PortState.PASSTHROUGH
    assert resumed is True


async def test_upload_failure_parks_the_port_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _states = make_manager(monkeypatch)

    def work(_address, _handler):  # noqa: ANN001
        raise RuntimeError("board went quiet")

    with pytest.raises(RuntimeError):
        await manager.with_port_for_upload(1, work)
    assert manager.handler(1).state is PortState.ERROR


async def test_upload_is_refused_while_a_session_owns_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ephymeris_sidecar.ports.states import IllegalTransition

    manager, _ = make_manager(monkeypatch)
    handler = manager.handler(1)
    handler._set_state(PortState.IN_SESSION, "test")  # noqa: SLF001

    with pytest.raises(IllegalTransition):
        await manager.with_port_for_upload(1, lambda _a, _h: None)
    assert handler.state is PortState.IN_SESSION
