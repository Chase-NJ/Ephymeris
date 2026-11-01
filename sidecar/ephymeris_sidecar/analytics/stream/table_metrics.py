"""A run's numbers, every one a function of its trial table
(`ANALYTICS.md#metrics-from-the-trial-table`): a replayed spine run's, and a
decoded legacy run's P(hit) per condition (`legacy_metrics`, `legacy_overall`,
`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

On a spine run, only complete trials count: a crashed run's last trial may have been cut short
of its outcome. Each proportion carries its 95% Wilson interval
(`ANALYTICS.md#uncertainty`), and none is `0.0` for "no trials".

- **Outcome classes:** for each class, n and n / trials, run-wide and per row
  (P(outcome | row)). Trials that reached no outcome-bearing state are
  `unclassified`, so classes plus unclassified partition the trials.
- **Rewarded:** trials paid / trials.
- **P(correct | row):** as a `MetricSummary`, so a spine run fills every panel
  a legacy run does. It reads each row's `correct`: hits are the trials whose
  class is in `HITS` (a correct response, or a correct withhold on a no-go
  row); the unclassified and the aborts (`EXCLUDED`) are excluded, as an
  unanswered or abandoned trial is on a legacy run
  (`ANALYTICS.md#trials-hits-misses-and-exclusions`).

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .stats import _round, wilson_interval
from .metric_summary import OVERALL_ID, MetricSummary
from .legacy.decode import LegacyTable
from .trial_table import CORRECT, EXCLUDED, HITS, ReplayTrial, class_rank

#: Re-exported: P(correct | row) reads the rows' `correct`, which
#: `trial_table.HITS` and `trial_table.EXCLUDED` decide.
__all__ = ["CORRECT", "EXCLUDED", "HITS", "ReplayScore", "correct_metrics", "legacy_metrics", "legacy_overall",
           "overall_correct", "score", "verdicts"]


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
    #: Its trials whose `correct` is true, and those it is not None for.
    hits: int = 0
    counted: int = 0

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
    #: Trials whose `correct` is true, and those it is not None for.
    hits: int = 0
    counted: int = 0

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
                                    classes=_classes(own),
                                    hits=sum(1 for t in own if t.correct),
                                    counted=sum(1 for t in own if t.correct is not None)))
    return ReplayScore(
        interp=interp,
        trials=len(done),
        unclassified=sum(1 for t in done if t.outcome is None),
        classes=_classes(done),
        rows=tuple(row_tallies),
        rewarded=Proportion(n=sum(1 for t in done if t.rewarded), of=len(done)),
        hits=sum(1 for t in done if t.correct),
        counted=sum(1 for t in done if t.correct is not None),
    )


def _correct(row: RowTally, *, metric_id: str, label: str, min_counted: int) -> MetricSummary:
    hits, counted = row.hits, row.counted
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
        excluded=row.trials - counted,
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
                      unclassified=result.unclassified, classes=result.classes, hits=result.hits,
                      counted=result.counted)
    return _correct(pooled, metric_id=OVERALL_ID, label="Overall accuracy", min_counted=min_counted)


# --- a legacy table (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`) ---------


def verdicts(table: LegacyTable, condition: str) -> list[bool]:
    """A condition's counted trials, in order: True a hit, False a miss."""
    return [v for t in table.trials if (v := t.verdict(condition)) is not None]


def legacy_metrics(table: LegacyTable, *, min_counted: int = 10) -> list[MetricSummary]:
    """P(hit) per condition, in authored order (`ANALYTICS.md#trials-hits-misses-and-exclusions`).

    `pSession` and `pWindow` are read off one list of verdicts, so they differ
    *only* in averaging window and cannot disagree on how a trial was
    classified (`ANALYTICS.md#two-probabilities-per-metric`).
    """
    out = []
    for c in table.conditions:
        counted_ = verdicts(table, c.id)
        triggered = sum(1 for t in table.trials if t.scored(c.id))
        counted, hits = len(counted_), sum(counted_)
        window = counted_[-c.window:] if c.window > 0 else []
        interval = wilson_interval(hits, counted) if counted else None
        out.append(MetricSummary(
            id=c.id,
            label=c.label,
            p_session=hits / counted if counted else None,
            p_window=sum(window) / len(window) if window else None,
            hits=hits,
            counted=counted,
            triggered=triggered,
            # Trials where neither response arrived before the next boundary —
            # lazy, invalid, or no-response. Meaningful in its own right: 200
            # triggers with 90 counted is a very different session from 200 with
            # 195, at identical P(correct).
            excluded=max(0, triggered - counted),
            window_size=c.window,
            wilson_low=interval[0] if interval else None,
            wilson_high=interval[1] if interval else None,
            low_confidence=counted < min_counted,
            answer_side=c.answer_side,
        ))
    return out


def legacy_overall(metrics: Sequence[MetricSummary], *, min_counted: int = 10) -> MetricSummary | None:
    """Accuracy pooled across every condition — correct trials over scored trials
    (`ANALYTICS.md#pooled-accuracy`).

    Why this exists, and why it is every per-run readout's default: **a single
    metric cannot show a side bias.** An animal that pokes right on every trial
    scores ~1.0 on "P(R | Odor 1)" and ~0.0 on "P(L | Odor 3)", so a readout
    keyed on the first metric alone paints a completely bias-locked animal as one of the
    best in the cohort. Pooling puts it at chance, which is the truth.

    Pooled by summing hits and trials rather than averaging the two
    proportions, so a session that scored 90 odor-1 trials and 10 odor-3 trials
    is weighted the way it actually happened.

    **The rate pools only conditions that scored; the trial counts pool all of
    them.** A condition that fired twenty times and was never answered
    contributes nothing to P, but those twenty trials are exactly what
    `triggered` and `excluded` exist to report. Counting all of them keeps
    `triggered == counted + excluded` true of the pooled row. None when no
    condition counted a trial.
    """
    scored = [m for m in metrics if m.p_session is not None and m.counted > 0]
    if not scored:
        return None
    counted = sum(m.counted for m in scored)
    hits = sum(m.hits for m in scored)
    interval = wilson_interval(hits, counted)
    return MetricSummary(
        id=OVERALL_ID,
        label="Overall accuracy",
        p_session=hits / counted,
        p_window=None,
        hits=hits,
        counted=counted,
        triggered=sum(m.triggered for m in metrics),
        excluded=sum(m.excluded for m in metrics),
        window_size=0,
        wilson_low=interval[0] if interval else None,
        wilson_high=interval[1] if interval else None,
        low_confidence=counted < min_counted,
        # The pooled figure spans every condition, so it is not answered at any
        # one side and has no axis. Its own kind of null, not a missing one.
        answer_side=None,
    )
