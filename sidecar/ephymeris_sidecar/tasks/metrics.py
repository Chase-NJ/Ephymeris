"""Live metric computation — `data-saving.md` §6.5.

This is the actual scientific output, not a UI detail, so the definition is
followed to the letter:

For each occurrence of `triggerCode`, scan forward for the *next* occurrence of
`successCode` or `alternateCode`, stopping at the next trial boundary — whichever
comes first:

* `successCode` first  → **hit**  (counts toward numerator and denominator)
* `alternateCode` first → **miss** (counts toward the denominator — "went to the
  other side", not "failed to respond")
* neither before the scan stops → **excluded** from both (a lazy / invalid /
  no-response trial)

Response-conditional (excludes true non-responses) but reward-unconditional (a
detected poke counts even if a later hold check would have failed — the firmware
fires `WATER_POKE_L/R` the instant a poke is detected). The rolling window is the
last `windowSize` **counted** (hit-or-miss) trials, not the last `windowSize`
strobe events.

The accumulator is incremental so the live runner feeds it one strobe at a time
(`starting-a-session.md` §7 step 7); `compute_series` replays a whole stream for
testing and for building the final file's metric view.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Iterable

from .profile import LiveMetric, TaskProfile


@dataclass(frozen=True)
class MetricValue:
    id: str
    value: float | None  # P(hit) over the window; None until a trial counts
    n: int  # counted trials in the window

    def to_json(self) -> dict[str, object]:
        return {"id": self.id, "value": self.value, "n": self.n}


class MetricAccumulator:
    """Rolling P(hit) for one `liveMetrics` entry.

    `boundary_codes` are the trial-start markers whose arrival mid-scan means the
    current trial ended without a scored response. §6.5 phrases this as "the next
    occurrence of `triggerCode` (or any other recognized trial-boundary code)";
    in practice every metric's `triggerCode` (each odor onset) is a boundary, so
    the runner passes the union of all trigger codes in the profile.
    """

    def __init__(self, metric: LiveMetric, boundary_codes: frozenset[int]) -> None:
        self._metric = metric
        self._boundaries = boundary_codes | {metric.trigger_code}
        self._window: deque[bool] = deque(maxlen=metric.window_size)
        self._pending = False
        #: Total counted (hit-or-miss) trials ever, monotonic. The window length
        #: caps at `windowSize`, so this is what distinguishes "a new trial
        #: landed" from "the window is just full".
        self._counted = 0

    @property
    def id(self) -> str:
        return self._metric.id

    @property
    def counted_total(self) -> int:
        return self._counted

    def _record(self, outcome: bool) -> None:
        self._window.append(outcome)
        self._counted += 1
        self._pending = False

    def offer(self, code: int) -> None:
        """Feed one strobe code."""
        if self._pending:
            if code == self._metric.success_code:
                self._record(True)
                return
            if code == self._metric.alternate_code:
                self._record(False)
                return
            if code in self._boundaries:
                # A new trial started before this one resolved — excluded.
                self._pending = False
                # fall through: this same code may itself begin the next trial

        if code == self._metric.trigger_code:
            self._pending = True

    def value(self) -> MetricValue:
        n = len(self._window)
        if n == 0:
            return MetricValue(id=self._metric.id, value=None, n=0)
        hits = sum(1 for outcome in self._window if outcome)
        return MetricValue(id=self._metric.id, value=hits / n, n=n)


class MetricSet:
    """All of a sketch's live metrics, fed together from its strobe stream."""

    def __init__(self, profile: TaskProfile | None) -> None:
        metrics = profile.live_metrics if profile else []
        boundaries = frozenset(m.trigger_code for m in metrics)
        self._accumulators = [MetricAccumulator(m, boundaries) for m in metrics]

    @property
    def empty(self) -> bool:
        return not self._accumulators

    def offer(self, code: int) -> list[MetricValue]:
        """Feed one strobe; return the current value of every metric.

        Returns all metrics rather than only the changed one — the frontend
        replaces its whole per-box metric set per telemetry push, and the set is
        tiny (two charts for GRGL).
        """
        for acc in self._accumulators:
            acc.offer(code)
        return [acc.value() for acc in self._accumulators]

    def values(self) -> list[MetricValue]:
        return [acc.value() for acc in self._accumulators]


def compute_series(
    metric: LiveMetric, stream: Iterable[int], boundary_codes: frozenset[int] | None = None
) -> list[float]:
    """Replay a whole stream, returning P(hit) *after each counted trial*.

    The last element is the final rolling value. Used in tests and for building
    the finished file's metric view.
    """
    boundaries = boundary_codes if boundary_codes is not None else frozenset({metric.trigger_code})
    acc = MetricAccumulator(metric, boundaries)
    series: list[float] = []
    previous_counted = 0
    for code in stream:
        acc.offer(code)
        if acc.counted_total != previous_counted:
            previous_counted = acc.counted_total
            value = acc.value().value
            if value is not None:
                series.append(value)
    return series
