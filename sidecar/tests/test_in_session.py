"""`IN_SESSION` entry/exit and strobe parsing — `ARCHITECTURE.md#entering-in_session`, `ARCHITECTURE.md#clean-exit`.

Driven through a scripted fake serial port, so the handshake sequence and the
`^\\d{1,3}\\t\\d+$` line-recognition rule are exercised without hardware.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.handler import PortBusy, PortHandler
from ephymeris_sidecar.ports.states import IllegalTransition, PortState


class ScriptedSerial:
    """A fake port that replays scripted board output and records writes.

    `feed` queues bytes the board would send; `written` captures what the
    sidecar sent back, so the handshake can be asserted in order.
    """

    instances: list["ScriptedSerial"] = []

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate")
        self.closed = False
        self.written = bytearray()
        self._out = bytearray()
        self._lock = threading.Lock()
        self._fail = False
        ScriptedSerial.instances.append(self)

    def feed(self, text: str) -> None:
        with self._lock:
            self._out.extend(text.encode())

    def fail_next_read(self) -> None:
        """Simulate the board being yanked mid-session."""
        self._fail = True

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._out)

    def read(self, size: int = 1) -> bytes:
        if self._fail:
            raise OSError("device disconnected")
        with self._lock:
            if self._out:
                chunk = bytes(self._out[:size])
                del self._out[:size]
                return chunk
        time.sleep(handler_module.READ_TIMEOUT_S)
        return b""

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_serial(monkeypatch: pytest.MonkeyPatch):
    ScriptedSerial.instances = []
    monkeypatch.setattr(handler_module.serial, "Serial", ScriptedSerial)
    # Keep the SEED window short so tests don't idle.
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.2)
    monkeypatch.setattr(handler_module, "SESSION_READY_TIMEOUT_S", 2.0)
    yield ScriptedSerial


_created: list[PortHandler] = []
_loop = asyncio.new_event_loop()


def make_handler() -> tuple[PortHandler, list[tuple]]:
    changes: list[tuple] = []
    handler = PortHandler(1, _loop, lambda *args: changes.append(args))
    _created.append(handler)
    return handler, changes


@pytest.fixture(autouse=True)
def _shutdown():
    yield
    while _created:
        _created.pop().shutdown()


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def drain_loop() -> None:
    """Turn the loop once so queued state-change notifications fire.

    `_set_state` hands notifications to the loop via `call_soon_threadsafe`
    (the reader thread can trigger them). In the real app the loop is running;
    here it has to be pumped explicitly before asserting on the callbacks.
    """
    _loop.run_until_complete(asyncio.sleep(0))


# --- entry sequence (`ARCHITECTURE.md#entering-in_session`) ---------------


def test_entry_requires_idle() -> None:
    """`ARCHITECTURE.md#entering-in_session` step 1 — refused if not IDLE, same rule as every other transition."""
    handler, _ = make_handler()
    handler._state = PortState.PASSTHROUGH
    with pytest.raises(IllegalTransition):
        handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)


def test_start_is_sent_only_after_ready(fake_serial) -> None:
    """`ARCHITECTURE.md#entering-in_session` steps 3–4 — the sidecar waits for READY before sending START."""
    handler, _ = make_handler()
    ready_seeds: list = []
    handler.start_session(
        "/dev/fake", 115200, "START CL=0 LAZY=1", ready_seeds.append, lambda c, t: None
    )
    port = wait_for(lambda: ScriptedSerial.instances) and ScriptedSerial.instances[0]

    # Nothing written before READY arrives.
    time.sleep(0.1)
    assert bytes(port.written) == b""

    port.feed("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    assert bytes(port.written) == b"START CL=0 LAZY=1\n"


def test_seed_line_is_captured_when_present(fake_serial) -> None:
    """`ARCHITECTURE.md#entering-in_session` step 5 / `TASKS.md#seed` — `SEED\\t<int>` right after START becomes trial_seed."""
    handler, _ = make_handler()
    seeds: list = []
    handler.start_session("/dev/fake", 115200, "START", seeds.append, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.feed("SEED\t288577176\n")

    assert wait_for(lambda: seeds)
    assert seeds[0] == 288577176


def test_a_missing_seed_resolves_after_the_window(fake_serial) -> None:
    handler, _ = make_handler()
    seeds: list = []
    handler.start_session("/dev/fake", 115200, "START", seeds.append, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")

    assert wait_for(lambda: seeds, timeout=3.0)
    assert seeds[0] is None  # proceeded without one


def test_a_first_strobe_resolves_the_seed_window_immediately(fake_serial) -> None:
    handler, _ = make_handler()
    seeds: list = []
    strobes: list = []
    handler.start_session(
        "/dev/fake", 115200, "START", seeds.append, lambda c, t: strobes.append((c, t))
    )
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.feed("221\t0\n")

    assert wait_for(lambda: strobes)
    assert seeds == [None]
    assert strobes[0] == (221, 0)


def test_never_seeing_ready_lands_in_error(fake_serial) -> None:
    handler, changes = make_handler()
    handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)
    # READY timeout is patched to 2s.
    assert wait_for(lambda: handler.state is PortState.ERROR, timeout=4.0)


# --- step 6: strobe parsing (`ARCHITECTURE.md#entering-in_session`) ------


def test_strobe_lines_parse_into_code_and_timestamp(fake_serial) -> None:
    handler, _ = make_handler()
    strobes: list = []
    handler.start_session(
        "/dev/fake", 115200, "START", lambda s: None, lambda c, t: strobes.append((c, t))
    )
    port = ScriptedSerial.instances[0]
    port.feed("READY\nSEED\t42\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    port.feed("221\t0\n222\t1000\n246\t3523555\n")

    assert wait_for(lambda: len(strobes) == 3)
    assert strobes == [(221, 0), (222, 1000), (246, 3523555)]


def test_non_strobe_lines_are_logged_but_not_data(fake_serial) -> None:
    """`ARCHITECTURE.md#entering-in_session` step 6 — stricter than PASSTHROUGH's opaque text handling."""
    handler, _ = make_handler()
    strobes: list = []
    handler.start_session(
        "/dev/fake", 115200, "START", lambda s: None, lambda c, t: strobes.append((c, t))
    )
    port = ScriptedSerial.instances[0]
    port.feed("READY\nSEED\t42\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    # Chatter, a 4-digit code, and a missing timestamp — none are data.
    port.feed("hello world\n1234\t5\n99\n221\t7\n")

    assert wait_for(lambda: strobes)
    assert strobes == [(221, 7)]
    # But everything still appears in scrollback for the raw-log fallback.
    text = [line.text for line in handler.scrollback()]
    assert "hello world" in text
    assert "1234\t5" in text


# --- stop / exit (`ARCHITECTURE.md#clean-exit`) ---------------------------


def test_stop_writes_the_literal_stop_line(fake_serial) -> None:
    handler, _ = make_handler()
    handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))

    handler.send_session_line("STOP")
    assert b"STOP\n" in bytes(port.written)
    # Sending STOP does not itself end the session (`ARCHITECTURE.md#clean-exit`).
    assert handler.state is PortState.IN_SESSION


def test_stop_is_refused_when_not_in_session() -> None:
    handler, _ = make_handler()
    with pytest.raises(PortBusy):
        handler.send_session_line("STOP")


def test_clean_end_returns_to_idle(fake_serial) -> None:
    handler, _ = make_handler()
    handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)

    handler.end_session("BF_END_SESSION received")
    assert handler.state is PortState.IDLE
    assert port.closed is True


# --- board drop = hard stop (`ARCHITECTURE.md#board-drop`) ---------------


def test_a_board_drop_mid_session_goes_to_error(fake_serial) -> None:
    """`ARCHITECTURE.md#board-drop` — always a hard stop, reusing the existing ERROR state."""
    handler, changes = make_handler()
    handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)

    port.fail_next_read()
    assert wait_for(lambda: handler.state is PortState.ERROR)
    drain_loop()

    transition = [c for c in changes if c[2] is PortState.ERROR][-1]
    assert transition[1] is PortState.IN_SESSION  # came straight from IN_SESSION
    assert "disconnected" in transition[3]


def test_error_clears_through_the_existing_ack(fake_serial) -> None:
    """`ARCHITECTURE.md#board-drop` — no new recovery logic; the ordinary port.error.ack path clears it."""
    handler, _ = make_handler()
    handler.start_session("/dev/fake", 115200, "START", lambda s: None, lambda c, t: None)
    port = ScriptedSerial.instances[0]
    port.feed("READY\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    port.fail_next_read()
    assert wait_for(lambda: handler.state is PortState.ERROR)

    assert handler.acknowledge_error() is PortState.IDLE
