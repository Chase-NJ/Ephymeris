"""A spine run's trial table, read off its replay (`ANALYTICS.md#how-a-spine-run-is-scored`).

One row per trial. Every column is read from the state table's own fields, never
from a phase kind or a code name, so a phase or an outcome class added later is
scored with no change here:

- a trial starts where a state flagged `STARTS_TRIAL` is entered. A tick can
  finish one trial and start the next (a chance state that misses straight
  back to the start): the hops before the flagged state are the old trial's;
- its **outcome class** is the `outcome` of the last outcome-bearing state it
  entered (0 when it entered none, as an abort to the ITI does);
- it is **rewarded** when it took the `on_hit` branch of a chance state that
  bears an outcome. The reward line is the outputs `on_hit` drives and
  `on_miss` does not, and the reward time is the ticks actually spent in it;
- its **response**, when the snapshot maps states to phases, is the first edge
  exit the trial took out of a Response window phase's states (the window and
  the hold after it), and its latency runs from the trial's first entry into
  that phase. A trial decided by a timer (an omission, a withhold) and a spine
  with no window (the tracer) have none. A held response, kept or broken, is
  the window's edge, timed from the window opening;
- **without a phase map**, the response is an edge exit out of a **deciding**
  state: one with two or more exits (edge rows and its timer) from which an outcome-bearing state can
  be reached before the next trial starts, as a response window's every
  response and its timeout can. Of the trial's edge exits out of deciding
  states before its first outcome-bearing state, the last one names a phase P;
  the response is the first edge exit of the trial's visit to P, and its
  latency runs from that visit's entry, each state its own phase. A trial
  decided by a timer has none, and neither has a spine with no deciding state;
- an input's **count** is its watched rises, attributed to the state held before
  the tick, as the interpreter attributes them.

`trials_of` works in states, ticks and bits; `name` turns one trial into the
row the wire carries, through the snapshot's `Naming`.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ...taskdef.lowering import EXCLUDED_CLASSES, HIT_CLASSES, OUTCOME_CLASSES, OUTCOME_CORRECT
from . import replay as rp

CORRECT = OUTCOME_CLASSES[OUTCOME_CORRECT - 1]

#: The outcome classes a trial is right in, for a spine row's `correct` and so
#: for P(correct | row) and the pooled figure (`ANALYTICS.md#metrics-from-the-trial-table`).
#: A withhold is a no-go row's correct answer, so a perfect go/no-go session
#: scores 1.0. Every other class (false alarm, wrong response, omission, hold
#: broken, one added later) is a miss, except the aborts in `EXCLUDED`; those
#: and a trial with no class are excluded. A block's criterion counts the same
#: trials as correct (`lowering.HIT_CLASSES`).
HITS = frozenset(HIT_CLASSES)

#: The classes a trial is excluded in, as a legacy run excludes a trial the
#: animal left before it was answered: an abort is neither right nor wrong. It
#: still counts in the class tallies and on the engagement ladder. A block's
#: criterion passes over the same trials (`lowering.EXCLUDED_CLASSES`).
EXCLUDED = frozenset(EXCLUDED_CLASSES)


def correct_of(outcome: str | None) -> bool | None:
    """A spine trial's `correct`: in `HITS`, a miss, or None (no class, or `EXCLUDED`)."""
    if outcome is None or outcome in EXCLUDED:
        return None
    return outcome in HITS


@dataclass(frozen=True)
class Trial:
    """One trial in table terms: states, ticks and bits."""

    index: int
    at: int
    #: First entry tick of each state the trial entered.
    entries: dict[int, int]
    outcome: int = 0
    #: The tick it entered the outcome-bearing state its class is read from.
    outcome_at: int | None = None
    #: (input bit, RISE or FALL), or None.
    response: tuple[int, int] | None = None
    response_at: int | None = None
    latency: int | None = None
    rewarded: bool = False
    reward_outputs: int = 0
    reward_ms: int | None = None
    #: (state, input bit) -> watched rises while in that state.
    counts: dict[tuple[int, int], int] = field(default_factory=dict)
    #: The next trial started, or the session ended at a trial start.
    complete: bool = False


@dataclass
class _Open:
    """A trial while its ticks are read."""

    index: int
    at: int
    #: (state entered, tick, the state it was entered from, the edge row that took it there)
    path: list[tuple[int, int, int | None, rp.EdgeRow | None]] = field(default_factory=list)
    counts: dict[tuple[int, int], int] = field(default_factory=dict)
    reward_state: int | None = None
    reward_at: int | None = None
    reward_ms: int | None = None
    reward_outputs: int = 0


def trials_of(
    table: rp.Table,
    actions: Iterable[tuple[int, rp.Actions]],
    *,
    end: int | None,
    phase_of: Sequence[int | None] | None = None,
    windows: frozenset[int] | None = None,
) -> list[Trial]:
    """Every trial of a replay, in order.

    `actions` are `replay.replay`'s, through the session's last tick. `end` is
    the tick the session ended at (its trial start opens no trial), or None for
    a run cut off before it ended, whose last trial is then incomplete.
    `phase_of[s]` is state s's phase, None for a state in no phase, and
    `windows` the Response window phases; given both, a response is read only
    from a window.
    """
    states = table.states

    def phase(s: int) -> int:
        # A state in no phase (a pick) is a phase of its own, never another's.
        p = phase_of[s] if phase_of is not None else s
        return p if p is not None else -1 - s

    deciding = _deciding(table)
    window_states = (frozenset(s for s, p in enumerate(phase_of) if p in windows)
                     if phase_of is not None and windows is not None else None)
    out: list[Trial] = []
    current: _Open | None = None
    held: int | None = None  # the state held before this tick

    def walk(trial: _Open | None, entered: list[int], hops: range, now: int, edge: rp.EdgeRow | None) -> None:
        if trial is None:
            return
        for h in hops:
            s = entered[h]
            trial.path.append((s, now, held if h == 0 else entered[h - 1], edge if h == 0 else None))
            row = states[s]
            if row.is_chance and row.outcome and h + 1 in hops and entered[h + 1] == row.on_hit:
                trial.reward_state, trial.reward_at = row.on_hit, now
                miss = states[row.on_miss].outputs if row.on_miss != rp.NONE else 0
                trial.reward_outputs = states[row.on_hit].outputs & ~miss

    for now, a in actions:
        if current is not None and held is not None and a.rose:
            for bit in _bits(a.rose):
                key = (held, bit)
                current.counts[key] = current.counts.get(key, 0) + 1
        entered = [s for s in a.entered if s != rp.NONE]
        if not entered:
            continue
        if current is not None and current.reward_state == held and current.reward_ms is None:
            current.reward_ms = now - (current.reward_at or now)
        edge = _taken(table, held, a, entered[0]) if held is not None else None
        split = len(entered)
        if a.flags & rp.ACT_TRIAL_START:
            split = next((h for h, s in enumerate(entered) if states[s].flags & rp.STARTS_TRIAL), 0)
        walk(current, entered, range(split), now, edge)
        if split < len(entered):
            if current is not None:
                out.append(_close(current, states, phase, deciding, window_states, complete=True))
                current = None
            if end is not None and now == end:
                return out
            current = _Open(index=len(out), at=now)
            walk(current, entered, range(split, len(entered)), now, edge)
        held = entered[-1]
    if current is not None:
        out.append(_close(current, states, phase, deciding, window_states, complete=False))
    return out


def _bits(mask: int) -> list[int]:
    return [i for i in range(32) if mask >> i & 1]


def _exits(table: rp.Table, s: int) -> list[int]:
    """Where state s can go: its edge rows, its timer, a chance state's branches."""
    row = table.states[s]
    out = [e.next for e in table.edges[row.edge_first : row.edge_first + row.edge_count]]
    if row.timer_min != rp.NONE:
        out.append(row.on_timeout)
    if row.is_chance:
        out += [row.on_hit, row.on_miss]
    return out


def _deciding(table: rp.Table) -> frozenset[int]:
    """The states with two or more exits (edge rows and timer) that can reach an
    outcome-bearing state before the next trial starts: where a trial's outcome
    is decided by what the animal does."""
    states = table.states
    # Every state that can reach an outcome-bearing one without starting a
    # trial: those states, then a fixed point back through their exits.
    reaches = {s for s, row in enumerate(states) if row.outcome}
    grew = True
    while grew:
        grew = False
        for s, row in enumerate(states):
            if s not in reaches and not row.flags & rp.STARTS_TRIAL \
                    and any(t in reaches for t in _exits(table, s)):
                reaches.add(s)
                grew = True

    out = set()
    for s, row in enumerate(states):
        if row.is_chance:
            continue
        exits = [e.next for e in table.edges[row.edge_first : row.edge_first + row.edge_count]]
        if row.timer_min != rp.NONE:
            exits.append(row.on_timeout)
        if sum(1 for t in exits if t in reaches) >= 2:
            out.add(s)
    return frozenset(out)


def _taken(table: rp.Table, held: int, a: rp.Actions, target: int) -> rp.EdgeRow | None:
    """The input edge row that moved `held` to `target` this tick, or None for
    its timer (or a pick's branch, which no input takes).

    The interpreter takes an edge whenever one of the state's edge rows matches,
    and the row it took is one whose `next` is where it went.
    """
    s = table.states[held]
    for e in table.edges[s.edge_first : s.edge_first + s.edge_count]:
        if e.edge not in (rp.RISE, rp.FALL):
            continue
        mask = a.rose if e.edge == rp.RISE else a.fell
        if mask >> e.input & 1 and e.next == target:
            return e
    return None


def _close(t: _Open, states: Sequence[rp.StateRow], phase, deciding: frozenset[int],  # noqa: ANN001
           window_states: frozenset[int] | None, *, complete: bool) -> Trial:
    entries: dict[int, int] = {}
    for s, tick, _, _ in t.path:
        entries.setdefault(s, tick)
    marked = [k for k, (s, *_rest) in enumerate(t.path) if states[s].outcome]
    outcome = states[t.path[marked[-1]][0]].outcome if marked else 0

    response = response_at = latency = None
    if window_states is not None:
        opened = next((tick for s, tick, _, _ in t.path if s in window_states), None)
        for _, tick, left, edge in t.path:
            if edge is not None and left in window_states:
                response, response_at = (edge.input, edge.edge), tick
                latency = tick - opened if opened is not None else None
                break
    elif marked:
        decided = [k for k in range(marked[0] + 1)
                   if t.path[k][3] is not None and t.path[k][2] in deciding]
        if decided:
            window = phase(t.path[decided[-1]][2])
            # Back through the visit to that phase: its first edge exit is the response.
            k = first = decided[-1]
            while k >= 0 and t.path[k][2] is not None and phase(t.path[k][2]) == window:
                if t.path[k][3] is not None:
                    first = k
                k -= 1
            _, response_at, _, edge = t.path[first]
            assert edge is not None
            response = (edge.input, edge.edge)
            opened = t.path[k][1] if k >= 0 else t.at
            latency = response_at - opened
    return Trial(
        index=t.index,
        at=t.at,
        entries=entries,
        outcome=outcome,
        outcome_at=t.path[marked[-1]][1] if marked else None,
        response=response,
        response_at=response_at,
        latency=latency,
        rewarded=t.reward_state is not None,
        reward_outputs=t.reward_outputs,
        reward_ms=t.reward_ms,
        counts=dict(t.counts),
        complete=complete,
    )


# --- the row the wire carries ---------------------------------------------------


@dataclass(frozen=True)
class InputCount:
    """Watched rises of one input channel during one phase of a trial."""

    phase: int
    channel: str
    count: int

    def to_json(self) -> dict[str, object]:
        return {"phase": self.phase, "channel": self.channel, "count": self.count}


@dataclass(frozen=True)
class ConditionScore:
    """A legacy trial's verdict under one condition its onset opens."""

    condition: str
    #: A hit, a miss, or None for excluded.
    correct: bool | None

    def to_json(self) -> dict[str, object]:
        return {"condition": self.condition, "correct": self.correct}


@dataclass(frozen=True)
class Naming:
    """What a snapshot says the table's numbers are, for `name`.

    `inputs[i]` and `outputs[j]` are bit i's and bit j's channel names.
    `phase_of[s]` is state s's phase index (None for a state in no phase, a
    pick), with `phases` the spine's phase count; `phase_of` is None when the
    snapshot cannot say. `row_of[s]` is the row id a
    state belongs to, and `row` the run's only row, when it has one.
    """

    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    phase_of: tuple[int | None, ...] | None = None
    phases: int = 0
    row_of: tuple[str | None, ...] | None = None
    #: The Response window phases, when `phase_of` is known.
    windows: frozenset[int] | None = None
    row: str | None = None
    rows: dict[str, tuple[str, float | None]] = field(default_factory=dict)
    block: str | None = None

    def row_at(self, state: int) -> str | None:
        """The row state `state` belongs to: the snapshot's map, or the run's
        only row; None for a state of no row (a pick, a shared end)."""
        if self.row_of is None:
            return self.row
        return self.row_of[state] if state < len(self.row_of) else None


@dataclass(frozen=True)
class ReplayTrial:
    """One row of the trial table (`ANALYTICS.md#the-trial-table`): a replayed
    spine run's, named, and a decoded legacy run's alike
    (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`). Every value is plain
    (numbers, strings, booleans, None, and lists of them or of flat objects), so a
    row serialises as is."""

    index: int
    #: None only on a legacy file with no usable clock.
    at_ms: int | None
    block: str | None = None
    row: str | None = None
    row_name: str | None = None
    level: float | None = None
    phase_entries: tuple[int | None, ...] = ()
    response: str | None = None
    response_edge: str | None = None
    response_ms: int | None = None
    latency_ms: int | None = None
    outcome: str | None = None
    #: When the outcome was settled: the tick its class was read from, or a
    #: legacy run's outcome strobe.
    outcome_ms: int | None = None
    #: Right, wrong, or not scored (None): `outcome` in `HITS` on a spine run,
    #: the hit or miss of its condition on a legacy one.
    correct: bool | None = None
    rewarded: bool = False
    reward_line: str | None = None
    reward_ms: int | None = None
    #: None when the run cannot say, as a legacy run cannot.
    correction: bool | None = False
    input_counts: tuple[InputCount, ...] = ()
    complete: bool = True
    #: The trial opens a presentation on the engagement ladder.
    presented: bool = True
    #: A legacy trial's verdict under every condition its onset opens: one,
    #: unless a profile declares two conditions on one onset. Empty on a spine run.
    scores: tuple[ConditionScore, ...] = ()

    def scored(self, condition: str) -> bool:
        """The trial was scored under `condition`: its onset opens it."""
        return any(s.condition == condition for s in self.scores)

    def verdict(self, condition: str) -> bool | None:
        """Its hit or miss under `condition`, or None (excluded, or not scored under it)."""
        return next((s.correct for s in self.scores if s.condition == condition), None)

    def to_json(self) -> dict[str, object]:
        return {
            "index": self.index,
            "atMs": self.at_ms,
            "block": self.block,
            "row": self.row,
            "rowName": self.row_name,
            "level": self.level,
            "phaseEntries": list(self.phase_entries),
            "response": self.response,
            "responseEdge": self.response_edge,
            "responseMs": self.response_ms,
            "latencyMs": self.latency_ms,
            "outcome": self.outcome,
            "outcomeMs": self.outcome_ms,
            "correct": self.correct,
            "rewarded": self.rewarded,
            "rewardLine": self.reward_line,
            "rewardMs": self.reward_ms,
            "correction": self.correction,
            "inputCounts": [c.to_json() for c in self.input_counts],
            "complete": self.complete,
            "presented": self.presented,
            "scores": [s.to_json() for s in self.scores],
        }


def class_name(number: int) -> str | None:
    """An outcome class number's name: `taskdef/lowering.py`'s `OUTCOME_CLASSES`, append-only.
    A number this build has no name for is still a class, `outcome_<n>`."""
    if number == 0:
        return None
    if 1 <= number <= len(OUTCOME_CLASSES):
        return OUTCOME_CLASSES[number - 1]
    return f"outcome_{number}"


def class_rank(name: str) -> tuple[int, str]:
    """Order classes by their number, unnamed ones last."""
    if name in OUTCOME_CLASSES:
        return OUTCOME_CLASSES.index(name), name
    return len(OUTCOME_CLASSES), name


def name(trial: Trial, naming: Naming) -> ReplayTrial:
    """`trial` as the wire's row, named by `naming`."""

    def channel(names: tuple[str, ...], bit: int) -> str:
        return names[bit] if bit < len(names) else f"bit {bit}"

    row = next((r for s in trial.entries if (r := naming.row_at(s))), None)
    row_name, level = naming.rows.get(row, (None, None)) if row is not None else (None, None)

    entries: tuple[int | None, ...] = ()
    counts: tuple[InputCount, ...] = ()
    if naming.phase_of is not None:
        first: list[int | None] = [None] * naming.phases
        for s, tick in trial.entries.items():
            p = naming.phase_of[s]
            if p is not None and (first[p] is None or tick < first[p]):  # type: ignore[operator]
                first[p] = tick
        entries = tuple(first)
        by_phase: dict[tuple[int, int], int] = {}
        for (s, bit), n in trial.counts.items():
            p = naming.phase_of[s]
            if p is not None:
                by_phase[(p, bit)] = by_phase.get((p, bit), 0) + n
        counts = tuple(InputCount(p, channel(naming.inputs, bit), n) for (p, bit), n in sorted(by_phase.items()))

    lines = _bits(trial.reward_outputs)
    return ReplayTrial(
        index=trial.index,
        at_ms=trial.at,
        block=naming.block,
        row=row,
        row_name=row_name,
        level=level,
        phase_entries=entries,
        response=channel(naming.inputs, trial.response[0]) if trial.response else None,
        response_edge=("rise" if trial.response[1] == rp.RISE else "fall") if trial.response else None,
        response_ms=trial.response_at,
        latency_ms=trial.latency,
        outcome=class_name(trial.outcome),
        outcome_ms=trial.outcome_at,
        correct=correct_of(class_name(trial.outcome)),
        rewarded=trial.rewarded,
        reward_line=", ".join(channel(naming.outputs, j) for j in lines) if lines else None,
        reward_ms=trial.reward_ms,
        # A block's correction rule is the core's: `stream/spine.py` sets this
        # from what the core reports at the trial's start (`ACT_CORRECTION`).
        correction=False,
        input_counts=counts,
        complete=trial.complete,
    )
