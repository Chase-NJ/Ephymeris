"""One run, scored — `ANALYTICS.md#how-a-strobe-stream-is-scored`.

`summarize(document, profile)` is the whole job, and it is the same for both
kinds of run: read the run into its trial table, then read every number off
the table. A spine run's table comes from its replay
(`ANALYTICS.md#how-a-spine-run-is-scored`); a legacy run's from the legacy
decoder (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`), which gives
the per-condition P(hit), the pooled figure, the outcome tally, the
per-condition tally and the engagement ladder, as one `RunSummary`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...tasks.profile import TaskProfile
from .document import _duration_ms, codes_of
from . import legacy, rates, table_metrics
from .spine import Divergence, Replayed, SpineDecodeError, is_spine_run, replayed
from .spine import trial_table as spine_table
from .engagement import TrialEngagement, tally_engagement
from .outcomes import ConditionOutcomes, TrialOutcomes, tally_conditions, tally_outcomes
from .metric_summary import OVERALL_ID, MetricSummary


@dataclass(frozen=True)
class RunSummary:
    """Everything the cohort-scale panels need about one animal's run."""

    status: str  # 'ok' | 'no-metrics' | 'diverged' | 'unreplayable' | 'missing' | 'unreadable'
    metrics: list[MetricSummary] = field(default_factory=list)
    #: Accuracy pooled across every metric — see `_overall`. The honest single
    #: number for a run, and every per-run readout's default.
    overall: MetricSummary | None = None
    #: None when the profile doesn't declare the outcome vocabulary
    #: (`ANALYTICS.md#rewarded-and-response-accuracy`) —
    #: absent rather than zeroed, because "this task has no notion of a reward
    #: delivery" and "this animal earned nothing" are different claims.
    outcomes: TrialOutcomes | None = None
    #: The same tally split per declared condition
    #: (`ANALYTICS.md#per-condition-tally`). Empty — not None —
    #: when `outcomes` is None: there is no separate claim to make about a task
    #: whose vocabulary can't express an outcome at all.
    conditions: list[ConditionOutcomes] = field(default_factory=list)
    #: How many trials the box *offered*, and how far each got
    #: (`ANALYTICS.md#engagement-ladder`). None on
    #: a profile that declares no trial light — same rule as `outcomes`, and for
    #: the same reason: a zeroed ladder would read as an animal that never
    #: engaged rather than as a task that can't say.
    engagement: TrialEngagement | None = None
    total_events: int = 0
    duration_ms: int | None = None
    stop_reason: str | None = None
    clean: bool = False
    seed: int | None = None
    detail: str | None = None
    #: A `kind: "utility"` profile is scored if it declares metrics, but left
    #: out of cohort aggregates unless asked for (`ANALYTICS.md#edge-cases`).
    excluded_by_default: bool = False
    #: A spine run's tallies from its trial table, when replay scored it
    #: (`ANALYTICS.md#metrics-from-the-trial-table`). None for every other run.
    replay: table_metrics.ReplayScore | None = None
    #: Where a `diverged` run's strobes leave what replay predicts.
    divergence: Divergence | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metrics": [m.to_json() for m in self.metrics],
            "overall": self.overall.to_json() if self.overall else None,
            "outcomes": self.outcomes.to_json() if self.outcomes else None,
            "conditions": [c.to_json() for c in self.conditions],
            "engagement": self.engagement.to_json() if self.engagement else None,
            "totalEvents": self.total_events,
            "durationMs": self.duration_ms,
            "stopReason": self.stop_reason,
            "clean": self.clean,
            "seed": self.seed,
            "detail": self.detail,
            "excludedByDefault": self.excluded_by_default,
            "replay": self.replay.to_json() if self.replay else None,
            "divergence": self.divergence.to_json() if self.divergence else None,
        }


#: The clean-end reason, matching `sessions/runner.py`'s literal exactly.
CLEAN_STOP_REASON = "BF_END_SESSION received"


#: Below this many counted trials a value is flagged rather than trusted. The
#: sidecar never suppresses — it reports the number, the count, the interval
#: and this flag, and presentation decides what to do
#: (`ANALYTICS.md#uncertainty`).
DEFAULT_MIN_COUNTED = 10


def summarize(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    min_counted: int = DEFAULT_MIN_COUNTED,
) -> RunSummary:
    """Score one recorded run (`ANALYTICS.md#how-a-strobe-stream-is-scored`)."""
    codes = codes_of(document)
    stop_reason = document.get("stop_reason")
    stop_reason = stop_reason if isinstance(stop_reason, str) else None

    duration = _duration_ms(document)
    seed = document.get("trial_seed")
    seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None

    base = {
        "total_events": len(codes),
        "duration_ms": duration,
        "stop_reason": stop_reason,
        "clean": stop_reason == CLEAN_STOP_REASON,
        "seed": seed,
    }

    # A spine run is scored by replay and nothing else: never by the legacy
    # scorer, whose onset-shaped names its edge codes would only mimic
    # (`ANALYTICS.md#how-a-spine-run-is-scored`).
    if is_spine_run(document):
        return _replay_summary(document, base, min_counted)

    # A sketch with no Task Profile is fully supported (`ANALYTICS.md#edge-cases`)
    # and still worth listing — it has a real duration, event count and stop
    # reason. Inventing a default metric for it would be worse than saying so.
    if profile is None or not profile.live_metrics:
        return RunSummary(status="no-metrics", **base)

    table = legacy.table_of(document, profile)
    metrics = table_metrics.legacy_metrics(table, min_counted=min_counted)
    return RunSummary(
        status="ok",
        metrics=metrics,
        overall=table_metrics.legacy_overall(metrics, min_counted=min_counted),
        outcomes=tally_outcomes(table),
        conditions=tally_conditions(table),
        engagement=tally_engagement(table),
        excluded_by_default=profile.kind == "utility",
        **base,
    )


def replay_score(result: Replayed, min_counted: int) -> table_metrics.ReplayScore:
    """A replayed spine run's tallies and rates: the one call Analytics
    (`summarize`) and live scoring (`live.scored`) both make, so they agree."""
    return table_metrics.score(result.trials, rows=result.rows, interp=result.interp,
                               rate_windows=result.rate_windows, labels=result.phases, min_counted=min_counted)


def _replay_summary(document: dict[str, Any], base: dict[str, Any], min_counted: int) -> RunSummary:
    """A spine run: `ok` with its trial-table metrics, `diverged`, or `unreplayable`."""
    try:
        result = replayed(document)
    except SpineDecodeError as exc:
        return RunSummary(status="unreplayable", detail=f"replay cannot run this spine run: {exc}", **base)
    if result.divergence is not None:
        return RunSummary(status="diverged", detail=result.divergence.detail,
                          divergence=result.divergence, **base)
    score = replay_score(result, min_counted)
    return RunSummary(
        status="ok",
        metrics=table_metrics.correct_metrics(score, min_counted=min_counted),
        overall=table_metrics.overall_correct(score, min_counted=min_counted),
        replay=score,
        **base,
    )


def with_threshold(payload: dict[str, Any], min_counted: int) -> dict[str, Any]:
    """A summary payload judged against `min_counted`, as a copy.

    `lowConfidence` is the only part of a summary the threshold touches, and it
    is `counted < min_counted` for each metric and the pooled figure, and
    `rates.low_confidence` for each phase-window rate, which never trusts one
    on fewer than `rates.RATE_MIN_TRIALS` trials. The
    threshold is a per-request argument (`analytics.summary`'s
    `minCountedTrials`) while the payload is cached, so the flag is re-judged on
    every row served rather than kept from whichever request computed it
    (`DATA.md#caching`).
    """
    def judged(metric: Any) -> Any:
        if not isinstance(metric, dict) or not isinstance(metric.get("counted"), int):
            return metric
        return {**metric, "lowConfidence": metric["counted"] < min_counted}

    def judged_rate(window: Any) -> Any:
        rate = window.get("rate") if isinstance(window, dict) else None
        if not isinstance(rate, dict) or not isinstance(rate.get("n"), int):
            return window
        versus = window.get("versus")
        versus_n = versus.get("n") if isinstance(versus, dict) and isinstance(versus.get("n"), int) else None
        return {**window, "lowConfidence": rates.low_confidence(rate["n"], versus_n, min_counted)}

    out = dict(payload)
    if isinstance(out.get("metrics"), list):
        out["metrics"] = [judged(metric) for metric in out["metrics"]]
    if out.get("overall") is not None:
        out["overall"] = judged(out["overall"])
    replay = out.get("replay")
    if isinstance(replay, dict) and isinstance(replay.get("rates"), list):
        out["replay"] = {**replay, "rates": [judged_rate(w) for w in replay["rates"]]}
    return out


def trial_table_of(document: dict[str, Any], profile: TaskProfile | None) -> dict[str, Any] | None:
    """A run's trial table as the wire carries it (`RunSeries.trialTable`), for a
    spine run and a legacy one alike. None for a run with no table: a spine run
    replay does not score (diverged, or one it cannot run), and a legacy run
    with no profile to decode it. Computed on each request and never cached
    (`DATA.md#caching`)."""
    if is_spine_run(document):
        return spine_table(document)
    table = legacy.table_of(document, profile)
    return table.to_json() if table.conditions else None
