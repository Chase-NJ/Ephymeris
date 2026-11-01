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
#: refused in it (`check_interp`).
INTERP_VERSIONS = frozenset({2, 3, 4})
INTERP_VERSION = 4

NONE = 0xFF
PERMILLE = 1000
RISE = 1
FALL = 2
STARTS_TRIAL = 0x01
PICK = 0x02
COUNT = 0x04
LAST_TRIAL = 0x08
ACT_SESSION_START = 0x01
ACT_TRIAL_START = 0x02
ACT_LAST_TRIAL = 0x04

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
class Table:
    """A state table, refused on construction unless BoxInterp.h's "a valid table" holds.

    The C core assumes a valid table and checks nothing, so this is the one
    place validity is enforced.
    """

    states: tuple[StateRow, ...]
    edges: tuple[EdgeRow, ...] = ()
    counter: Counter | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "states", tuple(self.states))
        object.__setattr__(self, "edges", tuple(self.edges))
        if not 1 <= len(self.states) < NONE:
            raise ValueError(f"a table has 1 to {NONE - 1} states, not {len(self.states)}")
        if len(self.edges) >= NONE:
            raise ValueError(f"a table has at most {NONE - 1} edge rows")
        if self.counter is not None:
            _check_counter(self.counter)
        for i, s in enumerate(self.states):
            _check_state(self, i, s)

    def slots_used(self) -> int:
        """One more than the highest parameter slot any state, or the counter, reads."""
        counter = self.counter.slots if self.counter is not None else ()
        return max((slot + 1 for slot in (*counter, *(x for s in self.states for x in s.slots))), default=0)


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
    if s.flags & ~(STARTS_TRIAL | PICK | COUNT | LAST_TRIAL):
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


@dataclass
class _Tick:
    """One tick's actions while they are built, mirroring the C struct's fields."""

    rose: int = 0
    fell: int = 0
    on: int = 0
    off: int = 0
    entered: list[int] = field(default_factory=lambda: [NONE, NONE])
    flags: int = 0

    def done(self) -> Actions:
        return Actions(self.rose, self.fell, self.on, self.off, (self.entered[0], self.entered[1]), self.flags)


def _pick(rng: int, branches: int) -> tuple[int, int]:
    """A pick state's draw: which of its `branches` it takes. Every entry draws."""
    return draw(rng, branches)


def _enter(core: Core, target: int, now: int, a: _Tick) -> Core:
    """`interp__enter()`."""
    states, params, rng = core.table.states, core.params, core.rng
    hop = 0
    while True:
        s = states[target]
        a.entered[hop] = target
        if s.flags & STARTS_TRIAL:
            a.flags |= ACT_TRIAL_START
        if s.flags & LAST_TRIAL:
            a.flags |= ACT_LAST_TRIAL
        state = target
        if not s.branches or hop == 1:
            break
        if s.is_chance:
            value, rng = draw(rng, PERMILLE)
            target = s.on_hit if value < params[s.chance] else s.on_miss
        else:
            k, rng = _pick(rng, s.edge_count)
            target = core.table.edges[s.edge_first + k].next
        hop += 1
    count, n = core.count, core.target
    if s.is_count:
        # N first, then the duration: the order the core draws them in.
        k = core.table.counter
        assert k is not None
        count = 0
        if k.count_min == NONE:
            n = k.ratios[min(core.step, len(k.ratios) - 1)]
        else:
            n, rng = _count_of(rng, params[k.count_min], params[k.count_max])
    duration = 0
    if s.timer_min != NONE:
        lo, hi = params[s.timer_min], params[s.timer_max]
        if hi > lo:
            value, rng = draw(rng, hi - lo + 1)
            duration = (lo + value) & _U32
        else:
            duration = lo
    a.on = s.outputs & ~core.outputs & _U32
    a.off = core.outputs & ~s.outputs & _U32
    return replace(core, rng=rng, entered_at=now, duration=duration, outputs=s.outputs, count=count,
                   target=n, state=state)


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
    before 3, or a counter or last-trial state before 4."""
    if interp not in INTERP_VERSIONS:
        raise ValueError(f"INTERP {interp} is not a version this replay knows ({sorted(INTERP_VERSIONS)})")
    if interp < 3 and any(s.is_pick for s in table.states):
        raise ValueError(f"INTERP {interp} has no pick state, and this table holds one")
    if interp < 4 and (table.counter is not None or any(s.is_count for s in table.states)):
        raise ValueError(f"INTERP {interp} has no counter, and this table holds one")
    if interp < 4 and any(s.flags & LAST_TRIAL for s in table.states):
        raise ValueError(f"INTERP {interp} has no last-trial state, and this table holds one")


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
    return core, a.done()


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
    elif s.timer_min != NONE and (now - core.entered_at) & _U32 >= core.duration:
        target = s.on_timeout
    if target != NONE:
        core = _enter(core, target, now, a)
    return core, a.done()


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
