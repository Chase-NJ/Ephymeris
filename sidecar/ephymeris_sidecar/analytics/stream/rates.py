"""Phase-window rates, read off the trial table (`ANALYTICS.md#phase-window-rates`).

A **window** is a phase that counts an input it never acts on: its states
watch the input's bit and none of them has an edge row on it. A Pavlovian
task's baseline, CS, trace and US phases watching the lick sensor are windows
(`TASKS.md#pavlovian-conditioning`); a Wait's port, a Response window's wells,
an abort's input and a Counter's lever are acted on, and are not. So which
phases are windows is read off the table's own fields (`windows_of`), never a
phase kind.

For each row of the task and each window:

- **the rate** of each trial: its rises in the window × 1000 / the window's
  span in ticks, events per second. The span runs from the phase's entry to
  the next phase's entry, or to the next trial's start for the trial's last
  phase: exactly the ticks the trial table attributes its rises to;
- **the mean rate** over the row's trials, with its 95% Student-t interval
  over trials, clamped at 0;
- **the paired difference** against the channel's **reference**, its first
  window in the spine (a Pavlovian task's baseline): each trial's rate minus
  its own reference rate, with the same interval.

The trials are those P(correct) counts: complete, with an outcome class that
is not an abort (`EXCLUDED`), and with the window entered and its span known
and above zero.

**Why trials, and why t**: licks come in bursts and their rate moves from
trial to trial far more than a Poisson count does, so a Poisson (Garwood)
interval on pooled counts would be falsely narrow. The trial is the unit, and
the difference is paired within it (`ANALYTICS.md#uncertainty`).

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from . import replay as rp
from .stats import _round, mean_interval
from .trial_table import EXCLUDED, ReplayTrial


@dataclass(frozen=True, order=True)
class Window:
    """A phase that counts an input channel and never acts on it."""

    phase: int
    channel: str


@dataclass(frozen=True)
class RateEstimate:
    """A mean over trials, events per second, with its 95% t interval. `mean`
    is None with no trials; `low` and `high` are None with fewer than two."""

    n: int
    mean: float | None = None
    low: float | None = None
    high: float | None = None

    def to_json(self) -> dict[str, object]:
        return {"n": self.n, "mean": _round(self.mean), "low": _round(self.low), "high": _round(self.high)}


@dataclass(frozen=True)
class WindowRate:
    """One row's rate in one window, and its difference against the reference."""

    row_id: str
    name: str
    phase: int
    #: The phase's kind, for a person: nothing is read from it.
    label: str
    channel: str
    rate: RateEstimate
    #: The reference window's phase; None on the reference itself.
    reference: int | None
    #: This window's rate minus the reference's, paired within each trial.
    versus: RateEstimate | None
    low_confidence: bool

    def to_json(self) -> dict[str, object]:
        return {"rowId": self.row_id, "name": self.name, "phase": self.phase, "label": self.label,
                "channel": self.channel, "rate": self.rate.to_json(), "reference": self.reference,
                "versus": self.versus.to_json() if self.versus else None,
                "lowConfidence": self.low_confidence}


def windows_of(table: rp.Table, phase_of: Sequence[int | None], inputs: Sequence[str]) -> tuple[Window, ...]:
    """The windows of a table: each (phase, channel) whose bit some state of
    the phase watches and no state of the phase has an edge row on.
    `phase_of[s]` is state s's phase, `inputs[i]` input bit i's channel."""
    watched: dict[int, int] = {}
    acted: dict[int, int] = {}
    for s, row in enumerate(table.states):
        p = phase_of[s] if s < len(phase_of) else None
        if p is None:
            continue
        watched[p] = watched.get(p, 0) | row.watch
        for e in table.edges[row.edge_first : row.edge_first + row.edge_count]:
            acted[p] = acted.get(p, 0) | 1 << e.input
    out = {Window(p, inputs[bit] if bit < len(inputs) else f"bit {bit}")
           for p, mask in watched.items() for bit in range(32)
           if (mask & ~acted.get(p, 0)) >> bit & 1}
    return tuple(sorted(out))


def _rates(table: Sequence[ReplayTrial], windows: Sequence[Window]) -> list[dict[Window, float]]:
    """Each counted trial's rate in each window it has a span for, by trial."""
    out = []
    for k, t in enumerate(table):
        if not t.complete or t.outcome is None or t.outcome in EXCLUDED:
            out.append({})
            continue
        following = table[k + 1].at_ms if k + 1 < len(table) and table[k + 1].index == t.index + 1 else None
        counts = {(c.phase, c.channel): c.count for c in t.input_counts}
        mine: dict[Window, float] = {}
        for w in windows:
            entries = t.phase_entries
            if w.phase >= len(entries) or entries[w.phase] is None:
                continue
            start = entries[w.phase]
            end = next((e for e in entries[w.phase + 1 :] if e is not None), following)
            if end is None or end <= start:  # type: ignore[operator]
                continue
            mine[w] = counts.get((w.phase, w.channel), 0) * 1000 / (end - start)  # type: ignore[operator]
        out.append(mine)
    return out


def _estimate(values: list[float], *, floor: float | None = None) -> RateEstimate:
    found = mean_interval(values)
    if found is None:
        return RateEstimate(n=0)
    mean, low, high = found
    if floor is not None and low is not None:
        low = max(floor, low)
    return RateEstimate(n=len(values), mean=mean, low=low, high=high)


def window_rates(
    table: Sequence[ReplayTrial],
    windows: Sequence[Window],
    *,
    rows: Sequence[tuple[str, str]],
    labels: Sequence[str] = (),
    min_counted: int = 10,
) -> tuple[WindowRate, ...]:
    """Every row's rate in every window, row by row in the task's order, then
    by phase. `rows` are the task's (id, name); `labels` the phases' kinds."""
    windows = sorted(set(windows))
    reference: dict[str, int] = {}
    for w in windows:
        reference.setdefault(w.channel, w.phase)
    per_trial = _rates(table, windows)
    out = []
    for row_id, row_name in rows:
        own = [r for t, r in zip(table, per_trial) if t.row == row_id]
        for w in windows:
            rate = _estimate([r[w] for r in own if w in r], floor=0.0)
            ref = Window(reference[w.channel], w.channel)
            versus = None
            if ref != w:
                versus = _estimate([r[w] - r[ref] for r in own if w in r and ref in r])
            out.append(WindowRate(
                row_id=row_id, name=row_name, phase=w.phase,
                label=labels[w.phase] if w.phase < len(labels) else f"phase {w.phase}",
                channel=w.channel, rate=rate, reference=ref.phase if ref != w else None,
                versus=versus, low_confidence=rate.n < min_counted,
            ))
    return tuple(out)
