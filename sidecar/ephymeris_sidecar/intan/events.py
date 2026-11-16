"""Named events on the recording's clock, and PSTHs around them
(`RECORDING.md#event-psth`). Pure: inputs in, numbers out.

A run's strobes say WHAT happened on the Arduino's clock; its sync edges, in
RHX's digital input, say WHEN on the recording's. `align` pairs them with the
same `EdgeMatcher` the live sync check ran, fed the complete record. Each
event can then be placed in its trial, and spikes binned around it.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import copysign, sqrt
from statistics import mean, stdev
from typing import Iterable, Sequence

from .analysis import EdgeMatcher

#: Edges held ahead of the strobes once anchored: a live stream's look-ahead.
#: Before the anchor, up to `EdgeMatcher.MAX_PENDING`, so any number of reset
#: twitches ahead of START can be skipped.
LOOK_AHEAD = 8
#: A site is responsive when its post-event rate differs from its pre-event
#: rate by at least this many standard errors, over at least `MIN_TRIALS`.
RESPONSIVE_T = 3.0
MIN_TRIALS = 5
#: |t| reported for a change with no spread at all: every trial moved alike.
#: Finite, so it crosses the wire (JSON has no infinity).
MAX_T = 99.9


@dataclass(frozen=True)
class AlignedEvent:
    code: int
    ms: int
    #: On the recording's clock; None when its pulse never came.
    sample: int | None


@dataclass(frozen=True)
class Alignment:
    events: tuple[AlignedEvent, ...]
    matched: int
    missed: int
    stray: int


def align(strobes: Sequence[tuple[int, int]], edges: Sequence[int], rate: float, *, tick_pulsed: bool) -> Alignment:
    """Every strobe of a run placed on the recording's clock, or not.

    Fed as a live stream would be -- a strobe, then edges up to a small
    look-ahead -- because the matcher gives up on the oldest of more than
    `MAX_PENDING` queued items, and a whole session at once would be that.
    """
    matcher = EdgeMatcher(rate, tick_pulsed=tick_pulsed)
    out: list = []
    taken = 0

    def top_up() -> None:
        nonlocal taken
        limit = LOOK_AHEAD if matcher.anchored else EdgeMatcher.MAX_PENDING - 1
        while taken < len(edges) and matcher.pending_edges < limit:
            out.extend(matcher.add_edges([edges[taken]]))
            taken += 1

    for code, ms in strobes:
        out.extend(matcher.add_strobe(code, ms))
        top_up()
    out.extend(matcher.flush())
    events = tuple(AlignedEvent(e.code, e.ms, e.sample) for e in out)
    return Alignment(
        events=events,
        matched=sum(1 for e in events if e.sample is not None),
        missed=matcher.unmatched_strobes,
        stray=matcher.spurious_edges,
    )


@dataclass(frozen=True)
class TrialStart:
    ms: int
    condition: str | None
    outcome: str | None


def trial_of(starts: Sequence[TrialStart], ms: int) -> int | None:
    """Which trial an event at `ms` falls in: the last that opened at or
    before it. None before the first. `starts` sorted by `ms`."""
    index = bisect_right([s.ms for s in starts], ms) - 1
    return index if index >= 0 else None


def psth_counts(spikes: Sequence[int], triggers: Iterable[int], pre: int, post: int, bin_: int) -> list[int]:
    """Spikes in each bin from `-pre` to `+post` samples around every trigger,
    summed over triggers. `spikes` sorted."""
    bins = max(1, (pre + post) // bin_)
    counts = [0] * bins
    for t in triggers:
        lo = bisect_left(spikes, t - pre)
        hi = bisect_left(spikes, t + post)
        for s in spikes[lo:hi]:
            k = (s - (t - pre)) // bin_
            if 0 <= k < bins:
                counts[k] += 1
    return counts


def raster(spikes: Sequence[int], triggers: Iterable[int], pre: int, post: int, per_ms: float) -> list[list[float]]:
    """Each trigger's spikes, in ms from it."""
    rows = []
    for t in triggers:
        lo = bisect_left(spikes, t - pre)
        hi = bisect_left(spikes, t + post)
        rows.append([round((s - t) / per_ms, 2) for s in spikes[lo:hi]])
    return rows


@dataclass(frozen=True)
class Responsiveness:
    #: Mean of (post rate - pre rate) over trials, in Hz.
    delta_hz: float
    #: That mean over its standard error; None under `MIN_TRIALS` or with no spread.
    t: float | None

    @property
    def verdict(self) -> str:
        if self.t is None or abs(self.t) < RESPONSIVE_T:
            return "none"
        return "up" if self.t > 0 else "down"


def responsiveness(spikes: Sequence[int], triggers: Sequence[int], window: int, rate: float) -> Responsiveness:
    """The paired change in rate from the `window` samples before each trigger
    to the `window` after it. A first look, not a test of significance: the
    same site judged at many events will find some by chance."""
    seconds = window / rate
    diffs = []
    for t in triggers:
        before = bisect_left(spikes, t) - bisect_left(spikes, t - window)
        after = bisect_left(spikes, t + window) - bisect_left(spikes, t)
        diffs.append((after - before) / seconds)
    if len(diffs) < MIN_TRIALS:
        return Responsiveness(mean(diffs) if diffs else 0.0, None)
    average, spread = mean(diffs), stdev(diffs)
    if spread == 0:
        # Every trial moved by the same amount: as consistent as it gets.
        return Responsiveness(average, None if average == 0 else copysign(MAX_T, average))
    return Responsiveness(average, max(-MAX_T, min(MAX_T, average / (spread / sqrt(len(diffs))))))


def whole_windows(triggers: Iterable[int], pre: int, post: int, first: int, last: int) -> list[int]:
    """Only triggers whose whole window lies inside the recording."""
    return [t for t in triggers if t - pre >= first and t + post <= last]
