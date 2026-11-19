"""One run, scored — `ANALYTICS.md#how-a-strobe-stream-is-scored`.

`summarize(document, profile)` is the whole job, and it is the same for both
kinds of run: read the run into its trial table, then read every number off
the table. A stream-grammar-2 run's table comes from its headers and outcome
codes (`ANALYTICS.md#stream-grammar-2`); a grammar-1 run's from the legacy
decoder (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`). Either gives
the per-condition P(hit), the pooled figure, the outcome tally, the
per-condition tally and the engagement ladder, as one `RunSummary`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...sessions.run_document import stop_reason_of, trial_seed_of
from ...tasks.profile import TaskProfile
from .document import _duration_ms, codes_of, ran_by_the_trial_runner
from . import grammar2, legacy, table_metrics
from .engagement import TrialEngagement, tally_engagement
from .outcomes import ConditionOutcomes, TrialOutcomes, tally_conditions, tally_outcomes
from .metric_summary import OVERALL_ID, MetricSummary


@dataclass(frozen=True)
class RunSummary:
    """Everything the cohort-scale panels need about one animal's run."""

    status: str  # 'ok' | 'no-metrics' | 'missing' | 'unreadable'
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
        }


#: The clean-end reason, matching `sessions/runner.py`'s literal exactly.
CLEAN_STOP_REASON = "BF_END_SESSION received"

#: Why a run another firmware interpreter recorded has no numbers.
FOREIGN_INTERPRETER = "recorded by a firmware interpreter this build does not read"


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
    stop_reason = stop_reason_of(document)
    stop_reason = stop_reason if isinstance(stop_reason, str) else None

    duration = _duration_ms(document)
    seed = trial_seed_of(document)
    seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None

    base = {
        "total_events": len(codes),
        "duration_ms": duration,
        "stop_reason": stop_reason,
        "clean": stop_reason == CLEAN_STOP_REASON,
        "seed": seed,
    }

    # A run its own file says another firmware interpreter ran is never read
    # by the decoders below, whose code names its stream would only mimic
    # (`ANALYTICS.md#why-a-run-has-no-numbers`).
    if not ran_by_the_trial_runner(document):
        return RunSummary(status="unreadable", detail=FOREIGN_INTERPRETER, **base)

    # A sketch with no Task Profile is fully supported (`ANALYTICS.md#edge-cases`)
    # and still worth listing — it has a real duration, event count and stop
    # reason. Inventing a default metric for it would be worse than saying so.
    if profile is None or not profile.live_metrics:
        return RunSummary(status="no-metrics", **base)

    # A grammar-2 run is read off its headers and outcome codes
    # (`ANALYTICS.md#stream-grammar-2`); its metrics are the same accumulators.
    if grammar2.is_grammar2_run(document, profile):
        table2 = grammar2.table_of(document, profile)
        metrics = table_metrics.legacy_metrics(table2, min_counted=min_counted)
        return RunSummary(
            status="ok",
            metrics=metrics,
            overall=table_metrics.legacy_overall(metrics, min_counted=min_counted),
            outcomes=grammar2.tally_outcomes(table2),
            conditions=grammar2.tally_conditions(table2),
            engagement=grammar2.tally_engagement(table2),
            excluded_by_default=profile.kind == "utility",
            **base,
        )

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


def with_threshold(payload: dict[str, Any], min_counted: int) -> dict[str, Any]:
    """A summary payload judged against `min_counted`, as a copy.

    `lowConfidence` is the only part of a summary the threshold touches, and it
    is `counted < min_counted` for each metric and the pooled figure. The
    threshold is a per-request argument (`analytics.summary`'s
    `minCountedTrials`) while the payload is cached, so the flag is re-judged on
    every row served rather than kept from whichever request computed it
    (`DATA.md#caching`).
    """
    def judged(metric: Any) -> Any:
        if not isinstance(metric, dict) or not isinstance(metric.get("counted"), int):
            return metric
        return {**metric, "lowConfidence": metric["counted"] < min_counted}

    out = dict(payload)
    if isinstance(out.get("metrics"), list):
        out["metrics"] = [judged(metric) for metric in out["metrics"]]
    if out.get("overall") is not None:
        out["overall"] = judged(out["overall"])
    return out


def trial_table_of(document: dict[str, Any], profile: TaskProfile | None) -> dict[str, Any] | None:
    """A run's trial table as the wire carries it (`RunSeries.trialTable`).
    None for a run with no table: one with no profile to decode it, or one
    another firmware interpreter recorded. Computed on each request and never
    cached (`DATA.md#caching`)."""
    if not ran_by_the_trial_runner(document):
        return None
    if grammar2.is_grammar2_run(document, profile):
        table2 = grammar2.table_of(document, profile)
        return table2.to_json() if table2.conditions else None
    table = legacy.table_of(document, profile)
    return table.to_json() if table.conditions else None
