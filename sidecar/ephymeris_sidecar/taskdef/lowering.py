"""A spine of phases -> BoxInterp.h's state table (`0003-phase-spine-task-model.md#interpreter-and-firmware`).

The generator's half of "a task is a phase spine, lowered to a state table".
`lower()` writes each phase as states exactly as `TASKS.md#lowering` and
BoxInterp.h's "Lowering the phases" describe, and returns the table as
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

ROWS AND BLOCKS. Each row gets its own copy of the spine, ITI included,
because its bindings, and so its bits, differ. With two or more rows, state 0
is a pick state whose branches are each block's rows' first states, block by
block; with one, the row's first state is state 0. Each block is an
`InterpBlock` naming its slice of those branches (`TASKS.md#blocks`).

ENDS. Every exit that ends a trial early (an abort, a released Hold, a Wait's
timeout, a Counter's time limit) goes to an END: a copy of the ITI state that
also carries the exit's outcome class. One end per (class, ITI outputs,
last-trial flag) serves every row, after all the rows' states. Past the
Outcome the trial is already marked: an early exit there goes to the row's own
ITI, or to an unmarked end when a Counter's limit ends the session.

PARAMETER SLOTS, in order (`ParamSlot`):
            NT        the session's trial cap, read by the session layer (BoxSpine.h),
                      only with `session_cap`
            T<i>      the timer of phase i, one per timed phase, in phase order;
            H<i>      a Response window's hold, straight after its T<i>;
            N<i>      a Counter's N (or the low end of a drawn N), straight after
                      its T<i>, unless it reads a compiled sequence (`ratios`);
            NX<i>     the high end of a drawn N
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
    then, per block b from 1:
            BN<b>, BNX<b>   its N, and a drawn N's high end
            BK<b>, BKN<b>   its criterion's k and n
            BC<b>     its correction limit
            BA<b>     an anti-bias block's window
            W<b>_<e>  the weight of its e-th row, for a selection that reads weights
            B<b>T<i>  phase i's duration while it runs

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
INTERP_VERSION = 6

#: BoxInterp.h's constants (`INTERP_NONE`, `INTERP_RISE`, ...), mirrored.
NONE = 0xFF
RISE = 1
FALL = 2
STARTS_TRIAL = 0x01
PICK = 0x02
COUNT = 0x04
LAST_TRIAL = 0x08
RESPONSE = 0x10

#: A block's selection, by its `select` name: `InterpBlock.select`.
SELECTIONS = {"uniform": 0, "weighted": 1, "bag": 2, "antibias": 3}
#: The selections that read each row's weight.
WEIGHTED = ("weighted", "bag", "antibias")
#: How many trials a criterion can look back on, how many responses anti-bias
#: can, and how many tokens a bag holds: BoxInterp.h's `INTERP_HISTORY`.
HISTORY = 32

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
OUTCOME_OMISSION = OUTCOME_CLASSES.index("omission") + 1
OUTCOME_ABORT_BEFORE = OUTCOME_CLASSES.index("abort_before_stimulus") + 1
OUTCOME_ABORT_DURING = OUTCOME_CLASSES.index("abort_during_sampling") + 1

#: The classes a block's correction repeats after unless the block names its
#: own (`correctionAfter`): the animal answered, wrongly. A correct withhold, an
#: omission and an abort are not errors.
ERROR_CLASSES = ("wrong_response", "false_alarm")
#: The aborts: classes a trial is excluded in, neither right nor wrong. The one
#: list of them: `analytics/stream/trial_table.py`'s `EXCLUDED` (P(correct))
#: reads it, and so does a block's criterion, whose "k correct of the last n"
#: passes over these trials (`InterpBlocks.skipped`). They still count toward N.
EXCLUDED_CLASSES = ("abort_before_stimulus", "abort_during_sampling")


def class_mask(names) -> int:  # noqa: ANN001
    """The bitmask of outcome classes `names`: bit c-1 for class number c."""
    return sum(1 << OUTCOME_CLASSES.index(name) for name in set(names))

#: Where `flags` sits in a state row (`Lowered.states`).
_FLAGS = 10

#: The phase palette (0003-phase-spine-task-model.md#phase-palette).
PHASES = ("wait", "hold", "present", "delay", "response", "counter", "outcome", "iti")
_TIMED = ("hold", "present", "delay", "response", "outcome", "iti")
#: An input edge, by the name of the channel code it strobes.
EDGES = {"enter": RISE, "exit": FALL}

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
#: `InterpBlock`, `InterpEntry` and `InterpOverride`, likewise pinned.
BLOCK_BYTES = 12
ENTRY_BYTES = 2
OVERRIDE_BYTES = 3


def table_bytes(states: int, edges: int, blocks: int = 0, entries: int = 0, overrides: int = 0) -> int:
    """The RAM a table of `states` states and `edges` edge rows, and its blocks,
    entries and overrides, takes on the board."""
    return (states * STATE_ROW_BYTES + edges * EDGE_ROW_BYTES + blocks * BLOCK_BYTES
            + entries * ENTRY_BYTES + overrides * OVERRIDE_BYTES)


class LoweringError(ValueError):
    """The spine cannot be written as a table at all."""


@dataclass(frozen=True)
class ParamSlot:
    """What one parameter slot is, so the profile can declare a field for it.

    `role` is `trials`, `timer`, `hold`, `count`, `count_max`, `reward_ms`,
    `reward_permille`, a driven output's value (`DRIVE_PARAMS`), or one of a
    block's: `block_trials`, `block_trials_max`, `criterion_correct`,
    `criterion_of`, `correction`, `bias_window`, `weight` and `block_timer`.
    `phase` is the phase a timer, hold or count belongs to (or a block's
    override is of); `row` the row index a reward, a drive value or a weight
    belongs to; `entry` the map key (a slot, or `timeout`) of a window entry's
    probability, None for an Outcome with no window before it; `slot` the
    driven output slot a drive value is for; `block` the block index a block's
    slot belongs to.
    """

    key: str
    role: str
    phase: int | None = None
    row: int | None = None
    entry: str | None = None
    slot: str | None = None
    block: int | None = None


@dataclass(frozen=True)
class Lowered:
    """One spine's table, in BoxInterp.h's field order.

    `states[i]` is (outputs, watch, timer_min, timer_max, on_timeout, chance,
    on_hit, on_miss, edge_first, edge_count, flags, outcome); `edges[k]` is
    (input, edge, next); `params[s]` is the wire key of parameter slot s, and
    `slots[s]` what it is. `inputs[i]` and `outputs[j]` are the (slot, channel)
    each bit is. `phases[s]` and `rows[s]` are the phase index and the row index
    state s belongs to: no phase for the pick state, and no row for it or for an
    end, which every row shares. `counter` is BoxInterp.h's `InterpCounter` as
    (count_min, count_max, ratios), None for a spine with no Counter. `drives` is
    (output bit, kind, first parameter slot) for every driven output bit, in bit
    order. `blocks[b]` is an `InterpBlock` (first, count, select, n_min, n_max,
    k, n, window, correct, next, errors); `entries` one (side, weight) per
    branch of the pick, empty when no block selects by weight or side;
    `overrides` each (block, slot, with); `skipped` the classes a criterion
    passes over, as a bitmask (`InterpBlocks.skipped`).
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
    counter: tuple[int, int, tuple[int, ...]] | None = None
    blocks: tuple[tuple[int, ...], ...] = ()
    entries: tuple[tuple[int, int], ...] = ()
    overrides: tuple[tuple[int, int, int], ...] = ()
    skipped: int = 0


def block_key(kind: str, block_index: int, extra: str = "") -> str:
    """A block's wire key: `BN<b>`, `BNX<b>`, `BK<b>`, `BKN<b>`, `BC<b>`, `BA<b>`,
    `W<b>_<e>` or `B<b>T<i>`, b from 1."""
    b = block_index + 1
    return f"W{b}_{extra}" if kind == "W" else f"B{b}T{extra}" if kind == "T" else f"{kind}{b}"


def timer_key(phase_index: int) -> str:
    return f"T{phase_index}"


def hold_key(phase_index: int) -> str:
    return f"H{phase_index}"


def count_key(phase_index: int) -> str:
    return f"N{phase_index}"


def count_max_key(phase_index: int) -> str:
    return f"NX{phase_index}"


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
    blocks: Sequence[dict[str, Any]] | None = None,
    session_cap: bool = False,
) -> Lowered:
    """The state table for `phases` over `rows`, drawn by `blocks`.

    `inputs` and `outputs` are the slot ids of each direction, in slot order.
    Each row is `{id, bind: {slot: channel}, map: {key: entry}}` and each block
    `{rows: [row id], select, trials, trialsMax, criterion, next, correction,
    correctionAfter, phaseMs}` in the definition's JSON form. Without `rows`,
    one row binds each slot to a channel of its own name; without `blocks`, one
    block draws every row uniformly and never ends. `drives` maps each driven
    output slot to its kind (`DRIVE_PARAMS`). `session_cap` gives the session's
    trial cap its slot, `NT`.
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
    row_index = {str(row.get("id", r)): r for r, row in enumerate(rows)}
    if blocks is None:
        blocks = [{"rows": list(row_index)}]
    if not blocks or len(blocks) >= NONE:
        raise LoweringError(f"a spine task has 1 to {NONE - 1} blocks")
    block_index = {str(b.get("id", i)): i for i, b in enumerate(blocks)}
    block_rows: list[list[int]] = []
    for i, b in enumerate(blocks):
        drawn = [row_index.get(str(r)) for r in b.get("rows") or []]
        if not drawn or None in drawn:
            raise LoweringError(f"block {i} draws one or more of the task's rows, by id")
        if b.get("select", "uniform") not in SELECTIONS:
            raise LoweringError(f"block {i}: a selection is one of {tuple(SELECTIONS)}")
        if b.get("next") is not None and str(b["next"]) not in block_index:
            raise LoweringError(f"block {i}: its next is not a block")
        if b.get("trialsMax") is not None and b.get("trials") is None:
            raise LoweringError(f"block {i}: trialsMax draws N from trials up to it")
        if any(name not in OUTCOME_CLASSES for name in b.get("correctionAfter") or ()):
            raise LoweringError(f"block {i}: correctionAfter names outcome classes {OUTCOME_CLASSES}")
        block_rows.append(drawn)
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
    counters = [i for i, kind in enumerate(kinds) if kind == "counter"]
    if len(counters) > 1:
        raise LoweringError("a spine has at most one Counter: the table holds one N")
    counter_phase = phases[counters[0]] if counters else None
    if counter_phase is not None and bool(counter_phase.get("ratios")) == (counter_phase.get("count") is not None):
        raise LoweringError(f"phase {counters[0]}: a Counter takes either a count or ratios")
    # Where an early exit's class changes: the first Present is the stimulus.
    stimulus = next((i for i, kind in enumerate(kinds) if kind == "present"), len(kinds))
    # Where a trial is decided: past its Outcome an early exit marks nothing, so a
    # trial carries one class, the Outcome's.
    decided = next((i for i, kind in enumerate(kinds) if kind == "outcome"), len(kinds))

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

    # Parameter slots: NT, the timers (and the window's hold), each row's
    # rewards, then each block's.
    slots: list[ParamSlot] = [ParamSlot(TRIALS_KEY, "trials")] if session_cap else []
    for i, p in enumerate(phases):
        if p["phase"] in _TIMED or (p["phase"] == "wait" and p.get("timeoutMs") is not None):
            slots.append(ParamSlot(timer_key(i), "timer", phase=i))
        if p["phase"] == "counter" and p.get("timeoutMs") is not None:
            slots.append(ParamSlot(timer_key(i), "timer", phase=i))
        if p["phase"] == "response" and p.get("holdMs") is not None:
            slots.append(ParamSlot(hold_key(i), "hold", phase=i))
        if p["phase"] == "counter" and p.get("count") is not None:
            slots.append(ParamSlot(count_key(i), "count", phase=i))
            if p.get("countMax") is not None:
                slots.append(ParamSlot(count_max_key(i), "count_max", phase=i))
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
    timed = {s.phase for s in slots if s.role == "timer"}
    for b, spec in enumerate(blocks):
        if spec.get("trials") is not None:
            slots.append(ParamSlot(block_key("BN", b), "block_trials", block=b))
            if spec.get("trialsMax") is not None:
                slots.append(ParamSlot(block_key("BNX", b), "block_trials_max", block=b))
        if spec.get("criterion") is not None:
            slots.append(ParamSlot(block_key("BK", b), "criterion_correct", block=b))
            slots.append(ParamSlot(block_key("BKN", b), "criterion_of", block=b))
        if spec.get("correction") is not None:
            slots.append(ParamSlot(block_key("BC", b), "correction", block=b))
        select = spec.get("select", "uniform")
        if select == "antibias":
            slots.append(ParamSlot(block_key("BA", b), "bias_window", block=b))
        if select in WEIGHTED:
            for e, r in enumerate(block_rows[b], 1):
                slots.append(ParamSlot(block_key("W", b, str(e)), "weight", row=r, block=b))
        for phase in sorted(int(i) for i in (spec.get("phaseMs") or {})):
            if phase not in timed:
                raise LoweringError(f"block {b}: phase {phase} has no duration to override")
            slots.append(ParamSlot(block_key("T", b, str(phase)), "block_timer", phase=phase, block=b))
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

    ends: dict[tuple[int, int, int], _Ref] = {}

    def early(r: int, i: int, cls: int, iti_ref: _Ref, flags: int = 0) -> _Ref:
        """Where an early exit of row r from phase i goes: an end, its ITI marked
        with `cls`. Past the Outcome the trial is already marked, so it goes to
        the row's own ITI, or to an unmarked end when it ends the session."""
        if i > decided:
            if not flags:
                return iti_ref
            cls = 0
        key = (cls, output_mask(r, iti, phases[iti].get("outputs")), flags)
        return ends.setdefault(key, _Ref())

    def aborts(r: int, i: int, p: dict[str, Any], iti_ref: _Ref) -> tuple[int, list[tuple[int, int, Any]]]:
        """A Present's or a Delay's abort exits, as (watch, edge rows)."""
        cls = OUTCOME_ABORT_BEFORE if i < stimulus else OUTCOME_ABORT_DURING
        watch, exits = 0, []
        for key, edge in (("abortOnRelease", FALL), ("abortOnEnter", RISE)):
            if p.get(key) is not None:
                bit = input_bit(r, i, p[key])
                watch |= 1 << bit
                exits.append((bit, edge, early(r, i, cls, iti_ref)))
        return watch, exits

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
                edge = EDGES.get(p.get("edge") or "enter")
                if edge is None:
                    raise LoweringError(f"phase {i}: a wait's edge is one of {tuple(EDGES)}")
                timer = timer_key(i) if p.get("timeoutMs") is not None else None
                # Before the stimulus no trial was offered; from it on, the animal was asked.
                missed = (early(r, i, OUTCOME_ABORT_BEFORE if i < stimulus else OUTCOME_OMISSION, iti_ref)
                          if timer else NONE)
                state(i, r, mask, 1 << bit, timer, missed, exits=[(bit, edge, nxt)])
            elif kind == "hold":
                bit = input_bit(r, i, p.get("on"))
                state(i, r, mask, 1 << bit, timer_key(i), nxt,
                      exits=[(bit, FALL, early(r, i, OUTCOME_HOLD_BROKEN, iti_ref))])
            elif kind in ("present", "delay"):
                watch, exits = aborts(r, i, p, iti_ref)
                state(i, r, mask, watch, timer_key(i), nxt, exits=exits)
            elif kind == "counter":
                bit = input_bit(r, i, p.get("on"))
                timer = timer_key(i) if p.get("timeoutMs") is not None else None
                limit = (early(r, i, OUTCOME_OMISSION, iti_ref, LAST_TRIAL if p.get("endsSession") else 0)
                         if timer else NONE)
                state(i, r, mask, 1 << bit, timer, limit, exits=[(bit, RISE, nxt)], flags=COUNT)
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
                  exits=[(b, RISE, branch_ref[slot]) for b, slot in zip(bits, responses)], flags=RESPONSE)
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

    branches = [r for drawn in block_rows for r in drawn]
    if len(rows) > 1:
        # The pick's branches are the blocks' rows, block by block: a block
        # draws its own slice of them (InterpBlock.first, .count).
        state(None, None, exits=[(0, 0, _Ref()) for _ in branches], flags=STARTS_TRIAL | PICK)
        for r in range(len(rows)):
            emit_row(r)
        for e, r in enumerate(branches):
            edges[e][2].at = row_first[r].at
    else:
        emit_row(0)
        states[0][_FLAGS] |= STARTS_TRIAL
    for (cls, mask, flags), ref in ends.items():
        ref.at = len(states)
        state(iti, None, mask, 0, timer_key(iti), 0, flags=flags, outcome=cls)

    counter = None
    if counter_phase is not None:
        c = counters[0]
        if counter_phase.get("count") is not None:
            high = count_max_key(c) if counter_phase.get("countMax") is not None else count_key(c)
            counter = (slot[count_key(c)], slot[high], ())
        else:
            counter = (NONE, NONE, tuple(int(n) for n in counter_phase["ratios"]))

    def side(r: int) -> int:
        """The input bit of row r's one response mapped `correct`, or NONE."""
        if w is None:
            return NONE
        correct = [key for key in phases[w].get("responses") or [] if maps[r][key].get("outcome") == "correct"]
        return row_in[r][correct[0]] if len(correct) == 1 else NONE

    def slot_or_none(key: str) -> int:
        return slot.get(key, NONE)

    block_table, entries, overrides, first = [], [], [], 0
    reads_entries = any(b.get("select", "uniform") != "uniform" for b in blocks)
    for b, spec in enumerate(blocks):
        reads_weights = spec.get("select", "uniform") in WEIGHTED
        nxt = block_index[str(spec["next"])] if spec.get("next") is not None else b + 1 if b + 1 < len(blocks) else NONE
        n_min = slot_or_none(block_key("BN", b))
        k = slot_or_none(block_key("BK", b))
        errors = (class_mask(spec.get("correctionAfter") or ERROR_CLASSES)
                  if spec.get("correction") is not None else 0)
        block_table.append((first, len(block_rows[b]), SELECTIONS[spec.get("select", "uniform")],
                            n_min, slot.get(block_key("BNX", b), n_min), k, slot_or_none(block_key("BKN", b)),
                            slot_or_none(block_key("BA", b)), slot_or_none(block_key("BC", b)), nxt, errors))
        if reads_entries:
            entries += [(side(r), slot[block_key("W", b, str(e))] if reads_weights else NONE)
                        for e, r in enumerate(block_rows[b], 1)]
        overrides += [(b, slot[timer_key(s.phase)], n) for n, s in enumerate(slots)  # type: ignore[arg-type]
                      if s.role == "block_timer" and s.block == b]
        first += len(block_rows[b])

    if len(states) >= NONE or len(edges) >= NONE or len(branches) >= NONE:
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
        counter=counter,
        blocks=tuple(block_table),
        entries=tuple(entries),
        overrides=tuple(overrides),
        skipped=class_mask(EXCLUDED_CLASSES),
    )
