"""A spine of phases -> BoxInterp.h's state table (`0003-phase-spine-task-model.md#interpreter-and-firmware`).

The generator's half of "a task is a phase spine, lowered to a state table".
`lower()` writes each phase as states exactly as BoxInterp.h's "Lowering the
first phases" describes, and returns the table as plain tuples in
`InterpStateRow` / `InterpEdgeRow` field order, so the same rows become the C
initialisers in `TaskSpine.h` and the `replay.Table` analytics replays.

**Pure and standard-library only**, like `analytics/stream/replay.py`: the
differential test (`extras/host_test/differential.py`) loads this file by
path and runs the tables it emits through both interpreters. Keep it free of
any import, relative ones included.

THE INPUT HAS ALREADY BEEN JUDGED. `taskdef/spine.py` validates a definition
and reports what is wrong with it; this refuses (`LoweringError`) only what it
cannot write at all, so a half-finished task still previews.

WHAT A TABLE IS INDEPENDENT OF. Pins never enter it: channels are bits, input
bit i is the i-th `digital_in` slot and output bit j the j-th `digital_out`
slot, in slot order. Durations and probabilities never enter it either: each
is a parameter slot the host sets by `SET` line. So one table serves every
tuning and every pin map.

PARAMETER SLOTS, in order:
    0       NT    the block's trial count, read by the session layer (BoxSpine.h)
    1..     T<i>  the timer of phase i, one per timed phase, in phase order
    then    RW1, RP1  the row's reward ms and reward probability in permille,
                  when the spine has an Outcome phase
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

#: The table format these tables are written in: BoxInterp.h's `INTERP_VERSION`,
#: which the spine runner announces as `INTERP=<n>`. A run's snapshot records
#: it beside the table, and replay refuses one it does not know. 1 is the trial
#: runner's, in the same numbering space (`analytics/stream/replay.py`).
INTERP_VERSION = 2

#: BoxInterp.h's constants (`INTERP_NONE`, `INTERP_RISE`, ...), mirrored.
NONE = 0xFF
RISE = 1
FALL = 2
STARTS_TRIAL = 0x01

#: The outcome classes a state can record (0003-phase-spine-task-model.md#phase-palette),
#: numbered from 1; 0 is "none". The core carries the number and never reads
#: it; replay reads it off the states a trial entered. Append only: a number
#: is recorded in every table a run's snapshot carries.
OUTCOME_CLASSES = (
    "correct",
    "wrong_response",
    "hold_broken",
    "omission",
    "withheld",
    "false_alarm",
    "abort_before_stimulus",
    "abort_during_sampling",
)
OUTCOME_CORRECT = 1

#: Where `flags` sits in a state row (`Lowered.states`).
_FLAGS = 10

#: The tracer's phases. Hold, Counter and the response window are #101 and #102.
PHASES = ("wait", "present", "delay", "outcome", "iti")

TRIALS_KEY = "NT"
REWARD_MS_KEY = "RW1"
REWARD_PERMILLE_KEY = "RP1"


class LoweringError(ValueError):
    """The spine cannot be written as a table at all."""


@dataclass(frozen=True)
class Lowered:
    """One spine's table, in BoxInterp.h's field order.

    `states[i]` is (outputs, watch, timer_min, timer_max, on_timeout, chance,
    on_hit, on_miss, edge_first, edge_count, flags, outcome); `edges[k]` is
    (input, edge, next); `params[s]` is the wire key of parameter slot s.
    `timers[i]` is phase i's wire key, or None for a phase with no timer.
    `phases[s]` is the index of the phase state s belongs to.
    """

    states: tuple[tuple[int, ...], ...]
    edges: tuple[tuple[int, int, int], ...]
    params: tuple[str, ...]
    timers: tuple[str | None, ...]
    phases: tuple[int, ...]


def timer_key(phase_index: int) -> str:
    return f"T{phase_index}"


def lower(phases: Sequence[dict[str, Any]], inputs: Sequence[str], outputs: Sequence[str]) -> Lowered:
    """The state table for `phases`, with `inputs` and `outputs` the slot ids in bit order."""
    if not phases:
        raise LoweringError("a spine needs at least one phase")
    kinds = [p.get("phase") for p in phases]
    for i, kind in enumerate(kinds):
        if kind not in PHASES:
            raise LoweringError(f"phase {i}: {kind!r} is not one of {PHASES}")
    if kinds.count("iti") != 1 or kinds[-1] != "iti" or len(phases) < 2:
        raise LoweringError("a spine ends in exactly one ITI, after at least one other phase")

    in_bit = {slot: i for i, slot in enumerate(inputs)}
    out_bit = {slot: j for j, slot in enumerate(outputs)}

    def input_bit(i: int, slot: Any) -> int:
        if slot not in in_bit:
            raise LoweringError(f"phase {i}: {slot!r} is not an input slot")
        return in_bit[slot]

    def output_mask(i: int, slots: Any) -> int:
        mask = 0
        for slot in slots or ():
            if slot not in out_bit:
                raise LoweringError(f"phase {i}: {slot!r} is not an output slot")
            mask |= 1 << out_bit[slot]
        return mask

    # Parameter slots: NT, then one timer per timed phase, then the row's two.
    params: list[str] = [TRIALS_KEY]
    timers: list[str | None] = []
    for i, p in enumerate(phases):
        timed = p["phase"] in ("present", "delay", "outcome", "iti") or (
            p["phase"] == "wait" and p.get("timeoutMs") is not None
        )
        timers.append(timer_key(i) if timed else None)
        if timed:
            params.append(timer_key(i))
    if "outcome" in kinds:
        params += [REWARD_MS_KEY, REWARD_PERMILLE_KEY]
    slot = {key: s for s, key in enumerate(params)}

    # First pass: where each phase's first state lands, so "next" and the ITI
    # resolve before any row is written. An Outcome is three states.
    first: list[int] = []
    count = 0
    for p in phases:
        first.append(count)
        count += 3 if p["phase"] == "outcome" else 1
    iti = first[-1]

    def after(i: int) -> int:
        return first[i + 1] if i + 1 < len(phases) else 0

    states: list[list[int]] = []
    edges: list[tuple[int, int, int]] = []

    def state(outputs_mask: int = 0, watch: int = 0, timer: str | None = None, on_timeout: int = NONE,
              exits: Sequence[tuple[int, int, int]] = (), chance: int = NONE, on_hit: int = NONE,
              on_miss: int = NONE, outcome: int = 0) -> None:
        t = slot[timer] if timer is not None else NONE
        edge_first = len(edges) if exits else 0
        edges.extend(exits)
        states.append([outputs_mask, watch, t, t, on_timeout if timer is not None else NONE,
                       chance, on_hit, on_miss, edge_first, len(exits), 0, outcome])

    for i, p in enumerate(phases):
        kind, mask, nxt = p["phase"], output_mask(i, p.get("outputs")), after(i)
        if kind == "wait":
            bit = input_bit(i, p.get("on"))
            state(mask, 1 << bit, timers[i], iti, exits=[(bit, RISE, nxt)])
        elif kind == "present":
            exits, watch = [], 0
            if p.get("abortOnRelease") is not None:
                bit = input_bit(i, p["abortOnRelease"])
                watch |= 1 << bit
                exits.append((bit, FALL, iti))
            state(mask, watch, timers[i], nxt, exits=exits)
        elif kind == "delay":
            state(mask, 0, timers[i], nxt)
        elif kind == "outcome":
            line = output_mask(i, [p.get("line")])
            reward, settle = first[i] + 1, first[i] + 2
            state(chance=slot[REWARD_PERMILLE_KEY], on_hit=reward, on_miss=settle, outcome=OUTCOME_CORRECT)
            # The reward line opens BESIDE the phase's own outputs: a phase's
            # outputs are HIGH for the whole phase, the reward included.
            state(mask | line, 0, REWARD_MS_KEY, settle)
            state(mask, 0, timers[i], nxt)
        else:  # iti
            state(mask, 0, timers[i], 0)

    if len(states) >= NONE or len(edges) >= NONE:
        raise LoweringError(f"the table has {len(states)} states and {len(edges)} edge rows; "
                            f"each is at most {NONE - 1}")
    states[0][_FLAGS] |= STARTS_TRIAL
    return Lowered(
        states=tuple(tuple(s) for s in states),
        edges=tuple(edges),
        params=tuple(params),
        timers=tuple(timers),
        phases=tuple(i for i, p in enumerate(phases) for _ in range(3 if p["phase"] == "outcome" else 1)),
    )
