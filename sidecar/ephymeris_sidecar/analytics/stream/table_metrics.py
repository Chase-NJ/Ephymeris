"""Metrics read off a legacy table (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`):
P(hit) per condition and the pooled figure.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from typing import Sequence

from .legacy.decode import LegacyTable
from .metric_summary import OVERALL_ID, MetricSummary
from .stats import wilson_interval
from .trial_table import CORRECT, EXCLUDED, HITS

#: Re-exported: a row's `correct` is what `trial_table.HITS` and
#: `trial_table.EXCLUDED` decide.
__all__ = ["CORRECT", "EXCLUDED", "HITS", "legacy_metrics", "legacy_overall", "verdicts"]


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
