"""A spine run's numbers, every one a function of its trial table
(`ANALYTICS.md#metrics-from-the-trial-table`).

Only complete trials count: a crashed run's last trial may have been cut short
of its outcome. Each proportion carries its 95% Wilson interval
(`ANALYTICS.md#uncertainty`), and none is `0.0` for "no trials".

- **Outcome classes:** for each class, n and n / trials, run-wide and per row
  (P(outcome | row)). Trials that reached no outcome-bearing state are
  `unclassified`, so classes plus unclassified partition the trials.
- **Rewarded:** trials paid / trials.
- **P(correct | row):** as a `MetricSummary`, so a spine run fills every panel
  a legacy run does. Counted trials are the classified ones not in `EXCLUDED`,
  hits those whose class is in `HITS` (a correct response, or a correct
  withhold on a no-go row). The unclassified and the aborted are excluded, as
  an unanswered or aborted trial is on a legacy run
  (`ANALYTICS.md#trials-hits-misses-and-exclusions`).

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...taskdef.lowering import OUTCOME_CLASSES, OUTCOME_CORRECT
from .stats import _round, wilson_interval
from .metric_summary import OVERALL_ID, MetricSummary
from .trial_table import ReplayTrial, class_rank

CORRECT = OUTCOME_CLASSES[OUTCOME_CORRECT - 1]

#: The outcome classes a trial is right in, for P(correct | row) and the pooled
#: figure (`ANALYTICS.md#metrics-from-the-trial-table`). A withhold is a no-go
#: row's correct answer, so a perfect go/no-go session scores 1.0. Every other
#: class (false alarm, wrong response, omission, hold broken, one added later)
#: is a miss, except those in `EXCLUDED`; a trial with no class is excluded too.
HITS = frozenset({CORRECT, "withheld"})

#: The outcome classes left out of P(correct | row), as a legacy run leaves out
#: an aborted trial: the animal quit before it was asked. They stay in the class
#: tallies (P(outcome | row)), just not in `counted` or `hits`.
EXCLUDED = frozenset(name for name in OUTCOME_CLASSES if name in ("abort_before_stimulus", "abort_during_sampling"))


@dataclass(frozen=True)
class Proportion:
    """n of `of`, with its Wilson interval. `p` is None when `of` is 0."""

    n: int
    of: int

    @property
    def p(self) -> float | None:
        return self.n / self.of if self.of else None

    @property
    def interval(self) -> tuple[float, float] | None:
        return wilson_interval(self.n, self.of) if self.of else None

    @property
    def low(self) -> float | None:
        return self.interval[0] if self.interval else None

    @property
    def high(self) -> float | None:
        return self.interval[1] if self.interval else None

    def to_json(self) -> dict[str, object]:
        return {"n": self.n, "of": self.of, "p": _round(self.p),
                "low": _round(self.low), "high": _round(self.high)}


@dataclass(frozen=True)
class ClassTally(Proportion):
    outcome_class: str = ""

    def to_json(self) -> dict[str, object]:
        return {"outcomeClass": self.outcome_class, **super().to_json()}


@dataclass(frozen=True)
class RowTally:
    """P(outcome | row) for one row."""

    row_id: str | None
    name: str | None
    trials: int
    unclassified: int
    classes: tuple[ClassTally, ...]

    def to_json(self) -> dict[str, object]:
        return {"rowId": self.row_id, "name": self.name, "trials": self.trials,
                "unclassified": self.unclassified, "classes": [c.to_json() for c in self.classes]}


@dataclass(frozen=True)
class ReplayScore:
    """A replayed run's tallies (`RunSummary.replay`)."""

    interp: int
    trials: int
    unclassified: int
    classes: tuple[ClassTally, ...]
    rows: tuple[RowTally, ...]
    rewarded: Proportion

    def to_json(self) -> dict[str, object]:
        return {
            "interp": self.interp,
            "trials": self.trials,
            "unclassified": self.unclassified,
            "classes": [c.to_json() for c in self.classes],
            "rows": [r.to_json() for r in self.rows],
            "rewarded": self.rewarded.to_json(),
        }


def _classes(trials: Sequence[ReplayTrial]) -> tuple[ClassTally, ...]:
    counts: dict[str, int] = {}
    for t in trials:
        if t.outcome is not None:
            counts[t.outcome] = counts.get(t.outcome, 0) + 1
    return tuple(ClassTally(n=counts[c], of=len(trials), outcome_class=c)
                 for c in sorted(counts, key=class_rank))


def score(
    table: Sequence[ReplayTrial], *, rows: Sequence[tuple[str, str]], interp: int = 0
) -> ReplayScore:
    """The tallies of `table`. `rows` are the task's (id, name), in its order;
    trials no row claims are tallied under a row of their own, id None."""
    done = [t for t in table if t.complete]
    known = [r for r, _ in rows]
    groups: list[tuple[str | None, str | None]] = list(rows)
    if any(t.row not in known for t in done):
        groups.append((None, None))
    row_tallies = []
    for row_id, row_name in groups:
        own = [t for t in done if (t.row if t.row in known else None) == row_id]
        row_tallies.append(RowTally(row_id=row_id, name=row_name, trials=len(own),
                                    unclassified=sum(1 for t in own if t.outcome is None),
                                    classes=_classes(own)))
    return ReplayScore(
        interp=interp,
        trials=len(done),
        unclassified=sum(1 for t in done if t.outcome is None),
        classes=_classes(done),
        rows=tuple(row_tallies),
        rewarded=Proportion(n=sum(1 for t in done if t.rewarded), of=len(done)),
    )


def _correct(row: RowTally, *, metric_id: str, label: str, min_counted: int) -> MetricSummary:
    hits = sum(c.n for c in row.classes if c.outcome_class in HITS)
    excluded = row.unclassified + sum(c.n for c in row.classes if c.outcome_class in EXCLUDED)
    counted = row.trials - excluded
    interval = wilson_interval(hits, counted) if counted else None
    return MetricSummary(
        id=metric_id,
        label=label,
        p_session=hits / counted if counted else None,
        # No authored window: a spine row has no rolling figure.
        p_window=None,
        hits=hits,
        counted=counted,
        triggered=row.trials,
        excluded=excluded,
        window_size=0,
        wilson_low=interval[0] if interval else None,
        wilson_high=interval[1] if interval else None,
        low_confidence=counted < min_counted,
        answer_side=None,
    )


def correct_metrics(result: ReplayScore, *, min_counted: int = 10) -> list[MetricSummary]:
    """P(correct | row), one per row of the task."""
    return [
        _correct(r, metric_id=f"replay:{r.row_id}:{CORRECT}",
                 label=f"P({CORRECT} | {r.name or r.row_id})", min_counted=min_counted)
        for r in result.rows if r.row_id is not None
    ]


def overall_correct(result: ReplayScore, *, min_counted: int = 10) -> MetricSummary | None:
    """P(correct) pooled over every row, by summing counts; None with no trials."""
    if result.trials == 0:
        return None
    pooled = RowTally(row_id=None, name=None, trials=result.trials,
                      unclassified=result.unclassified, classes=result.classes)
    return _correct(pooled, metric_id=OVERALL_ID, label="Overall accuracy", min_counted=min_counted)
