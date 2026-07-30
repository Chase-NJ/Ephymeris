"""PortHandler — line splitting, ring buffer, batching, and send guards.

Exercises the handler against a fake serial port so the parsing and buffering
rules from `dashboard.md` §6.3 can be checked without hardware.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import serial

from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.handler import (
    LINE_ENDINGS,
    READ_TIMEOUT_S,
    PortBusy,
    PortHandler,
    RING_CAPACITY,
)
from ephymeris_sidecar.ports.states import IllegalTransition, PortState


class FakeSerial:
    """Minimal stand-in for `serial.Serial`."""

    def __init__(self, *_args, **kwargs) -> None:
        self.baudrate = kwargs.get("baudrate")
        self.port = kwargs.get("port")
        self.written = bytearray()
        self.closed = False
        self.dtr = True
        self._to_read = bytearray()
        self._lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self._lock:
            self._to_read.extend(data)

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._to_read)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            if self._to_read:
                chunk = bytes(self._to_read[:size])
                del self._to_read[:size]
                return chunk
        # Block like a real port with a read timeout. Returning instantly here
        # turns the reader thread into a busy-spin and makes the suite crawl.
        time.sleep(READ_TIMEOUT_S)
        return b""

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_port(monkeypatch: pytest.MonkeyPatch) -> list[FakeSerial]:
    created: list[FakeSerial] = []

    def factory(*args, **kwargs):
        port = FakeSerial(*args, **kwargs)
        created.append(port)
        return port

    monkeypatch.setattr(handler_module.serial, "Serial", factory)
    return created


_created: list[PortHandler] = []
_loop = asyncio.new_event_loop()


def make_handler() -> tuple[PortHandler, list[tuple]]:
    changes: list[tuple] = []
    handler = PortHandler(1, _loop, lambda *args: changes.append(args))
    _created.append(handler)
    return handler, changes


@pytest.fixture(autouse=True)
def _shut_down_handlers():
    """Reader threads are daemons; without this they outlive their test."""
    yield
    while _created:
        _created.pop().shutdown()


# --- line splitting (§6.2) -----------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"one\ntwo\n", ["one", "two"]),
        (b"one\r\ntwo\r\n", ["one", "two"]),  # Arduino println emits CRLF
        (b"one\rtwo\r\n", ["one", "two"]),
        (b"mixed\nstyles\r\nhere\n", ["mixed", "styles", "here"]),
    ],
)
def test_splits_all_line_ending_styles(raw: bytes, expected: list[str]) -> None:
    handler, _ = make_handler()
    handler._ingest(raw)
    assert [line.text for line in handler.drain()] == expected


def test_a_trailing_cr_is_held_back_in_case_it_is_half_a_crlf() -> None:
    handler, _ = make_handler()
    handler._ingest(b"status\r")
    assert handler.drain() == []


def test_a_held_back_cr_line_is_released_once_the_port_goes_quiet() -> None:
    """A bare-CR sketch that prints once and waits must still be readable.

    Two quiet ticks are required, so a CRLF genuinely split across reads — which
    resolves in microseconds — is never released early.
    """
    handler, _ = make_handler()
    handler._ingest(b"status\r")

    handler.flush_stale_partial()  # first tick: data arrived since last check
    assert handler.drain() == []

    handler.flush_stale_partial()  # second tick: nothing new, release it
    assert [line.text for line in handler.drain()] == ["status"]


def test_a_split_crlf_survives_a_flush_tick_without_emitting_a_blank_line() -> None:
    handler, _ = make_handler()
    handler._ingest(b"value\r")
    handler.flush_stale_partial()
    handler._ingest(b"\nnext\n")
    handler.flush_stale_partial()

    assert [line.text for line in handler.drain()] == ["value", "next"]


def test_a_partial_line_waits_for_its_terminator() -> None:
    handler, _ = make_handler()
    handler._ingest(b"incomp")
    assert handler.drain() == []
    handler._ingest(b"lete\n")
    assert [line.text for line in handler.drain()] == ["incomplete"]


def test_a_split_crlf_is_not_treated_as_two_breaks() -> None:
    """A chunk boundary landing between CR and LF must not emit a blank line."""
    handler, _ = make_handler()
    handler._ingest(b"value\r")
    assert handler.drain() == []
    handler._ingest(b"\nnext\n")
    assert [line.text for line in handler.drain()] == ["value", "next"]


def test_undecodable_bytes_are_replaced_not_raised() -> None:
    """§6.2 — opaque text, decoded with error-replacement."""
    handler, _ = make_handler()
    handler._ingest(b"good \xff\xfe bytes\n")
    (line,) = handler.drain()
    assert line.text.startswith("good ")
    assert line.text.endswith(" bytes")


def test_a_sketch_that_never_sends_a_newline_cannot_grow_the_buffer_forever() -> None:
    handler, _ = make_handler()
    handler._ingest(b"x" * (handler_module.MAX_PARTIAL_BYTES + 10))
    emitted = handler.drain()
    assert len(emitted) == 1
    assert len(handler._buf) == 0


# --- ring buffer and batching --------------------------------------------


def test_scrollback_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, _ = make_handler()
    handler._ingest(b"".join(f"line{i}\n".encode() for i in range(RING_CAPACITY + 50)))
    scrollback = handler.scrollback()
    assert len(scrollback) == RING_CAPACITY
    # Oldest lines are the ones dropped.
    assert scrollback[-1].text == f"line{RING_CAPACITY + 49}"


def test_drain_takes_everything_and_leaves_nothing() -> None:
    handler, _ = make_handler()
    handler._ingest(b"a\nb\nc\n")
    assert len(handler.drain()) == 3
    assert handler.drain() == []


def test_draining_does_not_disturb_scrollback() -> None:
    handler, _ = make_handler()
    handler._ingest(b"a\nb\n")
    handler.drain()
    assert [line.text for line in handler.scrollback()] == ["a", "b"]


# --- open / close / send --------------------------------------------------


def test_open_moves_to_passthrough_and_close_returns_to_idle(fake_port) -> None:
    handler, changes = make_handler()
    assert handler.state is PortState.IDLE

    handler.open_passthrough("/dev/fake", 115200)
    assert handler.state is PortState.PASSTHROUGH
    assert fake_port[0].baudrate == 115200

    handler.close_passthrough()
    assert handler.state is PortState.IDLE
    assert fake_port[0].closed is True


def test_a_failed_open_lands_in_error_not_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """§4 — failures surface as ERROR, never a silent fall back to IDLE."""

    def explode(*_args, **_kwargs):
        raise serial.SerialException("port busy")

    monkeypatch.setattr(handler_module.serial, "Serial", explode)
    handler, _ = make_handler()

    with pytest.raises(serial.SerialException):
        handler.open_passthrough("/dev/fake", 115200)

    assert handler.state is PortState.ERROR


@pytest.mark.parametrize(("name", "suffix"), sorted(LINE_ENDINGS.items()))
def test_line_ending_is_appended_to_sent_text(fake_port, name: str, suffix: str) -> None:
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)
    handler.write("PING", name)
    assert bytes(fake_port[0].written) == f"PING{suffix}".encode()


def test_sent_commands_are_echoed_into_scrollback(fake_port) -> None:
    """§6.3 — sent and received history interleave and stay reviewable."""
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)
    handler._ingest(b"from board\n")
    handler.write("to board", "lf")

    assert [(l.dir, l.text) for l in handler.scrollback()] == [
        ("rx", "from board"),
        ("tx", "to board"),
    ]


def test_the_echo_records_the_text_without_the_line_ending(fake_port) -> None:
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)
    handler.write("CMD", "crlf")
    assert handler.scrollback()[0].text == "CMD"


@pytest.mark.parametrize(
    "state", [PortState.IDLE, PortState.FLASHING, PortState.RESETTING, PortState.IN_SESSION]
)
def test_send_is_refused_outside_passthrough(state: PortState) -> None:
    """§6.3 — enforced in the sidecar, not just by disabling the UI input."""
    handler, _ = make_handler()
    handler._state = state

    with pytest.raises(PortBusy):
        handler.write("PING", "lf")


def test_opening_while_in_session_is_an_illegal_transition() -> None:
    handler, _ = make_handler()
    handler._state = PortState.IN_SESSION

    with pytest.raises(IllegalTransition):
        handler.open_passthrough("/dev/fake", 115200)


# --- §3.3 release / auto-resume ------------------------------------------


def test_release_from_passthrough_reports_that_it_should_resume(fake_port) -> None:
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)

    should_resume = handler.release_for(PortState.FLASHING, "flash requested")

    assert should_resume is True
    assert handler.state is PortState.FLASHING
    # The port must be cleanly released before arduino-cli takes it.
    assert fake_port[0].closed is True


def test_release_from_idle_reports_no_resume() -> None:
    handler, _ = make_handler()
    assert handler.release_for(PortState.FLASHING, "flash requested") is False


def test_error_is_acknowledged_back_to_idle() -> None:
    handler, _ = make_handler()
    handler.force_error("board vanished")
    assert handler.state is PortState.ERROR

    assert handler.acknowledge_error() is PortState.IDLE
