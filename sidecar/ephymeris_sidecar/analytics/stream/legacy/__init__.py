"""The legacy decoder: the strobe scorer, frozen (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

A run whose file predates the phase spine (`interp` absent or 1) records what
the trial runner's strobe names say. This package is the only code that reads
meaning out of those names, and it reads them into the same trial table a
replayed spine run has (`decode.table_of`), so one analysis spans the cutover
(ADR 0003). Nothing outside it matches a strobe name.

| Module | Answers |
|---|---|
| `decode` | A legacy run's trial table (`table_of`) |
| `trials` | Is this trial a hit, a miss, or excluded? (also the live runner's scorer, `MetricSet`) |
| `strobes` | Which outcome strobe settles a trial, where a presentation starts, which answer a condition rewards |
| `infer` | Which conditions ran, read from the strobes when no profile declares them |

Frozen: a change here moves a number the archive already reported, so
`tests/test_legacy_pin.py` must still pass, unchanged.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from . import decode, infer, strobes
from .decode import Condition, LegacyTable, table_of
from .strobes import answer_side_of
from .trials import (
    MetricAccumulator,
    MetricSet,
    MetricValue,
    boundaries_for,
    compute_series,
    live_equivalent,
)

__all__ = [
    "Condition",
    "LegacyTable",
    "MetricAccumulator",
    "MetricSet",
    "MetricValue",
    "answer_side_of",
    "boundaries_for",
    "compute_series",
    "decode",
    "infer",
    "live_equivalent",
    "strobes",
    "table_of",
]
