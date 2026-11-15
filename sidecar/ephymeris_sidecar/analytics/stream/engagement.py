"""How far each offered trial got before the animal dropped out —
`ANALYTICS.md#engagement-ladder`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...tasks.profile import TaskProfile
from .stats import _round, wilson_interval
from .legacy import decode


@dataclass(frozen=True)
class TrialEngagement:
    """How far each *offered* trial got before the animal dropped out
    (`ANALYTICS.md#engagement-ladder`).

    `TrialOutcomes` and every accuracy above it are delimited on **odor onset**,
    and the firmware only reaches its odor-on strobe after the animal has poked
    the odor port and held it. So a trial the animal ignored, or poked and
    immediately abandoned, produces no boundary and is invisible to all of them.
    Every rate in this module is therefore conditioned on engagement — and
    without this class, engagement itself was measured nowhere. A rat that
    skipped two thirds of its trials and answered the rest well read exactly
    like one that worked steadily.

    Delimited on the **trial light** instead, which is the first thing that
    happens in a presentation and happens unconditionally: the firmware writes
    `trialLight` HIGH and strobes `LIGHTS_ON` at the top of every attempt,
    before the animal has had any opportunity to do anything at all.

    The three counts are a **ladder**, not a partition: each is "how many
    presentations reached this stage", so `presented >= poked >= odor_delivered`
    holds by construction and the two gaps can't come out negative or fail to
    account for a presentation. That is deliberate — a partition would need a
    residual bucket for the one presentation a board drop can leave dangling,
    and would invite reading a truncated stream as a behaviour.

    What the gaps mean:

    * `presented - poked` — the animal never engaged the odor port. `LAZY_RAT`
      in practice; also, for at most one presentation per run, a session that
      ended mid-window.
    * `poked - odor_delivered` — engaged, then let go before the pre-odor hold
      cleared, so no odor was ever delivered. Distinct from
      `TrialOutcomes.aborted`, which is the animal that *did* receive odor and
      left during sampling.
    """

    #: Every trial the box offered — one per `LIGHTS_ON`.
    presented: int = 0
    #: Of those, the ones the animal poked the odor port on.
    poked: int = 0
    #: Of those, the ones that reached odor delivery. Equals
    #: `TrialOutcomes.trials` on any well-formed stream — the same trials
    #: counted from the other end — and `test_analytics_derive` pins that
    #: agreement rather than either side assuming it.
    odor_delivered: int = 0

    @property
    def p_engaged(self) -> float | None:
        """Share of offered trials the animal poked at all — the participation
        rate the accuracy figures are silently conditioned on."""
        return self.poked / self.presented if self.presented else None

    @property
    def p_delivered(self) -> float | None:
        """Share of offered trials that got as far as odor delivery."""
        return self.odor_delivered / self.presented if self.presented else None

    def to_json(self) -> dict[str, Any]:
        engaged_interval = wilson_interval(self.poked, self.presented)
        return {
            "presented": self.presented,
            "poked": self.poked,
            "odorDelivered": self.odor_delivered,
            "noPoke": self.presented - self.poked,
            "pokeAborted": self.poked - self.odor_delivered,
            "pEngaged": _round(self.p_engaged),
            "pDelivered": _round(self.p_delivered),
            "engagedLow": _round(engaged_interval[0] if engaged_interval else None),
            "engagedHigh": _round(engaged_interval[1] if engaged_interval else None),
        }


def tally_engagement(table: decode.LegacyTable) -> TrialEngagement | None:
    """The ladder, read off a legacy table's presentations
    (`ANALYTICS.md#engagement-ladder`): every row that opens one, poked when an
    onset opened it or the animal let go before odor, delivered when an onset did.

    `None` when the profile declares neither the light nor the poke: "the box
    offered 300 trials and we can't say whether any were engaged" is worse
    than saying nothing, because it reads as zero engagement.
    """
    if not table.engagement:
        return None
    shown = [t for t in table.trials if t.presented]
    return TrialEngagement(
        presented=len(shown),
        poked=sum(1 for t in shown if t.row is not None or t.outcome == decode.POKED_NO_ODOR),
        odor_delivered=sum(1 for t in shown if t.row is not None),
    )


def engagement_of(codes: list[int], profile: TaskProfile | None) -> TrialEngagement | None:
    """The engagement ladder of bare codes."""
    return tally_engagement(decode.table_of_codes(codes, profile))
