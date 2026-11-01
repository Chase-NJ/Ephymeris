"""One metric's whole-session result, the shape every panel reads
(`ANALYTICS.md#two-probabilities-per-metric`). Its own module so the legacy
scorer (`summary.py`) and the trial-table metrics (`table_metrics.py`) both
build it without importing each other."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .stats import _round

#: The id reserved for the pooled figure, so the frontend can offer it in the
#: same selector as the real metrics without colliding with one.
OVERALL_ID = "__overall__"


@dataclass(frozen=True)
class MetricSummary:
    """One metric's whole-session result (`ANALYTICS.md#two-probabilities-per-metric`,
    `ANALYTICS.md#trial-counts`, `ANALYTICS.md#uncertainty`)."""

    id: str
    label: str
    #: Whole-session P(hit) — the summary statistic used by every panel.
    p_session: float | None
    #: Rolling P(hit) at the profile's authored window, for continuity with
    #: what the operator watched live. **Not** interchangeable with the above:
    #: they diverge sharply over the first `windowSize` trials.
    p_window: float | None
    #: Counted trials this metric scored a hit on. Carried alongside `counted`
    #: rather than left to be recovered from `p_session`, because POOLING two
    #: conditions is exact only over integers: summing hits and counted answers
    #: "how often was this animal right on either of these", where averaging the
    #: two proportions weights a 20-trial condition like a 200-trial one.
    hits: int
    counted: int
    triggered: int
    excluded: int
    window_size: int
    wilson_low: float | None
    wilson_high: float | None
    low_confidence: bool
    #: Which answer this condition rewards (`DATA.md#strategy-plane`), or None
    #: when the profile
    #: cannot prove one. What lets the strategy plane fold N conditions onto two
    #: axes without knowing anything about odors.
    answer_side: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "pSession": _round(self.p_session),
            "pWindow": _round(self.p_window),
            "hits": self.hits,
            "counted": self.counted,
            "triggered": self.triggered,
            "excluded": self.excluded,
            "windowSize": self.window_size,
            "wilsonLow": _round(self.wilson_low),
            "wilsonHigh": _round(self.wilson_high),
            "lowConfidence": self.low_confidence,
            "answerSide": self.answer_side,
        }
