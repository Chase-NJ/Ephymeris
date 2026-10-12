"""PortHandler — line splitting, ring buffer, batching, and send guards.

Exercises the handler against a fake serial port so the parsing and buffering
rules from `ARCHITECTURE.md#passthrough-read` can be checked without hardware.
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
from ephymeris_sidecar.ports.states import (
    IDLE_OR_CONSOLE,
    IllegalTransition,
    PortState,
    TakeRefused,
)


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
        #: Reads that found nothing, counted under the lock `feed` takes.
        self._empty_reads = 0

    def feed(self, data: bytes) -> None:
        with self._lock:
            self._to_read.extend(data)

    def fed(self, data: bytes, timeout: float = 2.0) -> None:
        """Feed `data` and return once the reader thread has taken all of it
        and come back for more: it reads, then splits, then reads again, so a
        later read that finds nothing means `data` has been split."""
        with self._lock:
            self._to_read.extend(data)
            before = self._empty_reads
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._empty_reads > before:
                    return
            time.sleep(0.005)
        raise AssertionError("the reader never took what was fed")

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._to_read)

    def read(self, size: int = 1) -> bytes:
        # Like a real port with a read timeout: what arrives while waiting is
        # returned; nothing by the deadline is an empty read. Returning at once
        # would turn the reader thread into a busy-spin and make the suite crawl.
        deadline = time.monotonic() + READ_TIMEOUT_S
        while True:
            with self._lock:
                if self._to_read:
                    chunk = bytes(self._to_read[:size])
                    del self._to_read[:size]
                    return chunk
                if time.monotonic() >= deadline:
                    self._empty_reads += 1
                    return b""
            time.sleep(0.005)

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
    """`changes` collects every announced change as `(box, from, to, reason)`."""
    changes: list[tuple] = []
    handler = PortHandler(1, _loop, lambda *args: changes.append(args))
    _created.append(handler)
    return handler, changes


def reading(fake_port: list[FakeSerial]) -> tuple[PortHandler, FakeSerial]:
    """A handler with its console open, and the board on the other end."""
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)
    return handler, fake_port[-1]


def announced(changes: list[tuple]) -> list[tuple[PortState, PortState]]:
    """What the handler announced: each change reaches its loop as a callback."""
    _loop.run_until_complete(asyncio.sleep(0))
    return [(old, new) for _box, old, new, _reason in changes]


def enter(handler: PortHandler, state: PortState) -> None:
    """Put a fresh handler in `state` the way the app does."""
    if state is PortState.IN_SESSION:
        handler.claim_session("/dev/fake", 115200, "START", lambda _seed: None, lambda _c, _t: None)
    elif state is PortState.PASSTHROUGH:
        handler.open_passthrough("/dev/fake", 115200)
    elif state is PortState.ERROR:
        handler.force_error("test")
    elif state is not PortState.IDLE:
        handler.release_for(state, "test")


@pytest.fixture(autouse=True)
def _shut_down_handlers():
    """Reader threads are daemons; without this they outlive their test."""
    yield
    while _created:
        _created.pop().shutdown()


# --- line splitting (`ARCHITECTURE.md#passthrough-read`) -----------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"one\ntwo\n", ["one", "two"]),
        (b"one\r\ntwo\r\n", ["one", "two"]),  # Arduino println emits CRLF
        (b"one\rtwo\r\n", ["one", "two"]),
        (b"mixed\nstyles\r\nhere\n", ["mixed", "styles", "here"]),
    ],
)
def test_splits_all_line_ending_styles(fake_port, raw: bytes, expected: list[str]) -> None:
    handler, board = reading(fake_port)
    board.fed(raw)
    assert [line.text for line in handler.drain()] == expected


def test_a_trailing_cr_is_held_back_in_case_it_is_half_a_crlf(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"status\r")
    assert handler.drain() == []


def test_a_held_back_cr_line_is_released_once_the_port_goes_quiet(fake_port) -> None:
    """A bare-CR sketch that prints once and waits must still be readable.

    Two quiet ticks are required, so a CRLF genuinely split across reads — which
    resolves in microseconds — is never released early.
    """
    handler, board = reading(fake_port)
    board.fed(b"status\r")

    handler.flush_stale_partial()  # first tick: data arrived since last check
    assert handler.drain() == []

    handler.flush_stale_partial()  # second tick: nothing new, release it
    assert [line.text for line in handler.drain()] == ["status"]


def test_a_split_crlf_survives_a_flush_tick_without_emitting_a_blank_line(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"value\r")
    handler.flush_stale_partial()
    board.fed(b"\nnext\n")
    handler.flush_stale_partial()

    assert [line.text for line in handler.drain()] == ["value", "next"]


def test_a_partial_line_waits_for_its_terminator(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"incomp")
    assert handler.drain() == []
    board.fed(b"lete\n")
    assert [line.text for line in handler.drain()] == ["incomplete"]


def test_a_split_crlf_is_not_treated_as_two_breaks(fake_port) -> None:
    """A chunk boundary landing between CR and LF must not emit a blank line."""
    handler, board = reading(fake_port)
    board.fed(b"value\r")
    assert handler.drain() == []
    board.fed(b"\nnext\n")
    assert [line.text for line in handler.drain()] == ["value", "next"]


def test_undecodable_bytes_are_replaced_not_raised(fake_port) -> None:
    """`ARCHITECTURE.md#passthrough-read` — opaque text, decoded with error-replacement."""
    handler, board = reading(fake_port)
    board.fed(b"good \xff\xfe bytes\n")
    (line,) = handler.drain()
    assert line.text.startswith("good ")
    assert line.text.endswith(" bytes")


def test_a_sketch_that_never_sends_a_newline_cannot_grow_the_buffer_forever(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"x" * (handler_module.MAX_PARTIAL_BYTES + 10))
    assert len(handler.drain()) == 1
    # Nothing was held back: the next line arrives on its own.
    board.fed(b"y\n")
    assert [line.text for line in handler.drain()] == ["y"]


# --- ring buffer and batching --------------------------------------------


def test_scrollback_is_capped(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"".join(f"line{i}\n".encode() for i in range(RING_CAPACITY + 50)))
    scrollback = handler.scrollback()
    assert len(scrollback) == RING_CAPACITY
    # Oldest lines are the ones dropped.
    assert scrollback[-1].text == f"line{RING_CAPACITY + 49}"


def test_drain_takes_everything_and_leaves_nothing(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"a\nb\nc\n")
    assert len(handler.drain()) == 3
    assert handler.drain() == []


def test_draining_does_not_disturb_scrollback(fake_port) -> None:
    handler, board = reading(fake_port)
    board.fed(b"a\nb\n")
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
    assert announced(changes) == [
        (PortState.IDLE, PortState.PASSTHROUGH), (PortState.PASSTHROUGH, PortState.IDLE),
    ]


def test_a_failed_open_lands_in_error_not_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ARCHITECTURE.md#states` — failures surface as ERROR, never a silent fall back to IDLE."""

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
    """`ARCHITECTURE.md#passthrough-send` — sent and received history interleave and stay reviewable."""
    handler, board = reading(fake_port)
    board.fed(b"from board\n")
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
def test_send_is_refused_outside_passthrough(fake_port, state: PortState) -> None:
    """`ARCHITECTURE.md#passthrough-send` — enforced in the sidecar, not just by disabling the UI input."""
    handler, _ = make_handler()
    enter(handler, state)
    assert handler.state is state

    with pytest.raises(PortBusy):
        handler.write("PING", "lf")


def test_opening_while_in_session_is_an_illegal_transition(fake_port) -> None:
    handler, _ = make_handler()
    enter(handler, PortState.IN_SESSION)

    with pytest.raises(IllegalTransition):
        handler.open_passthrough("/dev/fake", 115200)


# --- release / auto-resume (`ARCHITECTURE.md#exclusivity`) ---------------


def test_release_from_passthrough_reports_that_it_should_resume(fake_port) -> None:
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)

    should_resume = handler.release_for(
        PortState.FLASHING, "flash requested", from_=IDLE_OR_CONSOLE
    )

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


# --- each verb names the states it leaves (`ARCHITECTURE.md#port-verbs`) ----
#
# `TRANSITIONS` says which moves are ever legal; it cannot say who is asking.
# `FLASHING → IDLE` is legal because a flash lands there, not so a console
# close can free a port mid-upload; `ERROR → IDLE` belongs to the
# acknowledgement. Each verb refuses any state it does not leave, and leaves
# the port as it was.

S = PortState

#: verb → (the call, the states it is refused from).
REFUSED_FROM = {
    "close_passthrough": (
        lambda h: h.close_passthrough(),
        [S.FLASHING, S.RESETTING, S.IN_SESSION, S.ERROR],
    ),
    "finish_to_idle": (
        lambda h: h.finish_to_idle("done"),
        [S.PASSTHROUGH, S.IN_SESSION, S.ERROR],
    ),
    "acknowledge_error": (
        lambda h: h.acknowledge_error(),
        [S.PASSTHROUGH, S.FLASHING, S.RESETTING, S.IN_SESSION],
    ),
    "open_passthrough": (
        lambda h: h.open_passthrough("/dev/fake", 115200),
        [S.PASSTHROUGH, S.FLASHING, S.RESETTING, S.IN_SESSION, S.ERROR],
    ),
    # No `from_`: what a background job passes, which takes only an idle port.
    "release_for": (
        lambda h: h.release_for(S.FLASHING, "flash requested"),
        [S.PASSTHROUGH, S.FLASHING, S.RESETTING, S.IN_SESSION, S.ERROR],
    ),
}


@pytest.mark.parametrize(
    ("verb", "state"),
    [(verb, state) for verb, (_call, states) in REFUSED_FROM.items() for state in states],
)
def test_a_verb_refuses_a_state_it_does_not_leave(fake_port, verb: str, state: PortState) -> None:
    handler, changes = make_handler()
    enter(handler, state)
    before = announced(changes)
    opened = list(fake_port)

    with pytest.raises(IllegalTransition):
        REFUSED_FROM[verb][0](handler)

    assert handler.state is state
    assert announced(changes) == before
    # Nothing it held was closed, and nothing new was opened.
    if state is S.PASSTHROUGH:
        assert not opened[0].closed
    if state is not S.IN_SESSION:  # whose own thread opens the port when it likes
        assert fake_port == opened


def test_only_the_acknowledgement_leaves_error(fake_port) -> None:
    handler, changes = make_handler()
    handler.force_error("board vanished")
    for verb, (call, _states) in REFUSED_FROM.items():
        if verb == "acknowledge_error":
            continue
        with pytest.raises(IllegalTransition):
            call(handler)
    assert handler.state is PortState.ERROR

    assert handler.acknowledge_error() is PortState.IDLE
    assert announced(changes) == [(S.IDLE, S.ERROR), (S.ERROR, S.IDLE)]


@pytest.mark.parametrize("state", [S.FLASHING, S.RESETTING])
def test_a_flash_or_reset_lands_in_idle_or_back_in_its_console(fake_port, state: PortState) -> None:
    handler, _ = make_handler()
    enter(handler, state)
    assert handler.finish_to_idle("done") is S.IDLE

    enter(handler, state)
    assert handler.resume_passthrough("/dev/fake", 115200) is S.PASSTHROUGH


def test_release_for_hands_a_port_only_to_a_flash_or_reset() -> None:
    handler, _ = make_handler()
    with pytest.raises(ValueError):
        handler.release_for(S.IN_SESSION, "not a flash")
    assert handler.state is S.IDLE


def test_a_refused_take_says_the_port_was_not_taken(fake_port) -> None:
    """`TakeRefused` is how the flash queue tells "not taken" from a landing
    refused after the upload."""
    handler, _ = make_handler()
    handler.open_passthrough("/dev/fake", 115200)
    with pytest.raises(TakeRefused) as refused:
        handler.release_for(S.FLASHING, "a restore")
    assert (refused.value.current, refused.value.requested) == (S.PASSTHROUGH, S.FLASHING)


def test_a_lost_claim_hears_of_it_even_if_the_announcement_raises(fake_port) -> None:
    def announce(*_args) -> None:  # noqa: ANN002
        raise RuntimeError("a listener broke")

    handler = PortHandler(1, _loop, announce)
    _created.append(handler)
    lost: list[str] = []
    handler.claim_session(
        "/dev/fake", 115200, "START", lambda _seed: None, lambda _c, _t: None, lost.append
    )
    handler.force_error("board went away")
    _loop.run_until_complete(asyncio.sleep(0))

    assert lost == ["board went away"]
