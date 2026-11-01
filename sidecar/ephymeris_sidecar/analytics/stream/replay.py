"""Replay a session through the phase interpreter, exactly as the board ran it.

A Python port of `firmware/libraries/BehaviorBox/BoxInterp.h`, the board's
pure interpreter core (`0003-phase-spine-task-model.md#replay-and-analytics`).
That header documents the state table, the tick rules and the
actions of a tick; this file follows it line for line and documents only what
is Python's own. Given the table, the parameters, the seed and the input
edges, replay predicts every action the board took, at its tick.

The differential test (`firmware/libraries/BehaviorBox/extras/host_test/run_diff.sh`)
runs both over generated tables and input logs and fails on the first tick
where they differ, so change the two together. A table format or rule change
is a new `INTERP_VERSION` there; this file keeps every version that shipped
and refuses one it does not know.

**Pure**, like the rest of `stream/`: no file, clock or I/O, and no import
outside the standard library, so the differential test can load it by path.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable, Sequence

#: The `INTERP` versions this replay can run (`INTERP_VERSION` in BoxInterp.h),
#: and the one place they are listed. Not 1: that is BehaviorBox.h's trial
#: runner (`BOX_INTERP`), which every recorded GRGL run names, and which no table
#: describes. The two share one numbering space so a run's header alone says
#: which ran it. 2 is the tracer's format; 3 adds the pick state, and 4 the
#: counter and last-trial states. Each is otherwise the one before, so an older
#: table runs under the same rules here, and only what its version lacks is
#: refused in it (`check_interp`). 5 changes no table and no rule here: it adds
#: driven outputs, whose pulse trains are `train_pulses` and whose strobes
#: `stream/spine.py` predicts. 6 adds blocks and the response state.
INTERP_VERSIONS = frozenset({2, 3, 4, 5, 6})
INTERP_VERSION = 6
#: The first version whose outputs can be driven (PWM, tone, a pulse train).
DRIVES_SINCE = 5
#: The first version with blocks and the response state.
BLOCKS_SINCE = 6

NONE = 0xFF
PERMILLE = 1000
RISE = 1
FALL = 2
STARTS_TRIAL = 0x01
PICK = 0x02
COUNT = 0x04
LAST_TRIAL = 0x08
RESPONSE = 0x10
ACT_SESSION_START = 0x01
ACT_TRIAL_START = 0x02
ACT_LAST_TRIAL = 0x04
ACT_BLOCK_START = 0x08
ACT_DONE = 0x10
ACT_CORRECTION = 0x20
#: `InterpBlock.select`.
UNIFORM, WEIGHTED, BAG, ANTIBIAS = 0, 1, 2, 3
#: The outcome class `correct` (`lowering.OUTCOME_CLASSES[0]`). The core reads
#: no class by number: a criterion's hits come from the table (`Blocks.hits`).
CORRECT = 1
#: Responses anti-bias can read, trials a criterion can, tokens a bag holds.
HISTORY = 32
WEIGHT_MAX = 0xFFFF

_U32 = 0xFFFFFFFF
_CHANNELS = 32


# --- the session RNG ----------------------------------------------------------


def _s32(x: int) -> int:
    x &= _U32
    return x - (1 << 32) if x & 0x80000000 else x


def _cdiv(a: int, b: int) -> tuple[int, int]:
    """C's `/` and `%`: the quotient truncates toward zero."""
    q = abs(a) // abs(b)
    q = q if (a < 0) == (b < 0) else -q
    return q, a - q * b


def avr_random(ctx: int) -> tuple[int, int]:
    """avr-libc `random()` from state `ctx`: `(value, next ctx)`. `interp_random()`."""
    x = _s32(ctx)
    if x == 0:
        x = 123459876
    hi, lo = _cdiv(x, 127773)
    x = 16807 * lo - 2836 * hi
    if x < 0:
        x += 0x7FFFFFFF
    ctx = x & _U32
    return ctx % 0x80000000, ctx


def draw(ctx: int, n: int) -> tuple[int, int]:
    """`interp_draw()`: `random() % n` for an unsigned 32-bit n, and 0 without a draw when n is 0."""
    n &= _U32
    if n == 0:
        return 0, ctx
    value, ctx = avr_random(ctx)
    return value % n, ctx


# --- the state table ----------------------------------------------------------


@dataclass(frozen=True)
class EdgeRow:
    """`InterpEdgeRow`: an exit on one input's edge."""

    input: int
    edge: int
    next: int


@dataclass(frozen=True)
class StateRow:
    """`InterpStateRow`. Every field defaults to "none"."""

    outputs: int = 0
    watch: int = 0
    timer_min: int = NONE
    timer_max: int = NONE
    on_timeout: int = NONE
    chance: int = NONE
    on_hit: int = NONE
    on_miss: int = NONE
    edge_first: int = 0
    edge_count: int = 0
    flags: int = 0
    outcome: int = 0

    @property
    def is_chance(self) -> bool:
        return self.chance != NONE

    @property
    def is_pick(self) -> bool:
        return bool(self.flags & PICK)

    @property
    def is_count(self) -> bool:
        return bool(self.flags & COUNT)

    @property
    def branches(self) -> bool:
        """A state that takes no time: it goes on at once, by a draw."""
        return self.is_chance or self.is_pick

    @property
    def slots(self) -> tuple[int, ...]:
        """The parameter slots this state reads."""
        return tuple(s for s in (self.timer_min, self.timer_max, self.chance) if s != NONE)


@dataclass(frozen=True)
class Counter:
    """`InterpCounter`: where a counter state's N comes from.

    `count_min` and `count_max` are parameter slots (equal fixes N, unequal
    draws it); both NONE means N is `ratios[min(step, len - 1)]`.
    """

    count_min: int = NONE
    count_max: int = NONE
    ratios: tuple[int, ...] = ()

    @property
    def slots(self) -> tuple[int, ...]:
        return tuple(s for s in (self.count_min, self.count_max) if s != NONE)


@dataclass(frozen=True)
class Block:
    """`InterpBlock`: one block's rows, selection, end rule, next and correction.

    `first` and `count` are its branches of a trial-starting pick. Every other
    field but `select` and `next` is a parameter slot, NONE for none.
    """

    first: int = 0
    count: int = 1
    select: int = UNIFORM
    n_min: int = NONE
    n_max: int = NONE
    k: int = NONE
    n: int = NONE
    window: int = NONE
    correct: int = NONE
    next: int = NONE
    #: The classes a correction repeats after: bit c-1 for class c.
    errors: int = 0

    @property
    def slots(self) -> tuple[int, ...]:
        return tuple(s for s in (self.n_min, self.n_max, self.k, self.n, self.window, self.correct) if s != NONE)


@dataclass(frozen=True)
class Entry:
    """`InterpEntry`: a branch's side (an input bit, or NONE) and its weight's slot (NONE weighs 1)."""

    side: int = NONE
    weight: int = NONE


@dataclass(frozen=True)
class Override:
    """`InterpOverride`: while `block` runs, a state or the counter reading `slot` reads `with_`."""

    block: int
    slot: int
    with_: int


@dataclass(frozen=True)
class Blocks:
    """`InterpBlocks`: the table's blocks, and the entries and overrides they read."""

    rows: tuple[Block, ...]
    entries: tuple[Entry, ...] = ()
    overrides: tuple[Override, ...] = ()
    #: The classes a criterion's window passes over: bit c-1 for class c.
    skipped: int = 0
    #: The classes a criterion counts as correct (the scorer's hits).
    hits: int = 0

    def __post_init__(self) -> None:
        for name in ("rows", "entries", "overrides"):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def slots(self) -> tuple[int, ...]:
        return (*(x for b in self.rows for x in b.slots),
                *(e.weight for e in self.entries if e.weight != NONE),
                *(x for o in self.overrides for x in (o.slot, o.with_)))


@dataclass(frozen=True)
class Table:
    """A state table, refused on construction unless BoxInterp.h's "a valid table" holds.

    The C core assumes a valid table and checks nothing, so this is the one
    place validity is enforced.
    """

    states: tuple[StateRow, ...]
    edges: tuple[EdgeRow, ...] = ()
    counter: Counter | None = None
    blocks: Blocks | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "edges", tuple(self.edges))
        if not 1 <= len(self.states) < NONE:
            raise ValueError(f"a table has 1 to {NONE - 1} states, not {len(self.states)}")
        if len(self.edges) >= NONE:
            raise ValueError(f"a table has at most {NONE - 1} edge rows")
        if self.counter is not None:
            _check_counter(self.counter)
        if self.blocks is not None:
            _check_blocks(self, self.blocks)
        for i, s in enumerate(self.states):
            _check_state(self, i, s)

    def slots_used(self) -> int:
        """One more than the highest parameter slot any state, the counter or a block reads."""
        counter = self.counter.slots if self.counter is not None else ()
        blocks = self.blocks.slots if self.blocks is not None else ()
        return max((slot + 1 for slot in (*counter, *blocks, *(x for s in self.states for x in s.slots))),
                   default=0)


def _check_blocks(table: Table, b: Blocks) -> None:
    def byte(value: int, what: str) -> None:
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{what} does not fit a uint8_t")

    if not 1 <= len(b.rows) < NONE:
        raise ValueError(f"a table has 1 to {NONE - 1} blocks, not {len(b.rows)}")
    if len(b.entries) >= NONE or len(b.overrides) >= NONE:
        raise ValueError(f"a table has at most {NONE - 1} entries and {NONE - 1} overrides")
    for i, k in enumerate(b.rows):
        for name in ("first", "count", "select", "n_min", "n_max", "k", "n", "window", "correct", "next"):
            byte(getattr(k, name), f"block {i}'s {name}")
        if k.count < 1 or k.first + k.count > NONE:
            raise ValueError(f"block {i} draws one or more branches, each below {NONE}")
        if k.select not in (UNIFORM, WEIGHTED, BAG, ANTIBIAS):
            raise ValueError(f"block {i}'s select {k.select} is not one of 0-3")
        if not 0 <= k.errors <= 0xFFFF:
            raise ValueError(f"block {i}'s errors do not fit a uint16_t")
        if (k.n_min == NONE) != (k.n_max == NONE) or (k.k == NONE) != (k.n == NONE):
            raise ValueError(f"block {i}'s N and criterion are each two slots, or none")
        if k.next != NONE and k.next >= len(b.rows):
            raise ValueError(f"block {i}'s next {k.next} is not a block")
        if b.entries and k.first + k.count > len(b.entries):
            raise ValueError(f"block {i}'s branches run past the table's entries")
        for s in table.states:
            if s.is_pick and s.flags & STARTS_TRIAL and k.first + k.count > s.edge_count:
                raise ValueError(f"block {i}'s branches run past a trial-starting pick's")
    if not 0 <= b.skipped <= 0xFFFF or not 0 <= b.hits <= 0xFFFF:
        raise ValueError("the blocks' skipped and hit classes each fit a uint16_t")
    for e in b.entries:
        byte(e.side, "an entry's side")
        byte(e.weight, "an entry's weight")
    for o in b.overrides:
        for name in ("block", "slot", "with_"):
            byte(getattr(o, name), f"an override's {name}")
        if o.block >= len(b.rows) or NONE in (o.slot, o.with_):
            raise ValueError("an override names a block and two slots")


def _check_counter(k: Counter) -> None:
    if (k.count_min == NONE) != (k.count_max == NONE):
        raise ValueError("a counter's count_min and count_max are both slots, or both NONE")
    for name in ("count_min", "count_max"):
        if not 0 <= getattr(k, name) <= 0xFF:
            raise ValueError(f"the counter's {name} does not fit a uint8_t")
    if k.count_min == NONE:
        if not 1 <= len(k.ratios) < NONE:
            raise ValueError(f"a counter with no slots reads 1 to {NONE - 1} ratios, not {len(k.ratios)}")
    if any(not 1 <= r <= 0xFFFF for r in k.ratios):
        raise ValueError("every ratio is 1 to 65535")


def _check_state(table: Table, i: int, s: StateRow) -> None:
    n = len(table.states)

    def fail(why: str) -> None:
        raise ValueError(f"state {i}: {why}")

    def target(name: str) -> None:
        if not 0 <= getattr(s, name) < n:
            fail(f"{name} {getattr(s, name)} is not a state")

    for name in ("outputs", "watch"):
        if not 0 <= getattr(s, name) <= _U32:
            fail(f"{name} does not fit 32 channels")
    for name in ("timer_min", "timer_max", "on_timeout", "chance", "on_hit", "on_miss",
                 "edge_first", "edge_count", "flags", "outcome"):
        if not 0 <= getattr(s, name) <= 0xFF:
            fail(f"{name} does not fit a uint8_t")
    if s.flags & ~(STARTS_TRIAL | PICK | COUNT | LAST_TRIAL | RESPONSE):
        fail(f"unknown flags {s.flags:#x}")
    if s.flags & LAST_TRIAL and (s.branches or s.flags & STARTS_TRIAL):
        fail("a last-trial state neither branches nor starts a trial")
    if s.is_count:
        if s.branches:
            fail("a counter state is neither a chance nor a pick state")
        if table.counter is None:
            fail("a counter state in a table with no counter")
        if s.edge_count != 1:
            fail("a counter state has exactly one edge row, its counted rise")
        elif s.edge_first < len(table.edges) and table.edges[s.edge_first].edge != RISE:
            fail("a counter state counts a RISE")

    if s.is_chance:
        if s.outputs or s.watch or s.timer_min != NONE or s.edge_count:
            fail("a chance state has no outputs, watch, timer or edge rows")
        for name in ("on_hit", "on_miss"):
            target(name)
            if table.states[getattr(s, name)].is_chance:
                fail(f"a chance state's {name} is another chance state")
            if table.states[getattr(s, name)].is_pick:
                fail(f"a chance state's {name} is a pick state")
    elif s.on_hit != NONE or s.on_miss != NONE:
        fail("on_hit and on_miss belong to a chance state")

    if s.is_pick:
        if s.outputs or s.watch or s.timer_min != NONE or s.timer_max != NONE or s.on_timeout != NONE:
            fail("a pick state has no outputs, watch, timer or chance")
        if not s.edge_count:
            fail("a pick state needs at least one branch")
        if s.edge_first + s.edge_count > len(table.edges):
            fail("its edge rows run past the table's")
        for e in table.edges[s.edge_first : s.edge_first + s.edge_count]:
            if (e.input, e.edge) != (0, 0):
                fail("a pick state's branches are edge rows (input 0, edge 0)")
            if not 0 <= e.next < n:
                fail(f"a branch {e.next} is not a state")
            if table.states[e.next].branches:
                fail("a pick state's branches are neither chance nor pick states")
        return

    if s.timer_min == NONE:
        if s.timer_max != NONE or s.on_timeout != NONE:
            fail("timer_max and on_timeout need a timer_min")
    else:
        if s.timer_max == NONE:
            fail("timer_max is missing")
        target("on_timeout")

    if s.edge_first + s.edge_count > len(table.edges):
        fail("its edge rows run past the table's")
    seen: set[tuple[int, int]] = set()
    for e in table.edges[s.edge_first : s.edge_first + s.edge_count]:
        if not 0 <= e.input < _CHANNELS:
            fail(f"input {e.input} is not one of {_CHANNELS} channels")
        if e.edge not in (RISE, FALL):
            fail(f"edge {e.edge} is neither RISE nor FALL")
        if not s.watch >> e.input & 1:
            fail(f"input {e.input} has an exit but is not watched")
        if (e.input, e.edge) in seen:
            fail(f"input {e.input} has the same edge twice")
        seen.add((e.input, e.edge))
        if not 0 <= e.next < n:
            fail(f"an edge row's next {e.next} is not a state")


# --- one tick -----------------------------------------------------------------


@dataclass(frozen=True)
class Edges:
    """`InterpEdges`: one tick's input edges, by input bit."""

    rose: int = 0
    fell: int = 0


@dataclass(frozen=True)
class Actions:
    """`InterpActions`: what the board did at one tick."""

    rose: int = 0
    fell: int = 0
    on: int = 0
    off: int = 0
    entered: tuple[int, int] = (NONE, NONE)
    flags: int = 0
    #: The block running after this tick; NONE in a table without blocks.
    block: int = NONE

    @property
    def idle(self) -> bool:
        """`interp_idle()`: no report and no transition."""
        return not (self.rose or self.fell or self.flags) and self.entered[0] == NONE


@dataclass(frozen=True)
class Core:
    """`InterpCore`: a running session's whole state."""

    table: Table
    params: tuple[int, ...]
    rng: int
    entered_at: int = 0
    duration: int = 0
    outputs: int = 0
    count: int = 0
    target: int = 0
    step: int = 0
    state: int = 0
    corrects: int = 0
    bag: int = 0
    block_trials: int = 0
    block_n: int = 0
    block: int = NONE
    outcome: int = 0
    response: int = NONE
    entry: int = NONE
    repeats: int = 0
    correcting: bool = False
    hist: tuple[int, ...] = (NONE,) * HISTORY
    hist_len: int = 0
    hist_at: int = 0


class _Run:
    """A `Core` while one tick changes it: the C core writes its struct in place."""

    def __init__(self, core: Core) -> None:
        self.__dict__.update({f: getattr(core, f) for f in Core.__dataclass_fields__})
        self.hist = list(core.hist)

    def done(self) -> Core:
        return Core(**{f: (tuple(self.hist) if f == "hist" else getattr(self, f)) for f in Core.__dataclass_fields__})

    def draw(self, n: int) -> int:
        value, self.rng = draw(self.rng, n)
        return value


@dataclass
class _Tick:
    """One tick's actions while they are built, mirroring the C struct's fields."""

    rose: int = 0
    fell: int = 0
    on: int = 0
    off: int = 0
    entered: list[int] = field(default_factory=lambda: [NONE, NONE])
    flags: int = 0

    def done(self, block: int) -> Actions:
        return Actions(self.rose, self.fell, self.on, self.off, (self.entered[0], self.entered[1]), self.flags,
                       block)


def _pick(rng: int, branches: int) -> tuple[int, int]:
    """A pick state's draw: which of its `branches` it takes. Every entry draws."""
    return draw(rng, branches)


def _param(c: _Run, slot: int) -> int:
    """`interp__param()`: the running block's first override of `slot`, or its own."""
    blocks = c.table.blocks
    if blocks is not None:
        for o in blocks.overrides:
            if o.block == c.block and o.slot == slot:
                return c.params[o.with_]
    return c.params[slot]


def _ones(x: int) -> int:
    return bin(x & _U32).count("1")


def _class_in(mask: int, cls: int) -> bool:
    """`interp__class_in()`: class `cls` is in `mask`. No class, and one past the 16th, is in none."""
    return 1 <= cls <= 16 and bool(mask >> (cls - 1) & 1)


def _skips(c: _Run, cls: int) -> bool:
    """Whether a trial of class `cls` stays out of a criterion's window (an abort)."""
    return _class_in(c.table.blocks.skipped, cls)  # type: ignore[union-attr]


def _hit(c: _Run, cls: int) -> bool:
    """Whether a trial of class `cls` counts as correct in a criterion (the scorer's hits)."""
    return _class_in(c.table.blocks.hits, cls)  # type: ignore[union-attr]


def _is_error(k: Block, cls: int) -> bool:
    """Whether a trial of class `cls` is one block `k`'s correction repeats after."""
    return _class_in(k.errors, cls)


def _start_block(c: _Run, b: int, a: _Tick) -> None:
    """`interp__start_block()`: its counters and bag start over, and its N is drawn."""
    k = c.table.blocks.rows[b]  # type: ignore[union-attr]
    c.block, c.block_trials, c.block_n, c.corrects, c.bag, c.repeats = b, 0, 0, 0, 0, 0
    if k.n_min != NONE:
        lo, hi = c.params[k.n_min], c.params[k.n_max]
        c.block_n = ((lo + c.draw(hi - lo + 1)) if hi > lo else lo) & 0xFFFF
    a.flags |= ACT_BLOCK_START


def _block_ends(c: _Run, k: Block) -> bool:
    """`interp__block_ends()`: N trials started, or k of the last n correct."""
    if k.n_min != NONE and c.block_trials >= c.block_n:
        return True
    if k.k != NONE:
        n = c.params[k.n]
        mask = _U32 if n >= HISTORY else (1 << n) - 1
        if _ones(c.corrects & mask) >= c.params[k.k]:
            return True
    return False


def _next_block(k: Block) -> int:
    """The block entered when `k` ends; NONE: the blocks are done."""
    return k.next


def _repeats(c: _Run, k: Block, last_outcome: int) -> bool:
    """The correction rule: the last trial, marked and not correct, repeats while under its limit."""
    return k.correct != NONE and _is_error(k, last_outcome) and c.repeats < c.params[k.correct]


def _trial(c: _Run, a: _Tick) -> None:
    """`interp__trial()`: a trial starts in a table with blocks."""
    last_outcome, last_entry = c.outcome, c.entry
    c.entry, c.correcting = NONE, False
    if c.block == NONE:
        _start_block(c, 0, a)
    else:
        # An aborted trial counts toward N but not in the criterion's window.
        if not _skips(c, last_outcome):
            c.corrects = ((c.corrects << 1) | (1 if _hit(c, last_outcome) else 0)) & _U32
        if c.response != NONE:
            c.hist[c.hist_at] = c.response
            c.hist_at = (c.hist_at + 1) % HISTORY
            c.hist_len = min(c.hist_len + 1, HISTORY)
        k = c.table.blocks.rows[c.block]  # type: ignore[union-attr]
        if _block_ends(c, k):
            nxt = _next_block(k)
            if nxt == NONE:
                a.flags |= ACT_DONE
            else:
                _start_block(c, nxt, a)
        elif _repeats(c, k, last_outcome):
            c.repeats += 1
            c.correcting, c.entry = True, last_entry
            a.flags |= ACT_CORRECTION
        else:
            c.repeats = 0
    c.outcome, c.response = 0, NONE
    c.block_trials = min(c.block_trials + 1, 0xFFFF)


def _weight(c: _Run, e: int) -> int:
    entries = c.table.blocks.entries  # type: ignore[union-attr]
    if not entries or entries[e].weight == NONE:
        return 1
    return min(c.params[entries[e].weight], WEIGHT_MAX)


def _side(c: _Run, e: int) -> int:
    entries = c.table.blocks.entries  # type: ignore[union-attr]
    return entries[e].side if entries else NONE


def _branches(k: Block) -> range:
    return range(k.first, k.first + k.count)


def _uniform(c: _Run, k: Block) -> int:
    """`uniform`: one of the block's branches, r = draw(count)."""
    return k.first + c.draw(k.count)


def _by_weight(c: _Run, k: Block, side: int | None = None) -> int:
    """`interp__by_weight()`: by weight, or uniformly when the weights sum to 0;
    only the branches on `side` when one is given."""
    mine = [e for e in _branches(k) if side is None or _side(c, e) == side]
    weights = [_weight(c, e) for e in mine]
    if not sum(weights):
        weights = [1] * len(mine)
    r = c.draw(sum(weights))
    for e, w in zip(mine, weights):
        if r < w:
            return e
        r -= w
    return k.first + k.count - 1  # unreachable: r is below the sum


def _from_bag(c: _Run, k: Block) -> int:
    """`interp__from_bag()`: a shuffle bag of each branch's weight in tokens, at
    most HISTORY in all, drawn without replacement and refilled once empty."""
    total = min(sum(_weight(c, e) for e in _branches(k)), HISTORY)
    if total == 0:
        return k.first + c.draw(k.count)
    full = (1 << total) - 1
    if c.bag & full == full:
        c.bag = 0
    r = c.draw(total - _ones(c.bag & full))
    token = 0
    while True:
        if not c.bag >> token & 1:
            if r == 0:
                break
            r -= 1
        token += 1
    c.bag |= 1 << token
    upto = 0
    for e in _branches(k):
        upto += _weight(c, e)
        if token < upto:
            return e
    return k.first + k.count - 1  # unreachable


def _side_weight(c: _Run, side: int, length: int) -> int:
    """Anti-bias: a side weighs 1 + L - its count among the last L responses."""
    count = sum(1 for j in range(length) if c.hist[(c.hist_at + HISTORY - 1 - j) % HISTORY] == side)
    return 1 + length - count


def _antibias(c: _Run, k: Block) -> int:
    """`interp__antibias()`: a side against the last responses, then a branch on it by weight."""
    length = c.hist_len
    if k.window != NONE and c.params[k.window] < length:
        length = c.params[k.window]
    sides: list[int] = []
    for e in _branches(k):
        if _side(c, e) not in sides:
            sides.append(_side(c, e))
    weights = [_side_weight(c, s, length) for s in sides]
    r = c.draw(sum(weights))
    for s, w in zip(sides, weights):
        if r < w:
            return _by_weight(c, k, s)
        r -= w
    return k.first  # unreachable


def _select(c: _Run) -> int:
    """`interp__select()`: a trial-starting pick's branch in a table with blocks."""
    k = c.table.blocks.rows[c.block]  # type: ignore[union-attr]
    if c.correcting and c.entry != NONE:
        return c.entry
    if k.select == WEIGHTED:
        return _by_weight(c, k)
    if k.select == BAG:
        return _from_bag(c, k)
    if k.select == ANTIBIAS:
        return _antibias(c, k)
    return _uniform(c, k)


def _enter(core: Core, target: int, now: int, a: _Tick) -> Core:
    """`interp__enter()`."""
    c = _Run(core)
    table = c.table
    hop = 0
    while True:
        s = table.states[target]
        a.entered[hop] = target
        if s.flags & STARTS_TRIAL:
            a.flags |= ACT_TRIAL_START
            if table.blocks is not None:
                _trial(c, a)
        if s.flags & LAST_TRIAL:
            a.flags |= ACT_LAST_TRIAL
        if s.outcome:
            c.outcome = s.outcome
        c.state = target
        if not s.branches or hop == 1:
            break
        if s.is_chance:
            target = s.on_hit if c.draw(PERMILLE) < _param(c, s.chance) else s.on_miss
        elif table.blocks is not None and s.flags & STARTS_TRIAL:
            c.entry = _select(c)
            target = table.edges[s.edge_first + c.entry].next
        else:
            k, c.rng = _pick(c.rng, s.edge_count)
            target = table.edges[s.edge_first + k].next
        hop += 1
    if s.is_count:
        # N first, then the duration: the order the core draws them in.
        k = table.counter
        assert k is not None
        c.count = 0
        if k.count_min == NONE:
            c.target = k.ratios[min(c.step, len(k.ratios) - 1)]
        else:
            c.target, c.rng = _count_of(c.rng, _param(c, k.count_min), _param(c, k.count_max))
    c.duration = 0
    if s.timer_min != NONE:
        lo, hi = _param(c, s.timer_min), _param(c, s.timer_max)
        c.duration = ((lo + c.draw(hi - lo + 1)) & _U32) if hi > lo else lo
    a.on = s.outputs & ~c.outputs & _U32
    a.off = c.outputs & ~s.outputs & _U32
    c.outputs = s.outputs
    c.entered_at = now
    return c.done()


def _count_of(rng: int, lo: int, hi: int) -> tuple[int, int]:
    """A drawn or fixed N, as the core's uint16_t holds it."""
    if hi > lo:
        value, rng = draw(rng, hi - lo + 1)
        return (lo + value) & 0xFFFF, rng
    return lo & 0xFFFF, rng


def _counted(core: Core) -> tuple[Core, bool]:
    """A counter state's counted rise: the new core, and whether it is the N-th,
    so an exit. Below N it moves nothing and leaves the timer to run."""
    count = core.count + 1
    if count < core.target:
        return replace(core, count=count), False
    return replace(core, count=count, step=min(core.step + 1, 0xFF)), True


def check_interp(table: Table, interp: int) -> None:
    """Refuse a table `interp` cannot have run: an unknown version, a pick state
    before 3, a counter or last-trial state before 4, or blocks or a response
    state before 6."""
    if interp not in INTERP_VERSIONS:
        raise ValueError(f"INTERP {interp} is not a version this replay knows ({sorted(INTERP_VERSIONS)})")
    if interp < 3 and any(s.is_pick for s in table.states):
        raise ValueError(f"INTERP {interp} has no pick state, and this table holds one")
    if interp < 4 and (table.counter is not None or any(s.is_count for s in table.states)):
        raise ValueError(f"INTERP {interp} has no counter, and this table holds one")
    if interp < 4 and any(s.flags & LAST_TRIAL for s in table.states):
        raise ValueError(f"INTERP {interp} has no last-trial state, and this table holds one")
    if interp < BLOCKS_SINCE and (table.blocks is not None or any(s.flags & RESPONSE for s in table.states)):
        raise ValueError(f"INTERP {interp} has no blocks or response state, and this table holds one")


def begin(
    table: Table, params: Sequence[int], seed: int, now: int, interp: int = INTERP_VERSION
) -> tuple[Core, Actions]:
    """`interp_begin()`: the session's first tick, at `now`."""
    check_interp(table, interp)
    params = tuple(params)
    if len(params) < table.slots_used():
        raise ValueError(f"the table reads parameter slot {table.slots_used() - 1}, past the {len(params)} given")
    if any(not 0 <= p <= _U32 for p in params):
        raise ValueError("every parameter is a uint32_t")
    core = Core(table=table, params=params, rng=seed & _U32)
    a = _Tick(flags=ACT_SESSION_START)
    core = _enter(core, 0, now & _U32, a)
    return core, a.done(core.block)


def _matches(e: EdgeRow, a: _Tick) -> bool:
    return bool((a.rose if e.edge == RISE else a.fell) >> e.input & 1)


def _break_tie(rng: int, matching: list[EdgeRow]) -> tuple[EdgeRow, int]:
    """Tick rule 3: the k-th matching edge row in table order, k drawn when there are two or more."""
    if len(matching) == 1:
        return matching[0], rng
    k, rng = draw(rng, len(matching))
    return matching[k], rng


def step(core: Core, edges: Edges, now: int) -> tuple[Core, Actions]:
    """`interp_step()`: every tick after the first."""
    now &= _U32
    s = core.table.states[core.state]
    rows = core.table.edges[s.edge_first : s.edge_first + s.edge_count]
    a = _Tick(rose=edges.rose & s.watch, fell=edges.fell & s.watch)

    matching = [e for e in rows if _matches(e, a)]
    if matching and s.is_count:
        core, exits = _counted(core)
        if not exits:
            matching = []
    target = NONE
    if matching:
        taken, rng = _break_tie(core.rng, matching)
        core = replace(core, rng=rng)
        target = taken.next
        # An edge out of a response state is the trial's response, its first only.
        if s.flags & RESPONSE and core.response == NONE:
            core = replace(core, response=taken.input)
    elif s.timer_min != NONE and (now - core.entered_at) & _U32 >= core.duration:
        target = s.on_timeout
    if target != NONE:
        core = _enter(core, target, now, a)
    return core, a.done(core.block)


# --- pulse trains -------------------------------------------------------------


def _rise(j: int, hz: int) -> int:
    """Pulse j of a second rises this many ms into it (BoxInterp.h, PULSE TRAINS)."""
    return j * 1000 // hz


def train_pulses(hz: int, width: int, length: int) -> list[tuple[int, int]]:
    """Every pulse of a train that ran `length` ticks, as (rise, fall) offsets
    from its first tick; a pulse still HIGH at `length` falls there.

    Worked out pulse by pulse, never tick by tick, so the differential test
    holds two different computations of one train to each other: the C side
    steps `interp_train_high()` on every tick. A pulse is HIGH from its rise to
    `width` ms later or the next rise, whichever is first, and two that touch
    are one.
    """
    if hz <= 0 or width <= 0 or length <= 0:
        return []
    out: list[tuple[int, int]] = []
    for base in range(0, length, 1000):
        for j in range(hz):
            rise = base + _rise(j, hz)
            if rise >= length:
                return out
            nxt = base + _rise(j + 1, hz)  # _rise(hz, hz) is 1000: the next second's first
            fall = min(rise + width, nxt, length)
            if out and out[-1][1] == rise:
                out[-1] = (out[-1][0], fall)
            else:
                out.append((rise, fall))
    return out


# --- a whole session ----------------------------------------------------------


def _due_in(core: Core, now: int) -> int | None:
    """Ticks from `now` until the resting state's timer is checked and runs out."""
    if core.table.states[core.state].timer_min == NONE:
        return None
    elapsed = (now - core.entered_at) & _U32
    return max(1, core.duration - elapsed)


def replay(
    table: Table,
    params: Sequence[int],
    seed: int,
    events: Iterable[tuple[int, Edges]],
    ticks: int,
    start: int = 0,
    interp: int = INTERP_VERSION,
) -> list[tuple[int, Actions]]:
    """Every tick that did something, from `start` through `start + ticks`.

    `events` are `(now, edges)` in tick order, at most one per tick, each after
    `start` and no later than its last tick; `now` is millis() and may wrap.
    The board steps every tick; an idle tick changes nothing, so this jumps
    from one edge or timer to the next and produces the same actions.
    """
    core, first = begin(table, params, seed, start, interp)
    out = [(start & _U32, first)]
    offset = 0
    pending = [((now - start) & _U32, edges) for now, edges in events]
    for (a, _), (b, _) in zip(pending, pending[1:]):
        if b <= a:
            raise ValueError(f"events are one per tick, in order: {a} then {b}")
    if pending and not (1 <= pending[0][0] and pending[-1][0] <= ticks):
        raise ValueError("events fall after the first tick and within the run")
    i = 0
    while True:
        due = _due_in(core, (start + offset) & _U32)
        nxt = offset + due if due is not None else None
        if i < len(pending) and (nxt is None or pending[i][0] <= nxt):
            nxt, edges = pending[i][0], pending[i][1]
            i += 1
        else:
            edges = Edges()
        if nxt is None or nxt > ticks:
            return out
        offset = nxt
        now = (start + offset) & _U32
        core, actions = step(core, edges, now)
        if not actions.idle:
            out.append((now, actions))
