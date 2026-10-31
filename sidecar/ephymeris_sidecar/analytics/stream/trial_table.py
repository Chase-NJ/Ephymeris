"""A spine run's trial table, read off its replay (`ANALYTICS.md#how-a-spine-run-is-scored`).

One row per trial. Every column is read from the state table's own fields, never
from a phase kind or a code name, so a phase or an outcome class added later is
scored with no change here:

- a trial starts at each tick whose actions carry `ACT_TRIAL_START`, which is
  where a state flagged `STARTS_TRIAL` is entered;
- its **outcome class** is the `outcome` of the last outcome-bearing state it
  entered (0 when it entered none, as an abort to the ITI does);
- it is **rewarded** when it took the `on_hit` branch of a chance state that
  bears an outcome. The reward line is the outputs `on_hit` drives and
  `on_miss` does not, and the reward time is the ticks actually spent in it;
- its **response** is read through the phase map. P is the phase of the state
  the trial was in when it first entered an outcome-bearing state; the response
  is the first edge exit taken out of a state of phase P, and its latency runs
  from the trial's first entry into P. A window and the hold after it are one
  phase, so a held response is timed from the window, not from the hold's end.
  Without a phase map every state is its own phase, which reduces to "the edge
  into the first outcome-bearing state";
- an input's **count** is its watched rises, attributed to the state held before
  the tick, as the interpreter attributes them.

`trials_of` works in states, ticks and bits; `name` turns one trial into the
row the wire carries, through the snapshot's `Naming`.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from ...taskdef.lowering import OUTCOME_CLASSES
from . import replay as rp


@dataclass(frozen=True)
class Trial:
    """One trial in table terms: states, ticks and bits."""

    index: int
    at: int
    #: First entry tick of each state the trial entered.
    entries: dict[int, int]
    outcome: int = 0
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
    #: (state entered, tick, the state held before that tick, the edge row that took it there)
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
    phase_of: Sequence[int] | None = None,
) -> list[Trial]:
    """Every trial of a replay, in order.

    `actions` are `replay.replay`'s, through the session's last tick. `end` is
    the tick the session ended at (its trial start opens no trial), or None for
    a run cut off before it ended, whose last trial is then incomplete.
    """
    states = table.states
    phase = (lambda s: phase_of[s]) if phase_of is not None else (lambda s: s)
    out: list[Trial] = []
    current: _Open | None = None
    held: int | None = None  # the state held before this tick

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
        if a.flags & rp.ACT_TRIAL_START:
            if current is not None:
                out.append(_close(current, states, phase, complete=True))
                current = None
            if end is not None and now == end:
                return out
            current = _Open(index=len(out), at=now)
        edge = _taken(table, held, a, entered[0]) if held is not None else None
        before = held
        for hop, s in enumerate(entered):
            if current is not None:
                current.path.append((s, now, before, edge if hop == 0 else None))
                row = states[s]
                if row.is_chance and row.outcome and hop + 1 < len(entered) and entered[hop + 1] == row.on_hit:
                    current.reward_state = row.on_hit
                    current.reward_at = now
                    miss = states[row.on_miss].outputs if row.on_miss != rp.NONE else 0
                    current.reward_outputs = states[row.on_hit].outputs & ~miss
            before = s
        held = entered[-1]
    if current is not None:
        out.append(_close(current, states, phase, complete=False))
    return out


def _bits(mask: int) -> list[int]:
    return [i for i in range(32) if mask >> i & 1]


def _taken(table: rp.Table, held: int, a: rp.Actions, target: int) -> rp.EdgeRow | None:
    """The edge row that moved `held` to `target` this tick, or None for its timer.

    The interpreter takes an edge whenever one of the state's edge rows matches,
    and the row it took is one whose `next` is where it went.
    """
    s = table.states[held]
    for e in table.edges[s.edge_first : s.edge_first + s.edge_count]:
        mask = a.rose if e.edge == rp.RISE else a.fell
        if mask >> e.input & 1 and e.next == target:
            return e
    return None


def _close(t: _Open, states: Sequence[rp.StateRow], phase, *, complete: bool) -> Trial:  # noqa: ANN001
    entries: dict[int, int] = {}
    for s, tick, _, _ in t.path:
        entries.setdefault(s, tick)
    marked = [k for k, (s, *_rest) in enumerate(t.path) if states[s].outcome]
    outcome = states[t.path[marked[-1]][0]].outcome if marked else 0

    response = response_at = latency = None
    if marked:
        _, _, before, _ = t.path[marked[0]]
        if before is not None:
            window = phase(before)
            opened = next((tick for s, tick, _, _ in t.path if phase(s) == window), None)
            for s, tick, left, edge in t.path[: marked[0] + 1]:
                if edge is not None and left is not None and phase(left) == window:
                    response, response_at = (edge.input, edge.edge), tick
                    latency = tick - opened if opened is not None else None
                    break
    return Trial(
        index=t.index,
        at=t.at,
        entries=entries,
        outcome=outcome,
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
class Naming:
    """What a snapshot says the table's numbers are, for `name`.

    `inputs[i]` and `outputs[j]` are bit i's and bit j's channel names.
    `phase_of[s]` is state s's phase index, with `phases` the spine's phase
    count, or None when the snapshot cannot say. `row_of[s]` is the row id a
    state belongs to, and `row` the run's only row, when it has one.
    """

    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    phase_of: tuple[int, ...] | None = None
    phases: int = 0
    row_of: tuple[str | None, ...] | None = None
    row: str | None = None
    rows: dict[str, tuple[str, float | None]] = field(default_factory=dict)
    block: str | None = None


@dataclass(frozen=True)
class ReplayTrial:
    """One row of the trial table, named (`ANALYTICS.md#the-trial-table`)."""

    index: int
    at_ms: int
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
    rewarded: bool = False
    reward_line: str | None = None
    reward_ms: int | None = None
    correction: bool = False
    input_counts: tuple[InputCount, ...] = ()
    complete: bool = True

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
            "rewarded": self.rewarded,
            "rewardLine": self.reward_line,
            "rewardMs": self.reward_ms,
            "correction": self.correction,
            "inputCounts": [c.to_json() for c in self.input_counts],
            "complete": self.complete,
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

    row = naming.row
    if naming.row_of is not None:
        tagged = [naming.row_of[s] for s in trial.entries if s < len(naming.row_of) and naming.row_of[s]]
        row = tagged[0] if tagged else None
    row_name, level = naming.rows.get(row, (None, None)) if row is not None else (None, None)

    entries: tuple[int | None, ...] = ()
    counts: tuple[InputCount, ...] = ()
    if naming.phase_of is not None:
        first: list[int | None] = [None] * naming.phases
        for s, tick in trial.entries.items():
            p = naming.phase_of[s]
            if first[p] is None or tick < first[p]:  # type: ignore[operator]
                first[p] = tick
        entries = tuple(first)
        by_phase: dict[tuple[int, int], int] = {}
        for (s, bit), n in trial.counts.items():
            key = (naming.phase_of[s], bit)
            by_phase[key] = by_phase.get(key, 0) + n
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
        rewarded=trial.rewarded,
        reward_line=", ".join(channel(naming.outputs, j) for j in lines) if lines else None,
        reward_ms=trial.reward_ms,
        # No block has a correction rule yet (#103): no trial is a correction.
        correction=False,
        input_counts=counts,
        complete=trial.complete,
    )
