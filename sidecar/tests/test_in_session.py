"""`IN_SESSION` entry/exit and strobe parsing — `ARCHITECTURE.md#entering-in_session`, `ARCHITECTURE.md#clean-exit`.

Driven through a scripted board (`tests/scripted_board.py`), so the handshake sequence and the
`^\\d{1,3}\\t\\d+$` line-recognition rule are exercised without hardware.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.handler import PortHandler
from ephymeris_sidecar.ports.states import IllegalTransition, PortState
from ephymeris_sidecar.tasks.profile import parse_profile
from ephymeris_sidecar.tasks.start_command import build_start_command

from .scripted_board import Boards, ScriptedBoard

#: A run with nothing to set: one bare `SET`, answered `PARAMS 0 0`.
CMD = build_start_command(None, {})
#: One with two parameters, for the tests that look at what went out.
TOKENS = build_start_command(
    parse_profile(
        {
            "taskName": "T",
            "config": [
                {"metadataKey": "cl", "wireKey": "CL", "label": "CL", "type": "int", "default": 0},
                {"metadataKey": "lazy", "wireKey": "LAZY", "label": "LAZY", "type": "bool", "default": True},
            ],
        }
    ),
    {},
)
SEED = 777


class LateBoard(ScriptedBoard):
    """A board whose port opens late on purpose.

    The session thread opens the port after `claim_session` returns, so a test
    must wait for it (`port_opened`). Every open here is late, so a test that
    reads `boards.opened` straight away fails on every run, rather than on the
    one run in many where the thread is slow to start.
    """

    OPEN_DELAY_S = 0.02

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        time.sleep(self.OPEN_DELAY_S)
        super().__init__(*args, **kwargs)


#: Every board this test's handlers opened.
boards = Boards(LateBoard)


@pytest.fixture(autouse=True)
def _fresh_boards(monkeypatch: pytest.MonkeyPatch):
    boards.opened.clear()
    # Keep the SEED window short so tests don't idle.
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.2)
    monkeypatch.setattr(handler_module, "SESSION_READY_TIMEOUT_S", 2.0)
    yield boards


_created: list[PortHandler] = []
_loop = asyncio.new_event_loop()


def make_handler(open_serial=boards) -> tuple[PortHandler, list[tuple]]:  # noqa: ANN001
    changes: list[tuple] = []
    handler = PortHandler(1, _loop, lambda *args: changes.append(args), open_serial)
    _created.append(handler)
    return handler, changes


@pytest.fixture(autouse=True)
def _shutdown():
    yield
    while _created:
        _created.pop().shutdown()


#: How long a wait gives the session thread before calling it a hang. A wait
#: returns as soon as its condition holds, so this costs a passing test
#: nothing; it only has to outlast a stall on a loaded machine.
DEADLINE_S = 30.0


def wait_for(predicate, timeout: float = DEADLINE_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def port_opened(index: int = 0) -> ScriptedBoard:
    """The `index`th port opened in this test, once the session thread has opened it.

    `claim_session` returns before its thread opens the port, so reading
    `boards.opened` straight after it races that thread.
    """
    assert wait_for(lambda: len(boards.opened) > index)
    return boards.opened[index]


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
    handler.open_passthrough("/dev/fake", 115200)
    with pytest.raises(IllegalTransition):
        handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)


def test_start_is_sent_only_after_ready() -> None:
    """`ARCHITECTURE.md#entering-in_session` steps 3–4 — the sidecar waits for READY before sending START."""
    handler, _ = make_handler()
    ready_seeds: list = []
    handler.claim_session(
        "/dev/fake", 115200, TOKENS, SEED, lambda s, i: ready_seeds.append(s), lambda c, t: None
    )
    port = port_opened()

    # Nothing written before READY arrives.
    time.sleep(0.1)
    assert bytes(port.written) == b""

    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    # The parameters first, as one capped SET line, and only then START.
    assert bytes(port.written) == b"BEGIN\nSET CL=0 LAZY=1\nSTART SEED=777\n"


def test_seed_line_is_captured_when_present() -> None:
    """`ARCHITECTURE.md#entering-in_session` step 5 / `TASKS.md#seed` — `SEED\\t<int>` right after START becomes trial_seed."""
    handler, _ = make_handler()
    seeds: list = []
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: seeds.append(s), lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.say("SEED\t288577176\n")

    assert wait_for(lambda: seeds)
    assert seeds[0] == 288577176


def test_a_missing_seed_resolves_after_the_window() -> None:
    handler, _ = make_handler()
    seeds: list = []
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: seeds.append(s), lambda c, t: None)
    port = port_opened()
    port.say("READY\n")

    assert wait_for(lambda: seeds)
    assert seeds[0] is None  # proceeded without one


def test_a_first_strobe_resolves_the_seed_window_immediately() -> None:
    handler, _ = make_handler()
    seeds: list = []
    strobes: list = []
    handler.claim_session(
        "/dev/fake", 115200, CMD, SEED, lambda s, i: seeds.append(s), lambda c, t: strobes.append((c, t))
    )
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.say("221\t0\n")

    assert wait_for(lambda: strobes)
    assert seeds == [None]
    assert strobes[0] == (221, 0)


def test_never_seeing_ready_lands_in_error() -> None:
    handler, changes = make_handler()
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    # READY timeout is patched to 2s.
    assert wait_for(lambda: handler.state is PortState.ERROR)


# --- step 6: strobe parsing (`ARCHITECTURE.md#entering-in_session`) ------


def test_strobe_lines_parse_into_code_and_timestamp() -> None:
    handler, _ = make_handler()
    strobes: list = []
    handler.claim_session(
        "/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: strobes.append((c, t))
    )
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.say("SEED\t42\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    port.say("221\t0\n222\t1000\n246\t3523555\n")

    assert wait_for(lambda: len(strobes) == 3)
    assert strobes == [(221, 0), (222, 1000), (246, 3523555)]


def test_non_strobe_lines_are_logged_but_not_data() -> None:
    """`ARCHITECTURE.md#entering-in_session` step 6 — stricter than PASSTHROUGH's opaque text handling."""
    handler, _ = make_handler()
    strobes: list = []
    handler.claim_session(
        "/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: strobes.append((c, t))
    )
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.say("SEED\t42\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    # Chatter, a 4-digit code, and a missing timestamp — none are data.
    port.say("hello world\n1234\t5\n99\n221\t7\n")

    assert wait_for(lambda: strobes)
    assert strobes == [(221, 7)]
    # But everything still appears in scrollback for the raw-log fallback.
    text = [line.text for line in handler.scrollback()]
    assert "hello world" in text
    assert "1234\t5" in text


# --- stop / exit (`ARCHITECTURE.md#clean-exit`) ---------------------------


def test_stop_writes_the_literal_stop_line() -> None:
    handler, _ = make_handler()
    claim = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))

    assert claim.request_stop() is True
    assert b"STOP\n" in bytes(port.written)
    # Sending STOP does not itself end the session (`ARCHITECTURE.md#clean-exit`).
    assert handler.state is PortState.IN_SESSION


def test_a_stop_after_the_session_ended_is_not_sent_and_does_not_raise() -> None:
    """`request_stop` never raises: End sends STOP to every running box, and a
    box whose port has already left the session must not stop the others."""
    handler, _ = make_handler()
    claim = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.unplug()
    assert wait_for(lambda: handler.state is PortState.ERROR)

    assert claim.request_stop() is False
    assert b"STOP" not in bytes(port.written)


def test_clean_end_returns_to_idle() -> None:
    handler, _ = make_handler()
    claim = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    # IN_SESSION is set before the port even opens, so it says nothing about the
    # handshake; START going out does.
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in port.written)

    claim.release("BF_END_SESSION received")
    assert handler.state is PortState.IDLE
    assert port.closed is True


def slow_open(fails: bool = False):  # noqa: ANN201
    """An open that takes a while, as a COM port's can. The board counts as
    opened when the open begins, so a test can end the run while it is under way."""

    def open_serial(*args, **kwargs) -> ScriptedBoard:  # noqa: ANN002, ANN003
        board = boards(*args, **kwargs)
        time.sleep(0.2)
        if fails:
            raise handler_module.serial.SerialException("could not open port")
        return board

    return open_serial


def test_ending_while_the_port_opens_neither_stalls_nor_leaves_it_open() -> None:
    """Teardown joins the session thread while holding the handler lock. A
    thread that blocked on that lock to publish its port would hold teardown
    for the whole join timeout, and return IDLE with the port still open."""
    handler, _ = make_handler(slow_open())
    claim = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    assert wait_for(lambda: boards.opened)

    started = time.monotonic()
    claim.release("operator ended")
    assert time.monotonic() - started < 0.6
    assert handler.state is PortState.IDLE
    assert boards.opened[0].closed is True


def test_a_failure_after_the_session_ended_changes_nothing() -> None:
    """The thread no longer owns the port once told to stop, so an open that
    fails late must not turn a cleanly ended box into ERROR."""
    handler, _ = make_handler(slow_open(fails=True))
    claim = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    assert wait_for(lambda: boards.opened)

    claim.release("operator ended")
    time.sleep(0.4)  # past the failing open
    assert handler.state is PortState.IDLE


# --- board drop = hard stop (`ARCHITECTURE.md#board-drop`) ---------------


def test_a_board_drop_mid_session_goes_to_error() -> None:
    """`ARCHITECTURE.md#board-drop` — always a hard stop, reusing the existing ERROR state."""
    handler, changes = make_handler()
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)

    port.unplug()
    assert wait_for(lambda: handler.state is PortState.ERROR)
    drain_loop()

    transition = [c for c in changes if c[2] is PortState.ERROR][-1]
    assert transition[1] is PortState.IN_SESSION  # came straight from IN_SESSION
    assert "disconnected" in transition[3]


def test_a_stalled_session_thread_is_waited_for_not_raced(monkeypatch) -> None:
    """A loaded machine can stall the session thread for seconds before it
    opens the port. The tests wait for what the thread does, however long it
    takes, so a stall makes them slower, never red."""
    monkeypatch.setattr(LateBoard, "OPEN_DELAY_S", 3.5)
    handler, _ = make_handler()
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.unplug()
    assert wait_for(lambda: handler.state is PortState.ERROR)


def test_error_clears_through_the_existing_ack() -> None:
    """`ARCHITECTURE.md#board-drop` — no new recovery logic; the ordinary port.error.ack path clears it."""
    handler, _ = make_handler()
    handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: handler.state is PortState.IN_SESSION)
    port.unplug()
    assert wait_for(lambda: handler.state is PortState.ERROR)

    assert handler.acknowledge_error() is PortState.IDLE


# --- the claim's promises (`ports/handler.py` SessionClaim) -----------------------


def test_a_refused_claim_starts_nothing() -> None:
    handler, _ = make_handler()
    handler.force_error("board never reported READY")
    with pytest.raises(IllegalTransition):
        handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    time.sleep(0.1)
    assert boards.opened == []  # no session thread, no port opened
    assert handler.state is PortState.ERROR


def test_a_lost_session_is_told_to_its_claim_once() -> None:
    handler, _ = make_handler()
    lost: list[str] = []
    claim = handler.claim_session(
        "/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None, lost.append
    )
    port = port_opened()
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))
    port.unplug()
    assert wait_for(lambda: handler.state is PortState.ERROR)
    drain_loop()

    assert len(lost) == 1 and "disconnected" in lost[0]
    claim.release("operator stop")  # the ERROR stands
    handler.force_error("again")
    drain_loop()
    assert handler.state is PortState.ERROR and len(lost) == 1


def test_release_is_idempotent_and_never_loses() -> None:
    handler, changes = make_handler()
    lost: list[str] = []
    claim = handler.claim_session(
        "/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None, lost.append
    )
    claim.release("done")
    claim.release("done again")
    drain_loop()

    assert handler.state is PortState.IDLE
    assert [(c[1], c[2]) for c in changes] == [
        (PortState.IDLE, PortState.IN_SESSION), (PortState.IN_SESSION, PortState.IDLE),
    ]
    assert lost == []


def test_an_old_claim_cannot_end_a_newer_run() -> None:
    """A late release from a finished run must not end the box's next one."""
    handler, _ = make_handler()
    first = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    first_thread = handler._reader
    first.release("first run over")
    # Teardown's join gives up after a second; wait for the first run's thread
    # itself, so a port it opens late isn't taken for the second run's.
    first_thread.join(DEADLINE_S)
    assert not first_thread.is_alive()
    opened = len(boards.opened)
    second = handler.claim_session("/dev/fake", 115200, CMD, SEED, lambda s, i: None, lambda c, t: None)
    port = port_opened(opened)
    port.say("READY\n")
    assert wait_for(lambda: b"START" in bytes(port.written))

    first.release("late")
    assert first.request_stop() is False
    assert handler.state is PortState.IN_SESSION
    assert second.request_stop() is True
