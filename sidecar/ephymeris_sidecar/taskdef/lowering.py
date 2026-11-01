"""A spine of phases -> BoxInterp.h's state table (`0003-phase-spine-task-model.md#interpreter-and-firmware`).

The generator's half of "a task is a phase spine, lowered to a state table".
`lower()` writes each phase as states exactly as `TASKS.md#lowering` and
BoxInterp.h's "Lowering the first phases" describe, and returns the table as
plain tuples in `InterpStateRow` / `InterpEdgeRow` field order, so the same
rows become the C initialisers in `TaskSpine.h` and the `replay.Table`
analytics replays.

**Pure and standard-library only**, like `analytics/stream/replay.py`: the
differential test (`extras/host_test/differential.py`) loads this file by
path and runs the tables it emits through both interpreters. Keep it free of
any import, relative ones included.

THE INPUT HAS ALREADY BEEN JUDGED. `taskdef/spine.py` validates a definition
and reports what is wrong with it; this refuses (`LoweringError`) only what it
cannot write at all, so a half-finished task still previews.

WHAT A TABLE IS INDEPENDENT OF. Pins never enter it: channels are bits, input
bit i is the i-th distinct channel bound to a `digital_in` slot, by slot and
then by row (`channel_bits`), and outputs the same. Durations and
probabilities never enter it either: each is a parameter slot the host sets by
`SET` line. So one table serves every tuning and every pin map.

ROWS. Each row gets its own copy of the spine, ITI included, because its
bindings, and so its bits, differ. With two or more rows, state 0 is a pick
state whose branches are the rows' first states, in `rows` order; with one,
the row's first state is state 0.

PARAMETER SLOTS, in order (`ParamSlot`):
    0       NT        the block's trial count, read by the session layer (BoxSpine.h)
    1..     T<i>      the timer of phase i, one per timed phase, in phase order;
            H<i>      a Response window's hold, straight after its T<i>
    then, per row r from 1:
            RW<r>     the row's reward ms, when the row can pay
            RP<r>     its reward probability in permille, for an Outcome with no
                      window before it
            RP<r>_<k> the probability of map entry k, numbered from 1 in branch
                      order (the window's responses, then the timeout), for each
                      entry with a line
            then, per DRIVEN output slot s (numbered from 1 among the output
            slots), the row's values for it:
            PD<r>_<s>  a PWM duty, 0-255
            TF<r>_<s>  a tone's frequency in Hz
            TH<r>_<s>, TW<r>_<s>, TL<r>_<s>
                       a pulse train's rate in Hz, pulse width and length in ms,
                       in three consecutive slots

DRIVEN OUTPUTS (`TASKS.md#driven-outputs`). An output slot the definition
drives as `pwm`, `tone` or `train` gets one bit PER ROW rather than per
channel, since each row drives it at its own values: `Lowered.drives` names
each such bit's kind and its first parameter slot, which the hardware layer
reads when the core drives the bit HIGH. To the core it is a bit like any other.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

#: The table format these tables are written in: BoxInterp.h's `INTERP_VERSION`,
#: which the spine runner announces as `INTERP=<n>`. A run's snapshot records
#: it beside the table, and replay refuses one it does not know. 1 is the trial
#: runner's, in the same numbering space (`analytics/stream/replay.py`).
INTERP_VERSION = 4

#: BoxInterp.h's constants (`INTERP_NONE`, `INTERP_RISE`, ...), mirrored.
NONE = 0xFF
RISE = 1
FALL = 2
STARTS_TRIAL = 0x01
PICK = 0x02

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
OUTCOME_HOLD_BROKEN = OUTCOME_CLASSES.index("hold_broken") + 1

#: Where `flags` sits in a state row (`Lowered.states`).
_FLAGS = 10

#: The phases lowered so far. Hold and Counter are #102.
PHASES = ("wait", "present", "delay", "response", "outcome", "iti")
_TIMED = ("present", "delay", "response", "outcome", "iti")

#: The contingency map's key for the window running out; no slot may be called it.
TIMEOUT = "timeout"

TRIALS_KEY = "NT"

#: Inputs and outputs are each bits of a uint32_t (BoxInterp.h).
CHANNELS = 32

#: Each drive kind's parameters, in slot order: (role, wire key prefix).
DRIVE_PARAMS: dict[str, tuple[tuple[str, str], ...]] = {
    "pwm": (("pwm_duty", "PD"),),
    "tone": (("tone_hz", "TF"),),
    "train": (("train_hz", "TH"), ("train_width", "TW"), ("train_ms", "TL")),
}

#: The bytes one `InterpStateRow` and one `InterpEdgeRow` take on the board
#: (AVR packs them: two uint32_t and ten uint8_t; three uint8_t). The table sits
#: in RAM, so its size is checked at save (`TASKS.md#spine-diagnostics`).
#: `test_spine_task.py` pins both against BoxInterp.h.
STATE_ROW_BYTES = 18
EDGE_ROW_BYTES = 3


def table_bytes(states: int, edges: int) -> int:
    """The RAM a table of `states` states and `edges` edge rows takes on the board."""
    return states * STATE_ROW_BYTES + edges * EDGE_ROW_BYTES


class LoweringError(ValueError):
    """The spine cannot be written as a table at all."""


@dataclass(frozen=True)
class ParamSlot:
    """What one parameter slot is, so the profile can declare a field for it.

    `role` is `trials`, `timer`, `hold`, `reward_ms`, `reward_permille`, or
    a driven output's value (`DRIVE_PARAMS`). `phase` is the phase a timer or
    hold belongs to; `row` the row index a reward or a drive value belongs to;
    `entry` the map key (a slot, or `timeout`) of a window entry's
    probability, None for an Outcome with no window before it; `slot` the
    driven output slot a drive value is for.
    """

    key: str
    role: str
    phase: int | None = None
    row: int | None = None
    entry: str | None = None
    slot: str | None = None


@dataclass(frozen=True)
class Lowered:
    """One spine's table, in BoxInterp.h's field order.

    `states[i]` is (outputs, watch, timer_min, timer_max, on_timeout, chance,
    on_hit, on_miss, edge_first, edge_count, flags, outcome); `edges[k]` is
    (input, edge, next); `params[s]` is the wire key of parameter slot s, and
    `slots[s]` what it is. `inputs[i]` and `outputs[j]` are the (slot, channel)
    each bit is. `phases[s]` and `rows[s]` are the phase index and the row index
    state s belongs to, None for the pick state, which belongs to neither.
    `drives` is (output bit, kind, first parameter slot) for every driven
    output bit, in bit order.
    """

    states: tuple[tuple[int, ...], ...]
    edges: tuple[tuple[int, int, int], ...]
    params: tuple[str, ...]
    slots: tuple[ParamSlot, ...]
    phases: tuple[int | None, ...]
    rows: tuple[int | None, ...]
    inputs: tuple[tuple[str, str], ...]
    outputs: tuple[tuple[str, str], ...]
    drives: tuple[tuple[int, str, int], ...] = ()


def timer_key(phase_index: int) -> str:
    return f"T{phase_index}"


def hold_key(phase_index: int) -> str:
    return f"H{phase_index}"


def reward_ms_key(row_index: int) -> str:
    return f"RW{row_index + 1}"


def reward_permille_key(row_index: int, entry: int | None = None) -> str:
    """`RP<r>`, or `RP<r>_<k>` for map entry k (from 1, in branch order)."""
    return f"RP{row_index + 1}" if entry is None else f"RP{row_index + 1}_{entry}"


def drive_keys(row_index: int, slot_number: int, kind: str) -> tuple[str, ...]:
    """The wire keys of a row's values for driven output slot number `slot_number` (from 1)."""
    return tuple(f"{prefix}{row_index + 1}_{slot_number}" for _, prefix in DRIVE_PARAMS[kind])


def channel_bits(
    slots: Sequence[str], rows: Sequence[dict[str, Any]], per_row: Any = ()
) -> tuple[tuple[tuple[str, str], ...], tuple[dict[str, int], ...]]:
    """Bit i is the i-th distinct channel bound to one of `slots`, by slot and then by row.

    Returns each bit's (slot, channel) and, per row, each slot's bit. A slot a
    row leaves unbound gets a bit of its own, with channel "", so a half-built
    task still lowers. A slot in `per_row` (a driven output) gets a bit of its
    own in every row, whatever it binds.
    """
    bit_of: dict[Any, int] = {}
    entries: list[tuple[str, str]] = []
    bits: list[dict[str, int]] = [{} for _ in rows]
    for slot in slots:
        for r, row in enumerate(rows):
            channel = (row.get("bind") or {}).get(slot) or ""
            key: Any = (slot, r) if slot in per_row or not channel else channel
            if key not in bit_of:
                bit_of[key] = len(entries)
                entries.append((slot, channel))
            bits[r][slot] = bit_of[key]
    return tuple(entries), tuple(bits)


def _entries(phase: dict[str, Any]) -> list[str]:
    """A window's map keys in branch order: its responses, then the timeout."""
    return [*phase.get("responses", []), TIMEOUT]


class _Ref:
    """A state index not known yet when a row pointing at it is written."""

    at: int | None = None


def lower(
    phases: Sequence[dict[str, Any]],
    inputs: Sequence[str],
    outputs: Sequence[str],
    rows: Sequence[dict[str, Any]] | None = None,
    drives: dict[str, str] | None = None,
) -> Lowered:
    """The state table for `phases` over `rows`.

    `inputs` and `outputs` are the slot ids of each direction, in slot order.
    Each row is `{bind: {slot: channel}, map: {key: entry}}` in the definition's
    JSON form. Without `rows`, one row binds each slot to a channel of its own
    name. `drives` maps each driven output slot to its kind (`DRIVE_PARAMS`).
    """
    drives = dict(drives or {})
    for slot, kind in drives.items():
        if slot not in outputs or kind not in DRIVE_PARAMS:
            raise LoweringError(f"{slot!r} driven as {kind!r}: a driven slot is an output slot, "
                                f"driven as one of {tuple(DRIVE_PARAMS)}")
    if rows is None:
        rows = [{"bind": {s: s for s in (*inputs, *outputs)}}]
    if not rows:
        raise LoweringError("a spine task needs at least one row")
    if not phases:
        raise LoweringError("a spine needs at least one phase")
    kinds = [p.get("phase") for p in phases]
    for i, kind in enumerate(kinds):
        if kind not in PHASES:
            raise LoweringError(f"phase {i}: {kind!r} is not one of {PHASES}")
    if kinds.count("iti") != 1 or kinds[-1] != "iti" or len(phases) < 2:
        raise LoweringError("a spine ends in exactly one ITI, after at least one other phase")
    iti = len(phases) - 1
    windows = [i for i, kind in enumerate(kinds) if kind == "response"]
    if len(windows) > 1:
        raise LoweringError("a spine has at most one Response window")
    w = windows[0] if windows else None
    if w is not None and kinds[w + 1 : iti].count("outcome") != 1:
        raise LoweringError("a Response window is followed by exactly one Outcome")
    if len(rows) > 1 and kinds[0] == "outcome":
        raise LoweringError("with several rows the first phase is not an Outcome: a pick branch never draws again")

    in_bits, row_in = channel_bits(inputs, rows)
    out_bits, row_out = channel_bits(outputs, rows, per_row=drives)
    for what, bits in (("input", in_bits), ("output", out_bits)):
        if len(bits) > CHANNELS:
            raise LoweringError(f"the rows bind {len(bits)} {what} bits, and a table speaks of at most "
                                f"{CHANNELS}: a driven slot takes a bit in every row")

    def input_bit(r: int, i: int, slot: Any) -> int:
        if slot not in row_in[r]:
            raise LoweringError(f"phase {i}: {slot!r} is not an input slot")
        return row_in[r][slot]

    def output_mask(r: int, i: int, slots: Any) -> int:
        mask = 0
        for slot in slots or ():
            if slot not in row_out[r]:
                raise LoweringError(f"phase {i}: {slot!r} is not an output slot")
            mask |= 1 << row_out[r][slot]
        return mask

    # Each row's map, checked as far as writing it needs.
    maps: list[dict[str, dict[str, Any]]] = []
    for r, row in enumerate(rows):
        rmap = row.get("map") or {}
        if w is not None:
            window = phases[w]
            responses = list(window.get("responses") or [])
            if not responses or len(set(responses)) != len(responses):
                raise LoweringError(f"phase {w}: a window watches one or more distinct input slots")
            for key in _entries(window):
                entry = rmap.get(key)
                if not isinstance(entry, dict):
                    raise LoweringError(f"row {r}: the map has no entry for {key!r}")
                if entry.get("outcome") not in OUTCOME_CLASSES:
                    raise LoweringError(f"row {r}: {entry.get('outcome')!r} is not an outcome class")
                if entry.get("line") is not None:
                    output_mask(r, w, [entry["line"]])
                if entry.get("hold") and (key == TIMEOUT or window.get("holdMs") is None):
                    raise LoweringError(f"row {r}: entry {key!r} holds, which needs a response and the window's holdMs")
        maps.append(rmap)

    # Parameter slots: NT, the timers (and the window's hold), then each row's rewards.
    slots: list[ParamSlot] = [ParamSlot(TRIALS_KEY, "trials")]
    for i, p in enumerate(phases):
        if p["phase"] in _TIMED or (p["phase"] == "wait" and p.get("timeoutMs") is not None):
            slots.append(ParamSlot(timer_key(i), "timer", phase=i))
        if p["phase"] == "response" and p.get("holdMs") is not None:
            slots.append(ParamSlot(hold_key(i), "hold", phase=i))
    plain_outcome = any(kind == "outcome" and (w is None or i < w) for i, kind in enumerate(kinds))
    for r in range(len(rows)):
        lines = ([(k, key) for k, key in enumerate(_entries(phases[w]), 1) if maps[r][key].get("line")]
                 if w is not None else [])
        if plain_outcome or lines:
            slots.append(ParamSlot(reward_ms_key(r), "reward_ms", row=r))
        if plain_outcome:
            slots.append(ParamSlot(reward_permille_key(r), "reward_permille", row=r))
        for k, key in lines:
            slots.append(ParamSlot(reward_permille_key(r, k), "reward_permille", row=r, entry=key))
        for number, out_slot in enumerate(outputs, 1):
            if out_slot in drives:
                kind = drives[out_slot]
                slots += [ParamSlot(key, role, row=r, slot=out_slot)
                          for key, (role, _) in zip(drive_keys(r, number, kind), DRIVE_PARAMS[kind])]
    slot = {s.key: n for n, s in enumerate(slots)}
    number_of = {s: n for n, s in enumerate(outputs, 1)}
    drive_bits = tuple(sorted(
        (row_out[r][s], kind, slot[drive_keys(r, number_of[s], kind)[0]])
        for r in range(len(rows)) for s, kind in drives.items()
    ))

    states: list[list[Any]] = []
    edges: list[list[Any]] = []
    phase_of: list[int | None] = []
    row_of: list[int | None] = []

    def state(phase: int | None, row: int | None, outputs_mask: int = 0, watch: int = 0,
              timer: str | None = None, on_timeout: Any = NONE, exits: Sequence[tuple[int, int, Any]] = (),
              chance: str | None = None, on_hit: Any = NONE, on_miss: Any = NONE, flags: int = 0,
              outcome: int = 0) -> int:
        t = slot[timer] if timer is not None else NONE
        edge_first = len(edges) if exits else 0
        edges.extend([list(e) for e in exits])
        states.append([outputs_mask, watch, t, t, on_timeout if timer is not None else NONE,
                       slot[chance] if chance is not None else NONE, on_hit, on_miss,
                       edge_first, len(exits), flags, outcome])
        phase_of.append(phase)
        row_of.append(row)
        return len(states) - 1

    def outcome_states(r: int, i: int, mask: int, nxt: Any, cls: int, line: str | None,
                       chance: str | None) -> None:
        """An Outcome: with a line, a chance state marked with the class, the
        reward, then the class timeout; without one, the class timeout alone,
        marked. The phase's own outputs stay HIGH through all of it."""
        if line is None:
            state(i, r, mask, 0, timer_key(i), nxt, outcome=cls)
            return
        at = len(states)
        state(i, r, chance=chance, on_hit=at + 1, on_miss=at + 2, outcome=cls)
        state(i, r, mask | output_mask(r, i, [line]), 0, reward_ms_key(r), at + 2)
        state(i, r, mask, 0, timer_key(i), nxt)

    def run(r: int, indices: Sequence[int], end: Any, iti_ref: _Ref,
            branch: tuple[int, str | None, int | None] | None = None) -> None:
        """Phases `indices` in order, the last going on to `end`. `branch` is
        the (class, line, entry) of the map entry these phases follow."""
        for n, i in enumerate(indices):
            nxt: Any = end
            if n + 1 < len(indices):
                nxt = _Ref()
            p = phases[i]
            kind, mask = p["phase"], output_mask(r, i, p.get("outputs"))
            if kind == "wait":
                bit = input_bit(r, i, p.get("on"))
                timer = timer_key(i) if p.get("timeoutMs") is not None else None
                state(i, r, mask, 1 << bit, timer, iti_ref, exits=[(bit, RISE, nxt)])
            elif kind == "present":
                exits, watch = [], 0
                if p.get("abortOnRelease") is not None:
                    bit = input_bit(r, i, p["abortOnRelease"])
                    watch |= 1 << bit
                    exits.append((bit, FALL, iti_ref))
                state(i, r, mask, watch, timer_key(i), nxt, exits=exits)
            elif kind == "delay":
                state(i, r, mask, 0, timer_key(i), nxt)
            elif kind == "outcome":
                if branch is None:
                    outcome_states(r, i, mask, nxt, OUTCOME_CORRECT, p.get("line"), reward_permille_key(r))
                else:
                    cls, line, k = branch
                    outcome_states(r, i, mask, nxt, cls, line,
                                   reward_permille_key(r, k) if line is not None else None)
            if isinstance(nxt, _Ref):
                nxt.at = len(states)

    row_first: list[_Ref] = []

    def emit_row(r: int) -> None:
        first, iti_ref = _Ref(), _Ref()
        first.at = len(states)
        row_first.append(first)
        if w is None:
            run(r, range(iti), iti_ref, iti_ref)
        else:
            window_ref = _Ref()
            run(r, range(w), window_ref, iti_ref)
            window_ref.at = len(states)
            window = phases[w]
            rmap = maps[r]
            keys = _entries(window)
            branch_ref = {key: _Ref() for key in keys}
            broken = _Ref()
            win_mask = output_mask(r, w, window.get("outputs"))
            responses = keys[:-1]
            bits = [input_bit(r, w, slot) for slot in responses]
            if len(set(bits)) != len(bits):
                raise LoweringError(f"row {r}: two of the window's responses are one channel")
            state(w, r, win_mask, sum(1 << b for b in bits), timer_key(w), branch_ref[TIMEOUT],
                  exits=[(b, RISE, branch_ref[slot]) for b, slot in zip(bits, responses)])
            post = range(w + 1, iti)
            for k, key in enumerate(keys, 1):
                branch_ref[key].at = len(states)
                entry = rmap[key]
                if entry.get("hold"):
                    bit = input_bit(r, w, key)
                    state(w, r, win_mask, 1 << bit, hold_key(w), len(states) + 1, exits=[(bit, FALL, broken)])
                cls = OUTCOME_CLASSES.index(entry["outcome"]) + 1
                run(r, post, iti_ref, iti_ref, branch=(cls, entry.get("line"), k))
            if any(rmap[key].get("hold") for key in keys):
                broken.at = len(states)
                run(r, post, iti_ref, iti_ref, branch=(OUTCOME_HOLD_BROKEN, None, None))
        iti_ref.at = len(states)
        state(iti, r, output_mask(r, iti, phases[iti].get("outputs")), 0, timer_key(iti), 0)

    if len(rows) > 1:
        refs = [_Ref() for _ in rows]
        state(None, None, exits=[(0, 0, ref) for ref in refs], flags=STARTS_TRIAL | PICK)
        for r in range(len(rows)):
            emit_row(r)
            refs[r].at = row_first[r].at
    else:
        emit_row(0)
        states[0][_FLAGS] |= STARTS_TRIAL

    if len(states) >= NONE or len(edges) >= NONE:
        raise LoweringError(f"the table has {len(states)} states and {len(edges)} edge rows; "
                            f"each is at most {NONE - 1}")

    def resolve(value: Any) -> int:
        return value.at if isinstance(value, _Ref) else value

    return Lowered(
        states=tuple(tuple(resolve(v) for v in s) for s in states),
        edges=tuple((e[0], e[1], resolve(e[2])) for e in edges),
        params=tuple(s.key for s in slots),
        slots=tuple(slots),
        phases=tuple(phase_of),
        rows=tuple(row_of),
        inputs=in_bits,
        outputs=out_bits,
        drives=drive_bits,
    )
