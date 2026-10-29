"""How far each offered trial got before the animal dropped out —
`ANALYTICS.md#engagement-ladder`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...tasks.profile import TaskProfile
from .stats import _round, wilson_interval
from .trials import boundaries_for


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


#: The trial light going on: the top of a presentation, before the animal has
#: had any chance to act (`ANALYTICS.md#engagement-ladder`). Exact, so `LIGHTS_OFF`
#: — the same word, the
#: opposite edge — can never open a presentation window.
_PRESENTED = re.compile(r"^LIGHTS_ON$", re.IGNORECASE)
#: The animal poked the odor port. Exact for the same reason `_SAMPLED` is:
#: `ODOR_POKE_*` variants, were any ever declared, would be different events.
_ENGAGED = re.compile(r"^ODOR_POKE$", re.IGNORECASE)


def engagement_of(
    codes: list[int], profile: TaskProfile | None
) -> TrialEngagement | None:
    """Walk the presentations and count how far each one got
    (`ANALYTICS.md#engagement-ladder`).

    One pass, one open window at a time, and each stage latched rather than
    counted per occurrence — a presentation contributes at most one to each
    rung whatever the animal did inside it. That is what keeps the ladder
    monotone: a repeated `ODOR_POKE` inside one window (the firmware doesn't
    emit one, but a hand-edited file can hold anything) can't push `poked` past
    `presented`.

    `None` when the profile declares neither the light nor the poke. Both are
    needed together: the light alone gives a denominator with no numerator, and
    "the box offered 300 trials and we can't say whether any were engaged" is
    worse than saying nothing — it reads as zero engagement.
    """
    if profile is None:
        return None
    boundaries = boundaries_for(profile)
    if not boundaries:
        return None
    lights = frozenset(
        code for code, name in profile.strobes.items() if _PRESENTED.match(name.strip())
    )
    pokes = frozenset(
        code for code, name in profile.strobes.items() if _ENGAGED.match(name.strip())
    )
    if not lights or not pokes:
        return None

    presented = poked = delivered = 0
    open_window = False
    saw_poke = saw_odor = False

    def close() -> None:
        nonlocal poked, delivered
        poked += 1 if saw_poke else 0
        delivered += 1 if saw_odor else 0

    for code in codes:
        if code in lights:
            if open_window:
                close()
            presented += 1
            open_window, saw_poke, saw_odor = True, False, False
            continue
        if not open_window:
            # Strobes before the first trial light — `START_SESSION` and
            # friends — belong to no presentation and are not one.
            continue
        if code in pokes:
            saw_poke = True
        elif code in boundaries:
            # Odor delivery implies the poke that earned it, even if the poke
            # strobe went missing: the firmware cannot reach its odor-on code
            # without one, so inferring it here keeps the ladder monotone on a
            # stream that dropped a line.
            saw_poke = saw_odor = True

    if open_window:
        close()
    return TrialEngagement(presented=presented, poked=poked, odor_delivered=delivered)
