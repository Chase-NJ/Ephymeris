"""The parameter handshake of a session start — `ARCHITECTURE.md#entering-in_session`,
`TASKS.md#the-start-line`.

READY → capped `SET` lines, each answered `PARAMS <n> <crc32>` → `START SEED=<n>`
only if the answer matches what was sent. Driven through a fake board that
answers the way the firmware does (`BehaviorBox.h`'s `applySetLine`), including
the ways it can go wrong: a line cut short, a key it does not parse, a value it
clamps, and a sketch that does not speak `SET` at all.
"""

from __future__ import annotations

import asyncio
import threading
import time
import zlib

import pytest

from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.handler import PortHandler
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.protocol import ErrCode
from ephymeris_sidecar.tasks.profile import parse_profile
from ephymeris_sidecar.tasks.start_command import StartRefused, build_start_command

SEED = 424242


def _profile(*keys: str):
    return parse_profile(
        {
            "taskName": "T",
            "config": [
                {"metadataKey": k.lower(), "wireKey": k, "label": k, "type": "int", "default": 1000 + i}
                for i, k in enumerate(keys)
            ],
        }
    )


class Board:
    """A fake Mega that speaks the handshake. One per port opened."""

    instances: list["Board"] = []
    #: Keys the firmware parses. Anything else is ignored, uncounted and unhashed.
    known: set[str] = {"ITI", "PRM", "NT"}
    #: Keys whose value the board's clamp would move.
    clamps: set[str] = set()
    #: The board's line buffer: a longer line is cut to this many characters.
    cap: int = 127
    #: A sketch that predates `SET`: reads lines, answers nothing.
    silent: bool = False
    announce_interp: str | None = "1"

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.closed = False
        self.written = bytearray()
        self._out = bytearray()
        self._lock = threading.Lock()
        self._tokens: list[str] = []
        Board.instances.append(self)

    # --- the board's side ---------------------------------------------------

    def say(self, text: str) -> None:
        with self._lock:
            self._out.extend(text.encode())

    def boot(self) -> None:
        if self.announce_interp is not None:
            self.say(f"INTERP={self.announce_interp}\r\n")
        self.say("READY\r\n")

    def _hear(self, line: str) -> None:
        if self.silent:
            return
        line = line[: self.cap]
        if line == "SET" or line.startswith("SET "):
            for token in line.split()[1:]:
                key, eq, _value = token.partition("=")
                if eq and key in self.known:
                    self._tokens.append(token)
            clamped = [t.partition("=")[0] for t in self._tokens if t.partition("=")[0] in self.clamps]
            crc = zlib.crc32(" ".join(self._tokens).encode())
            reply = "".join(f"CLAMPED {key}\r\n" for key in clamped)
            self.say(reply + f"PARAMS {len(self._tokens)} {crc}\r\n")
        elif line.startswith("START"):
            self.say("SEED\t" + line.partition("SEED=")[2] + "\r\n")

    # --- the serial.Serial surface -----------------------------------------

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._out)

    def read(self, size: int = 1) -> bytes:
        with self._lock:
            if self._out:
                chunk = bytes(self._out[:size])
                del self._out[:size]
                return chunk
        time.sleep(handler_module.READ_TIMEOUT_S)
        return b""

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        for line in data.decode().splitlines():
            self._hear(line)
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def sent(self) -> list[str]:
        return bytes(self.written).decode().splitlines()


@pytest.fixture(autouse=True)
def board(monkeypatch: pytest.MonkeyPatch):
    Board.instances = []
    monkeypatch.setattr(Board, "known", {"ITI", "PRM", "NT"})
    monkeypatch.setattr(Board, "clamps", set())
    monkeypatch.setattr(Board, "cap", 127)
    monkeypatch.setattr(Board, "silent", False)
    monkeypatch.setattr(Board, "announce_interp", "1")
    monkeypatch.setattr(handler_module.serial, "Serial", Board)
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.2)
    monkeypatch.setattr(handler_module, "SESSION_READY_TIMEOUT_S", 2.0)
    monkeypatch.setattr(handler_module, "SESSION_PARAMS_TIMEOUT_S", 0.4)
    yield Board


_loop = asyncio.new_event_loop()
_created: list[PortHandler] = []


@pytest.fixture(autouse=True)
def _shutdown():
    yield
    while _created:
        _created.pop().shutdown()


class Run:
    """One claimed session and everything its callbacks heard."""

    def __init__(self, command, seed: int = SEED) -> None:
        self.handler = PortHandler(1, _loop, lambda *args: None)
        _created.append(self.handler)
        self.ready: list[tuple[int | None, int | None]] = []
        self.refused: list[StartRefused] = []
        self.strobes: list[tuple[int, int]] = []
        self.handler.claim_session(
            "/dev/fake",
            115200,
            command,
            seed,
            lambda seed, interp: self.ready.append((seed, interp)),
            lambda code, ts: self.strobes.append((code, ts)),
            on_refused=self.refused.append,
        )
        self.board = wait_for(lambda: Board.instances) and Board.instances[0]


def wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- a clean handshake -------------------------------------------------------


def test_the_set_lines_go_out_after_ready_and_start_only_after_params_match() -> None:
    run = Run(build_start_command(_profile("ITI", "PRM"), {}))
    time.sleep(0.1)
    assert run.board.sent() == []  # nothing before READY

    run.board.boot()
    assert wait_for(lambda: run.ready)

    assert run.board.sent() == ["SET ITI=1000 PRM=1001", f"START SEED={SEED}"]
    assert run.ready == [(SEED, 1)]
    assert run.handler.state is PortState.IN_SESSION


def test_each_set_line_waits_for_the_answer_to_the_one_before() -> None:
    """The Mega's receive buffer is 64 bytes: a second line sent before the first
    is parsed could overrun it."""
    keys = [f"K{i:02d}" for i in range(30)]
    Board.known = set(keys)
    command = build_start_command(_profile(*keys), {})
    assert len(command.set_lines) > 2

    run = Run(command)
    # A board that answers a line only when the host nudges it: hold PARAMS back.
    original = run.board._hear
    held: list[str] = []
    run.board._hear = held.append  # type: ignore[method-assign]
    run.board.boot()
    assert wait_for(lambda: held)
    time.sleep(0.2)
    assert held == [command.set_lines[0]]  # the second waits

    run.board._hear = original  # type: ignore[method-assign]
    original(held[0])
    assert wait_for(lambda: run.ready)
    assert run.board.sent()[: len(command.set_lines)] == list(command.set_lines)
    assert run.board.sent()[-1] == f"START SEED={SEED}"


def test_the_interpreter_the_board_announced_reaches_the_file_header() -> None:
    Board.announce_interp = "7"
    run = Run(build_start_command(_profile("ITI"), {}))
    run.board.boot()
    assert wait_for(lambda: run.ready)
    assert run.ready[0][1] == 7


def test_a_board_that_announces_no_interpreter_is_recorded_as_none() -> None:
    Board.announce_interp = None
    run = Run(build_start_command(_profile("ITI"), {}))
    run.board.boot()
    assert wait_for(lambda: run.ready)
    assert run.ready[0][1] is None


# --- the three refusals ------------------------------------------------------


def _refused(run: Run) -> StartRefused:
    run.board.boot()
    assert wait_for(lambda: run.refused), "the start was not refused"
    assert wait_for(lambda: run.handler.state is PortState.ERROR)
    assert not any(line.startswith("START") for line in run.board.sent()), "START went out anyway"
    assert run.ready == []
    return run.refused[0]


def test_a_truncated_line_refuses_the_start() -> None:
    Board.cap = 14  # "SET ITI=1000 PRM=1001" arrives as "SET ITI=1000 PR"
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {})))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "count"  # the cut key is no key at all


def test_a_value_cut_short_refuses_the_start() -> None:
    Board.cap = 19  # "SET ITI=1000 PRM=10"
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {})))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "crc"


def test_a_key_the_firmware_does_not_parse_refuses_the_start() -> None:
    Board.known = {"ITI"}
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {})))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "count"
    assert "1 of 2" in str(refused)


def test_a_value_the_board_clamps_refuses_the_start_naming_it() -> None:
    Board.clamps = {"PRM"}
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {})))
    assert refused.code == ErrCode.PARAMS_CLAMPED
    assert refused.detail == {"keys": ["PRM"]}


def test_an_older_sketch_that_never_answers_is_refused_with_a_reflash_message() -> None:
    Board.silent = True
    refused = _refused(Run(build_start_command(_profile("ITI"), {})))
    assert refused.code == ErrCode.FIRMWARE_OUTDATED
    assert "reflash" in str(refused).lower()


def test_the_port_is_released_to_error_so_the_operator_can_acknowledge_it() -> None:
    Board.silent = True
    run = Run(build_start_command(_profile("ITI"), {}))
    _refused(run)
    assert run.board.closed
    assert run.handler.acknowledge_error() is PortState.IDLE
