"""Evaluating a strobe stream — `ANALYTICS.md#how-a-strobe-stream-is-scored`.

**Pure.** No I/O, no database, no clock: `(document, profile)` in, numbers
out. That is what makes the offline figures assertable against the live path
over a recorded stream, and it is what lets a reader check the science without
reading anything outside this folder. `tests/test_analytics_stream_is_pure.py`
keeps it that way.

| Module | Answers |
|---|---|
| `trials` | Is this trial a hit, a miss, or excluded? (also the live runner's scorer) |
| `outcomes` | Was it rewarded, a hold failure, the wrong well, unanswered, or aborted? |
| `engagement` | How many trials were offered, poked, and given odor? |
| `summary` | One run's whole result (`summarize`) |
| `curves` | The run trial by trial: learning curves and the strategy walk |
| `infer` | Which conditions ran, read from the strobes when no profile declares them |
| `false_starts` | Which restarted runs to set aside |
| `replay`, `spine` | A spine run replayed from its own file, and checked against what it recorded |
| `trial_table`, `table_metrics` | A spine run's trial table, and the numbers that are functions of it |
| `stats`, `document`, `metric_summary` | The Wilson interval; reading `ts_data` out of a file's document; the metric shape |

Cached summaries are versioned by `scoring.current_version`, which moves by
itself when anything here changes what a summary holds — the maths or the
payload's shape (`DATA.md#caching`). There is nothing to bump in this folder.
"""

from __future__ import annotations

from . import false_starts, infer
from .curves import (
    MetricSeries,
    StrategyAxes,
    StrategyPoint,
    series,
    strategy_axes,
    strategy_trail,
)
from .document import codes_of
from .engagement import TrialEngagement, engagement_of
from .outcomes import (
    ConditionOutcomes,
    TrialOutcomes,
    TrialRecord,
    conditions_of,
    outcomes_of,
    trials_of,
)
from .stats import Z_95, wilson_interval
from .summary import (
    CLEAN_STOP_REASON,
    DEFAULT_MIN_COUNTED,
    OVERALL_ID,
    MetricSummary,
    RunSummary,
    answer_side_of,
    live_equivalent,
    summarize,
    with_threshold,
)
from .trials import (
    MetricAccumulator,
    MetricSet,
    MetricValue,
    boundaries_for,
    compute_series,
)

__all__ = [
    "CLEAN_STOP_REASON",
    "DEFAULT_MIN_COUNTED",
    "OVERALL_ID",
    "Z_95",
    "ConditionOutcomes",
    "MetricAccumulator",
    "MetricSeries",
    "MetricSet",
    "MetricSummary",
    "MetricValue",
    "RunSummary",
    "StrategyAxes",
    "StrategyPoint",
    "TrialEngagement",
    "TrialOutcomes",
    "TrialRecord",
    "answer_side_of",
    "boundaries_for",
    "codes_of",
    "compute_series",
    "conditions_of",
    "engagement_of",
    "false_starts",
    "infer",
    "live_equivalent",
    "outcomes_of",
    "series",
    "strategy_axes",
    "strategy_trail",
    "summarize",
    "trials_of",
    "wilson_interval",
    "with_threshold",
]
