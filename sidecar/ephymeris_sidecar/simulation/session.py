"""One simulated session: the firmware started as a board is, an animal in the box.

`simulate` hands the simulator its trial table (`tasksim.cpp`), then takes it
through the start handshake a session takes a board through
(`TASKS.md#confirming-the-parameters`) with the `SET` lines `build_start_command`
writes for the task, and answers each output it switches with the animal's
beams. What comes back is the strobe stream that board would have sent.

A session may run `GRACE_MS` past its limit to reach its next trial boundary,
and its simulator is killed after `WALL_SECONDS` of real time.
"""

from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

from ..rig import registry
from ..taskdef import generate, rows
from ..taskdef.model import TaskDefinition
from ..tasks.profile import TaskProfile
from ..tasks.start_command import ParamsExchange, StartRefused, build_start_command
from . import build
from .animal import Animal, Condition, Rat
from .errors import SimulationError

DEFAULT_LIMIT_MS = 60 * 60_000
MAX_LIMIT_MS = 24 * 60 * 60_000
GRACE_MS = 30 * 60_000
WALL_SECONDS = 120.0
SEED_RANGE = (1, 2**31 - 2)

ENDED_BY_TRIALS = "trials"
ENDED_BY_LIMIT = "timeLimit"
ENDED_BY_CUT = "cutOff"

_STROBE = re.compile(r"^(\d+)\t(\d+)$")
_OUTPUT = re.compile(r"^@ (\d+) (\w+) ([01])$")
_ANNOUNCED = re.compile(r"^(INTERP|STREAM)=(\d+)$")
_PAST_LIMIT = "the session ran past its limit"


@dataclass(frozen=True)
class Simulated:
    """What one simulated board sent, and what ended it."""

    profile: TaskProfile
    params: dict[str, Any]
    strobes: list[list[int]]
    seed: int
    limit_ms: int
    ended_by: str
    interp: int | None
    stream: int | None


def table_of(definition: TaskDefinition) -> tuple[list[str], dict[int, Condition]]:
    """The simulator's `CODE` and `ROW` lines for a task, and what each odor
    line asks of the animal. The rows are `generate.task_trials_h`'s, in its
    order, dropped by its rule."""
    channels = registry.channels()
    vocab = registry.vocabulary()
    lines = [f"CODE {entry.name} {entry.code}" for entry in vocab]
    conditions: dict[int, Condition] = {}
    slot = 0
    for trial in definition.trials:
        row = rows.resolve_row(trial, channels, vocab)
        if row is None:
            continue
        type_name = generate.type_name(slot)
        slot += 1
        if type_name not in vocab:
            raise SimulationError(
                f"The vocabulary has no {type_name} for this task's row {slot} (TSK115)."
            )
        onset, type_code = vocab.code_of(trial.onset_strobe), vocab.code_of(type_name)
        if trial.is_go:
            right = row.port.name == "right_well"
            fluid = vocab.code_of(row.slot["reward_code"])
            stop = vocab.code_of(row.slot["reward_stop_code"])
            lines.append(
                f"ROW 1 {row.odor_index} {'R' if right else 'L'} {row.reward_index} "
                f"{onset} {fluid} {stop} {trial.reward_time} {type_code}"
            )
            conditions[row.odor_index] = Condition("right" if right else "left")
        else:
            lines.append(f"ROW 0 {row.odor_index} N -1 {onset} 0 0 0 {type_code}")
            conditions[row.odor_index] = Condition(None)
    if not slot:
        raise SimulationError("This task has no trial type a box could present (TSK108).")
    return lines, conditions


def simulate(definition: TaskDefinition, animal: Animal, seed: int, *,
             limit_ms: int = DEFAULT_LIMIT_MS) -> Simulated:
    """Run `definition` at its own parameter values against `animal`.

    `seed` is the run's trial seed and seeds the animal too, so one number
    repeats a simulation. The session ends as a recorded one does: at the trial
    cap, or at the first trial boundary after the `STOP` sent at `limit_ms`.
    """
    if not SEED_RANGE[0] <= seed <= SEED_RANGE[1]:
        raise SimulationError(f"A trial seed runs from {SEED_RANGE[0]} to {SEED_RANGE[1]}.")
    if not 1 <= limit_ms <= MAX_LIMIT_MS:
        raise SimulationError("A session's time limit runs from 1 ms to 24 h.")

    profile = generate.build_profile(definition)
    params = {field.metadata_key: field.default for field in profile.config}
    command = build_start_command(profile, params)
    table, conditions = table_of(definition)
    table += [f"STOP_AT {limit_ms}", f"LIMIT {limit_ms + GRACE_MS}", "END"]
    simulator = build.locate(definition.selection_mode)

    process = subprocess.Popen(
        [str(simulator)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
    )
    overdue = threading.Timer(WALL_SECONDS, process.kill)
    overdue.start()
    try:
        return _converse(process, table, command, Rat(animal, conditions, seed),
                         Simulated(profile, params, [], seed, limit_ms, ENDED_BY_TRIALS, None, None))
    except (BrokenPipeError, OSError) as error:
        raise SimulationError(f"The task simulator stopped answering ({error}).") from error
    finally:
        overdue.cancel()
        process.kill()
        process.wait()


def _converse(process: subprocess.Popen, table: list[str], command, rat: Rat,
              run: Simulated) -> Simulated:
    said = process.stdin
    heard = process.stdout

    def say(*lines: str) -> None:
        said.write("".join(f"{line}\n" for line in lines))
        said.flush()

    def hear() -> str:
        line = heard.readline()
        if not line:
            raise SimulationError("The task simulator ended before its session did.")
        line = line.rstrip("\r\n")
        if line.startswith("@ABORT") and _PAST_LIMIT not in line:
            raise SimulationError(f"The task simulator refused the task: {line[7:]}.")
        return line

    say(*table)
    announced: dict[str, int] = {}
    while (line := hear()) != "READY":
        if found := _ANNOUNCED.match(line):
            announced[found.group(1)] = int(found.group(2))

    exchange = ParamsExchange(command)
    say(command.begin_line, exchange.first_line)
    try:
        while not exchange.done:
            following = exchange.hear(hear())
            if following is not None:
                say(following)
    except StartRefused as refused:
        raise SimulationError(str(refused)) from refused
    say(command.start_line(run.seed))

    strobes: list[list[int]] = []
    stopped = False
    ended_by = ENDED_BY_TRIALS
    while True:
        line = hear()
        if line == "@END":
            ended_by = ENDED_BY_LIMIT if stopped else ENDED_BY_TRIALS
            break
        if line.startswith("@ABORT"):
            ended_by = ENDED_BY_CUT
            break
        if line.startswith("@STOP"):
            stopped = True
            continue
        if strobe := _STROBE.match(line):
            strobes.append([int(strobe.group(1)), int(strobe.group(2))])
            continue
        output = _OUTPUT.match(line)
        if output is None:
            continue
        say(*rat.sense(int(output.group(1)), output.group(2), int(output.group(3))), ".")

    return Simulated(run.profile, run.params, strobes, run.seed, run.limit_ms, ended_by,
                     announced.get("INTERP"), announced.get("STREAM"))
