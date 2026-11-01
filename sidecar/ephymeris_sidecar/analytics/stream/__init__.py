"""Evaluating a strobe stream — `ANALYTICS.md#how-a-strobe-stream-is-scored`.

**Pure.** No I/O, no database, no clock: `(document, profile)` in, numbers
out. That is what makes the offline figures assertable against the live path
over a recorded stream, and it is what lets a reader check the science without
reading anything outside this folder. `tests/test_analytics_stream_is_pure.py`
keeps it that way.

Every run is read into its **trial table**, and every number is read off the
table: a spine run's by replay, a legacy run's by the legacy decoder.

| Module | Answers |
|---|---|
| `legacy/` | A legacy run's trial table, read from its strobe names; the live runner's scorer (`MetricSet`); inference |
| `replay`, `spine` | A spine run replayed from its own file, and checked against what it recorded |
| `trial_table` | One row per trial, for both kinds of run |
| `table_metrics` | P(correct \\| row) and P(hit) per condition, the pooled figure, a spine run's class tallies |
| `outcomes` | Was it rewarded, a hold failure, the wrong well, unanswered, or aborted? |
| `engagement` | How many trials were offered, poked, and given odor? |
| `summary` | One run's whole result (`summarize`), and its trial table for the wire |
| `curves` | The run trial by trial: learning curves and the strategy walk |
| `false_starts` | Which restarted runs to set aside |
| `stats`, `document`, `metric_summary` | The Wilson interval; reading `ts_data` out of a file's document; the metric shape |

Cached summaries are versioned by `scoring.current_version`, which moves by
itself when anything here changes what a summary holds — the maths or the
payload's shape (`DATA.md#caching`). There is nothing to bump in this folder.
"""

from __future__ import annotations

from . import false_starts, legacy
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
    summarize,
    trial_table_of,
    with_threshold,
)

__all__ = [
    "CLEAN_STOP_REASON",
    "DEFAULT_MIN_COUNTED",
    "OVERALL_ID",
    "Z_95",
    "ConditionOutcomes",
    "MetricSeries",
    "MetricSummary",
    "RunSummary",
    "StrategyAxes",
    "StrategyPoint",
    "TrialEngagement",
    "TrialOutcomes",
    "TrialRecord",
    "codes_of",
    "conditions_of",
    "engagement_of",
    "false_starts",
    "legacy",
    "outcomes_of",
    "series",
    "strategy_axes",
    "strategy_trail",
    "summarize",
    "trial_table_of",
    "trials_of",
    "wilson_interval",
    "with_threshold",
]
