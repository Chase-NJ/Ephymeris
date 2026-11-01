"""What actually happened on each trial — `ANALYTICS.md#rewarded-and-response-accuracy`,
`ANALYTICS.md#per-condition-tally`, `ANALYTICS.md#per-trial-tape`.

Every figure here is read off a legacy run's trial table
(`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`): its onset trials, each
classified once by the legacy decoder. The run's tally, the per-condition tally
and the per-trial tape are all read off those rows, so they cannot disagree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

from ...tasks.profile import TaskProfile
from . import spine
from .legacy import decode
from .stats import _round, wilson_interval

@dataclass(frozen=True)
class TrialOutcomes:
    """What actually happened on each trial (`ANALYTICS.md#rewarded-and-response-accuracy`).

    The declared metrics are **reward-unconditional**: `legacy/trials.py` scores
    a `WATER_POKE_L/R` the instant the poke is detected, so an animal that
    reaches the correct well and releases before the fluid hold still scores a
    hit. That is the right definition for a live discrimination readout — it
    measures the choice, not the consummatory hold — but it is not the same
    question as "how often did this animal actually earn water", and averaging
    the two together would quietly answer neither.

    So this tally separates them:

    * **rewarded accuracy** = `rewarded / administered` — fluid actually
      delivered. Conservative: a hold failure counts against it.
    * **side accuracy** = `(rewarded + hold_failed) / administered` — the
      correct *side* was chosen, whether or not the hold earned the drop. This
      is the discrimination figure, and is always ≥ rewarded accuracy.

    The gap between the two is the consummatory hold failure rate, which is a
    real and separately interesting behaviour rather than noise.
    """

    #: Every trial boundary seen — **one per odor onset**, which is not the same
    #: as one per trial the box offered. The firmware fires its odor-on strobe
    #: only after the animal has poked *and* held the odor port, so a trial the
    #: animal ignored (`LAZY_RAT`) or bailed out of before odor delivery
    #: produces no boundary and is invisible to every count in this class. This
    #: is a tally of *engaged* trials; engagement itself is not measured here.
    trials: int = 0
    #: Odor sampled to completion; the denominator for both accuracies. A trial
    #: the animal never engaged is not evidence about discrimination.
    administered: int = 0
    rewarded: int = 0
    #: Correct well reached, released before the hold cleared — no fluid.
    hold_failed: int = 0
    wrong_well: int = 0
    #: Administered, but no well was ever answered before the next trial.
    #:
    #: On a **no-go** task this bucket also catches the *correct* answer — a
    #: withhold looks exactly like a non-response from the strobes alone, since
    #: the only thing distinguishing them (`WATER_POKE_NONE`) isn't part of the
    #: recognised vocabulary, and a no-go trial answered at a port carries no
    #: fluid or error evidence either. A task with a no-go type needs its own
    #: bucket before these numbers can be read; P(withhold) is a per-condition
    #: metric and is unaffected (`ANALYTICS.md#trials-hits-misses-and-exclusions`).
    no_response: int = 0
    #: Odor was delivered and the animal left the port before sampling cleared.
    #: **Not** every unengaged trial — see `trials` above: a trial the animal
    #: never poked at all never reaches an odor onset and is not counted here,
    #: or anywhere.
    aborted: int = 0

    @property
    def p_rewarded(self) -> float | None:
        return self.rewarded / self.administered if self.administered else None

    @property
    def p_side(self) -> float | None:
        if not self.administered:
            return None
        return (self.rewarded + self.hold_failed) / self.administered

    def to_json(self) -> dict[str, Any]:
        rewarded_interval = wilson_interval(self.rewarded, self.administered)
        side_interval = wilson_interval(self.rewarded + self.hold_failed, self.administered)
        return {
            "trials": self.trials,
            "administered": self.administered,
            "rewarded": self.rewarded,
            "holdFailed": self.hold_failed,
            "wrongWell": self.wrong_well,
            "noResponse": self.no_response,
            "aborted": self.aborted,
            "pRewarded": _round(self.p_rewarded),
            "pSide": _round(self.p_side),
            "rewardedLow": _round(rewarded_interval[0] if rewarded_interval else None),
            "rewardedHigh": _round(rewarded_interval[1] if rewarded_interval else None),
            "sideLow": _round(side_interval[0] if side_interval else None),
            "sideHigh": _round(side_interval[1] if side_interval else None),
        }


@dataclass(frozen=True)
class ConditionOutcomes:
    """The same tally as `TrialOutcomes`, restricted to one declared condition
    (`ANALYTICS.md#per-condition-tally`).

    A condition is a declared `liveMetrics` entry, identified by the trigger
    code that opens its trials — for GRGL that is odor 1 (answer right) and
    odor 3 (answer left), so this is what makes "how many go-right trials were
    administered, and how many of those paid out" answerable. Driven off the
    profile's authored metrics rather than any particular task's vocabulary: a
    profile declaring five conditions gets five of these.

    Two metrics sharing a trigger code would legitimately produce two entries
    over the same trials — the trigger is what delimits a condition, and a
    profile that declares the same trials twice is asking for exactly that.
    """

    metric_id: str
    label: str
    trigger_code: int
    outcomes: TrialOutcomes

    def to_json(self) -> dict[str, Any]:
        return {
            "metricId": self.metric_id,
            "label": self.label,
            "triggerCode": self.trigger_code,
            "outcomes": self.outcomes.to_json(),
        }


@dataclass(frozen=True)
class TrialRecord:
    """One classified trial (`ANALYTICS.md#per-trial-tape`) — the tape the tallies
    are summed from."""

    #: 0-based position in the stream's trial order.
    index: int
    #: The condition code that opened the trial — one of `boundaries_for`'s
    #: union, so a `ConditionOutcomes.trigger_code` matches it directly.
    trigger_code: int
    #: The internal classification (`legacy.strobes.classify_trials`' spelling).
    outcome: str
    #: Trial open, in ms from the run's earliest recorded timestamp. `None`
    #: when the file carries no usable clock at either end of the subtraction.
    at_ms: int | None
    #: Trial open → the code that settled the outcome. `None` for
    #: no-response/aborted trials, which nothing settles.
    latency_ms: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "triggerCode": self.trigger_code,
            "outcome": _WIRE_OUTCOME[self.outcome],
            "atMs": self.at_ms,
            "latencyMs": self.latency_ms,
        }


#: Wire spellings are hyphenated, matching `RunStatus`/`ProfileSource`; the
#: internal names keep the underscore `Counter` keys `_tally` already uses.
_WIRE_OUTCOME = {
    "rewarded": "rewarded",
    "hold_failed": "hold-failed",
    "wrong_well": "wrong-well",
    "no_response": "no-response",
    "aborted": "aborted",
}



def _tally(classifications: Iterable[str]) -> TrialOutcomes:
    counts = Counter(classifications)
    rewarded = counts["rewarded"]
    hold_failed = counts["hold_failed"]
    wrong_well = counts["wrong_well"]
    no_response = counts["no_response"]
    aborted = counts["aborted"]
    return TrialOutcomes(
        trials=sum(counts.values()),
        # Everything that reached a well was necessarily administered, whether
        # or not the sampling marker was seen — deriving it from the resolved
        # outcomes keeps the denominator consistent with its own numerators.
        administered=rewarded + hold_failed + wrong_well + no_response,
        rewarded=rewarded,
        hold_failed=hold_failed,
        wrong_well=wrong_well,
        no_response=no_response,
        aborted=aborted,
    )




def tally_outcomes(table: decode.LegacyTable) -> TrialOutcomes | None:
    """The outcome tally of a legacy table, or `None` when its profile can't
    express outcomes."""
    if not table.outcomes:
        return None
    return _tally(decode.legacy_outcome(t) for t in _onsets(table))


def tally_conditions(table: decode.LegacyTable) -> list[ConditionOutcomes]:
    """The same tally, split per declared condition (`ANALYTICS.md#per-condition-tally`).

    Empty whenever `tally_outcomes` is None, and in the same authored order as
    `liveMetrics` — the order the strategy space already treats as load-bearing
    (`DATA.md#strategy-plane`), so a reader comparing the two panels is looking
    at the same axes in the same order. A condition's trials are the rows scored
    under it: every trial its onset opened.
    """
    if not table.outcomes:
        return []
    return [
        ConditionOutcomes(
            metric_id=c.id,
            label=c.label,
            trigger_code=c.trigger,
            outcomes=_tally(decode.legacy_outcome(t) for t in _onsets(table) if t.scored(c.id)),
        )
        for c in table.conditions
    ]


def tape_of(table: decode.LegacyTable) -> list[TrialRecord]:
    """The per-trial tape (`ANALYTICS.md#per-trial-tape`), or `[]` when the
    profile can't express outcomes.

    The same rows `tally_outcomes`/`tally_conditions` sum over, kept as a
    sequence — so tallying this list by class reproduces the run's
    `TrialOutcomes`, and grouping it by `trigger_code` reproduces its
    `ConditionOutcomes`. That identity is pinned by test.

    Times are relative to the run's *earliest* timestamp rather than its
    first, for `_duration_ms`'s reason: a finalized file is written in arrival
    order, but a hand-edited or concatenated one need not be, and a negative
    "elapsed" reads as a behaviour instead of being caught. A latency that
    still comes out negative on such a file is nulled, not reported.
    """
    if not table.outcomes:
        return []
    trigger = {c.id: c.trigger for c in table.conditions}
    return [
        TrialRecord(
            index=k,
            trigger_code=trigger[t.row],
            outcome=decode.legacy_outcome(t),
            at_ms=t.at_ms,
            latency_ms=t.outcome_ms - t.at_ms
            if t.outcome_ms is not None and t.at_ms is not None and t.outcome_ms >= t.at_ms
            else None,
        )
        for k, t in enumerate(_onsets(table))
    ]


def _onsets(table: decode.LegacyTable) -> list[Any]:
    """The rows an odor onset opened: every row with a condition."""
    return [t for t in table.trials if t.row is not None]


def outcomes_of(codes: list[int], profile: TaskProfile | None) -> TrialOutcomes | None:
    """Tally bare codes' trial outcomes, or `None` when the profile can't express them."""
    return tally_outcomes(decode.table_of_codes(codes, profile))


def conditions_of(codes: list[int], profile: TaskProfile | None) -> list[ConditionOutcomes]:
    """The per-condition tally of bare codes."""
    return tally_conditions(decode.table_of_codes(codes, profile))


def trials_of(document: dict[str, Any], profile: TaskProfile | None) -> list[TrialRecord]:
    """A legacy run's per-trial tape. `[]` for a spine run: its trial table is its tape."""
    if spine.is_spine_run(document):
        return []
    return tape_of(decode.table_of(document, profile))
