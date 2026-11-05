"""The parameter handshake of a session start — `ARCHITECTURE.md#entering-in_session`,
`TASKS.md#the-start-line`.

READY → capped `SET` lines, each answered `PARAMS <n> <crc32>` → `START SEED=<n>`
only if the answer matches what was sent. Driven through a scripted board
(`tests/scripted_board.py`) that answers the way the firmware does
(`BehaviorBox.h`'s `applySetLine`), including
the ways it can go wrong: a line cut short, a key it does not parse, a value it
clamps, and a sketch that does not speak `SET` at all.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.handler import PortHandler
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.protocol import ErrCode
from ephymeris_sidecar.tasks.profile import parse_profile
from ephymeris_sidecar.tasks.start_command import StartRefused, build_start_command

from .scripted_board import Boards, ScriptedBoard, clamping, running_params, silent

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


#: Every board this test's handler opened.
boards = Boards()


def boot(board: ScriptedBoard, interp: str | None = "1") -> None:
    """What a sketch prints as it starts: the interpreter it runs, when it
    announces one, then READY."""
    if interp is not None:
        board.say(f"INTERP={interp}\r\n")
    board.say("READY\r\n")


@pytest.fixture(autouse=True)
def _fresh_boards(monkeypatch: pytest.MonkeyPatch):
    boards.opened.clear()
    monkeypatch.setattr(handler_module, "SESSION_SEED_WINDOW_S", 0.2)
    monkeypatch.setattr(handler_module, "SESSION_READY_TIMEOUT_S", 2.0)
    monkeypatch.setattr(handler_module, "SESSION_PARAMS_TIMEOUT_S", 0.4)
    yield boards


_loop = asyncio.new_event_loop()
_created: list[PortHandler] = []


@pytest.fixture(autouse=True)
def _shutdown():
    yield
    while _created:
        _created.pop().shutdown()


class Run:
    """One claimed session and everything its callbacks heard. `board` sets
    how the board's firmware takes and answers `SET` (`ScriptedBoard`'s `cap`,
    `known` and `answer`); START is answered with the run's `seed`."""

    def __init__(self, command, seed: int = SEED, **board) -> None:  # noqa: ANN001, ANN003
        self.handler = PortHandler(1, _loop, lambda *args: None, boards)
        _created.append(self.handler)
        self.ready: list[tuple[int | None, int | None]] = []
        self.refused: list[StartRefused] = []
        self.strobes: list[tuple[int, int]] = []
        self.handler.claim_session(
            "/dev/fake",
            115200,
            command,
            seed,
            lambda seed, announced: self.ready.append((seed, announced.interp)),
            lambda code, ts: self.strobes.append((code, ts)),
            on_refused=self.refused.append,
        )
        self.board = wait_for(lambda: boards.opened) and boards.opened[0]
        # Nothing reaches the firmware before READY, so it can be set up here.
        self.board.seed_on_start = seed
        for name, value in board.items():
            setattr(self.board, name, value)


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

    boot(run.board)
    assert wait_for(lambda: run.ready)

    assert run.board.sent() == ["BEGIN", "SET ITI=1000 PRM=1001", f"START SEED={SEED}"]
    assert run.ready == [(SEED, 1)]
    assert run.handler.state is PortState.IN_SESSION


def test_each_set_line_waits_for_the_answer_to_the_one_before() -> None:
    """The Mega's receive buffer is 64 bytes: a second line sent before the first
    is parsed could overrun it."""
    keys = [f"K{i:02d}" for i in range(30)]
    command = build_start_command(_profile(*keys), {})
    assert len(command.set_lines) > 2

    run = Run(command)
    # A board that answers a line only when the host nudges it: hold PARAMS back.
    held: list[list[str]] = []

    def hold(tokens: list[str]) -> list[str]:
        held.append(list(tokens))
        return []

    run.board.answer = hold
    boot(run.board)
    assert wait_for(lambda: held)
    time.sleep(0.2)
    assert run.board.sent() == ["BEGIN", command.set_lines[0]]  # the second waits

    run.board.answer = running_params
    run.board.say("".join(f"{line}\r\n" for line in running_params(held[0])))
    assert wait_for(lambda: run.ready)
    assert run.board.sent()[: len(command.set_lines) + 1] == ["BEGIN", *command.set_lines]
    assert run.board.sent()[-1] == f"START SEED={SEED}"


def test_the_interpreter_the_board_announced_reaches_the_file_header() -> None:
    run = Run(build_start_command(_profile("ITI"), {}))
    boot(run.board, interp="7")
    assert wait_for(lambda: run.ready)
    assert run.ready[0][1] == 7


def test_a_board_that_announces_no_interpreter_is_recorded_as_none() -> None:
    run = Run(build_start_command(_profile("ITI"), {}))
    boot(run.board, interp=None)
    assert wait_for(lambda: run.ready)
    assert run.ready[0][1] is None


# --- the three refusals ------------------------------------------------------


def _refused(run: Run) -> StartRefused:
    boot(run.board)
    assert wait_for(lambda: run.refused), "the start was not refused"
    assert wait_for(lambda: run.handler.state is PortState.ERROR)
    assert not any(line.startswith("START") for line in run.board.sent()), "START went out anyway"
    assert run.ready == []
    return run.refused[0]


def test_a_truncated_line_refuses_the_start() -> None:
    # "SET ITI=1000 PRM=1001" arrives as "SET ITI=1000 PR"
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {}), cap=14))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "count"  # the cut key is no key at all


def test_a_value_cut_short_refuses_the_start() -> None:
    # "SET ITI=1000 PRM=10"
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {}), cap=19))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "crc"


def test_a_key_the_firmware_does_not_parse_refuses_the_start() -> None:
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {}), known={"ITI"}))
    assert refused.code == ErrCode.PARAMS_MISMATCH
    assert refused.reason == "count"
    assert "1 of 2" in str(refused)


def test_a_value_the_board_clamps_refuses_the_start_naming_it() -> None:
    refused = _refused(Run(build_start_command(_profile("ITI", "PRM"), {}), answer=clamping("PRM")))
    assert refused.code == ErrCode.PARAMS_CLAMPED
    assert refused.detail == {"keys": ["PRM"]}


def test_an_older_sketch_that_never_answers_is_refused_with_a_reflash_message() -> None:
    refused = _refused(Run(build_start_command(_profile("ITI"), {}), answer=silent))
    assert refused.code == ErrCode.FIRMWARE_OUTDATED
    assert "reflash" in str(refused).lower()


def test_the_port_is_released_to_error_so_the_operator_can_acknowledge_it() -> None:
    run = Run(build_start_command(_profile("ITI"), {}), answer=silent)
    _refused(run)
    assert run.board.closed
    assert run.handler.acknowledge_error() is PortState.IDLE
