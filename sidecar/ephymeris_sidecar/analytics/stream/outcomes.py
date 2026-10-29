"""What actually happened on each trial — `ANALYTICS.md#rewarded-and-response-accuracy`,
`ANALYTICS.md#per-condition-tally`, `ANALYTICS.md#per-trial-tape`.

One classification pass (`_classify_trials`) over the stream, delimited by the
same boundary codes the metrics use. The run's tally, the per-condition tally
and the per-trial tape are all read off that one pass, so they cannot disagree.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

from ...tasks.profile import TaskProfile
from .document import _pairs_of
from .stats import _round, wilson_interval
from .trials import boundaries_for


@dataclass(frozen=True)
class TrialOutcomes:
    """What actually happened on each trial (`ANALYTICS.md#rewarded-and-response-accuracy`).

    The declared metrics are **reward-unconditional**: `trials.py` scores
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
    #: recognised vocabulary. No sketch in this lab runs no-go trials today
    #: (`GRGL`'s and shaping's trial types are all `isGo`), so nothing is
    #: currently mis-scored; a no-go task would need its own bucket before
    #: these numbers could be read.
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
    #: The internal classification (`_classify_trials`' spelling).
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


# --- trial outcomes (ANALYTICS.md#rewarded-and-response-accuracy) ----------------
#
# Recognised by **name** out of the profile's `strobes` map, not by hard-coded
# codes: `TASKS.md#strobes` makes that map the sketch's own declaration of its
# vocabulary, and a code number means nothing without it. A task that doesn't
# declare these names simply reports no outcomes — which is why every pattern
# below is anchored rather than a loose substring.

#: `^FLUID` and not `STOP_FLUID_G_R`, which also contains the word and marks the
#: *end* of delivery. Anchoring is the whole defence here.
_REWARD = re.compile(r"^FLUID(_|$)", re.IGNORECASE)
#: Correct well, released before the hold cleared.
_HOLD_FAIL = re.compile(r"^WATER_UNPOKE_EARLY(_|$)", re.IGNORECASE)
_WRONG_WELL = re.compile(r"^WATER_POKE_ERROR(_|$)", re.IGNORECASE)
#: The odor was sampled to completion. Exact — `ODOR_UNPOKE_EARLY` is the
#: opposite event and must never match here.
_SAMPLED = re.compile(r"^ODOR_UNPOKE$", re.IGNORECASE)


@dataclass(frozen=True)
class _Vocabulary:
    """The outcome codes a profile actually declares."""

    reward: frozenset[int]
    hold_fail: frozenset[int]
    wrong_well: frozenset[int]
    sampled: frozenset[int]

    @property
    def usable(self) -> bool:
        """Both halves are needed: a reward marker with no completed-sampling
        marker gives a numerator with no honest denominator."""
        return bool(self.reward) and bool(self.sampled)


def _vocabulary(profile: TaskProfile) -> _Vocabulary:
    def matching(pattern: re.Pattern[str]) -> frozenset[int]:
        return frozenset(
            code for code, name in profile.strobes.items() if pattern.match(name.strip())
        )

    return _Vocabulary(
        reward=matching(_REWARD),
        hold_fail=matching(_HOLD_FAIL),
        wrong_well=matching(_WRONG_WELL),
        sampled=matching(_SAMPLED),
    )


def _classify_trials(
    codes: list[int], boundaries: frozenset[int], vocab: _Vocabulary
) -> Iterator[tuple[int, int | None, int, str]]:
    """`(open index, settle index, opening code, classification)` per trial.

    Delimited as the metrics are: uses `boundaries_for`'s union rather than a
    single trigger for the same reason the metrics do — a trial abandoned when
    the next odor fires must close there, or its outcome is stolen by
    whichever trial answers next.

    The opening code rides along so a caller can split the tally per condition
    (`ANALYTICS.md#per-condition-tally`) without a second, separately-drifting pass
    over the stream. The two
    indices — positions into `codes`, the settle index `None` for a trial
    nothing settled — ride along for the same reason: the per-trial tape
    (`ANALYTICS.md#per-trial-tape`) must come from *this* loop, because a second
    classifier would
    drift from the first and the tape would stop agreeing with the tallies
    printed beside it.
    """
    open_trial = False
    open_index = 0
    settle_index: int | None = None
    trigger = 0
    sampled = False
    outcome: str | None = None

    def settle() -> str:
        if outcome is not None:
            return outcome
        # A trial the animal engaged with but never answered is a real
        # behavioural category; one it never engaged with is not the same thing.
        return "no_response" if sampled else "aborted"

    for index, code in enumerate(codes):
        if code in boundaries:
            if open_trial:
                yield open_index, settle_index, trigger, settle()
            open_trial, open_index, trigger = True, index, code
            settle_index, sampled, outcome = None, False, None
            continue
        if not open_trial:
            continue
        if code in vocab.sampled:
            sampled = True
        elif outcome is None:
            if code in vocab.reward:
                outcome = "rewarded"
            elif code in vocab.hold_fail:
                outcome = "hold_failed"
            elif code in vocab.wrong_well:
                outcome = "wrong_well"
            else:
                continue
            settle_index = index

    if open_trial:
        yield open_index, settle_index, trigger, settle()


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


def outcomes_of(codes: list[int], profile: TaskProfile | None) -> TrialOutcomes | None:
    """Tally trial outcomes, or `None` when the profile can't express them."""
    classified = _classified_trials(codes, profile)
    if classified is None:
        return None
    return _tally(outcome for _, outcome in classified)


def conditions_of(
    codes: list[int], profile: TaskProfile | None
) -> list[ConditionOutcomes]:
    """The same tally, split per declared condition (`ANALYTICS.md#per-condition-tally`).

    Empty whenever `outcomes_of` is None, and in the same authored order as
    `liveMetrics` — the order the strategy space already treats as load-bearing
    (`DATA.md#strategy-plane`), so a reader comparing the two panels is looking
    at the same axes in
    the same order.
    """
    classified = _classified_trials(codes, profile)
    if classified is None or profile is None:
        return []
    by_trigger: dict[int, list[str]] = {}
    for trigger, outcome in classified:
        by_trigger.setdefault(trigger, []).append(outcome)
    return [
        ConditionOutcomes(
            metric_id=metric.id,
            label=metric.label,
            trigger_code=metric.trigger_code,
            outcomes=_tally(by_trigger.get(metric.trigger_code, [])),
        )
        for metric in profile.live_metrics
    ]


def _classified_trials(
    codes: list[int], profile: TaskProfile | None
) -> list[tuple[int, str]] | None:
    """One classification pass, or `None` when the profile can't express one."""
    if profile is None:
        return None
    boundaries = boundaries_for(profile)
    if not boundaries:
        return None
    vocab = _vocabulary(profile)
    if not vocab.usable:
        return None
    return [
        (trigger, outcome)
        for _, _, trigger, outcome in _classify_trials(codes, boundaries, vocab)
    ]


def trials_of(document: dict[str, Any], profile: TaskProfile | None) -> list[TrialRecord]:
    """The per-trial tape (`ANALYTICS.md#per-trial-tape`), or `[]` when the profile
    can't express one.

    The same `_classify_trials` pass `outcomes_of`/`conditions_of` sum over,
    kept as a sequence — so tallying this list by class reproduces the run's
    `TrialOutcomes`, and grouping it by `trigger_code` reproduces its
    `ConditionOutcomes`. That identity is pinned by test; a second classifier
    here would let the tape and the tallies drift apart silently.

    Times are relative to the run's *earliest* timestamp rather than its
    first, for `_duration_ms`'s reason: a finalized file is written in arrival
    order, but a hand-edited or concatenated one need not be, and a negative
    "elapsed" reads as a behaviour instead of being caught. A latency that
    still comes out negative on such a file is nulled, not reported.
    """
    if profile is None:
        return []
    boundaries = boundaries_for(profile)
    if not boundaries:
        return []
    vocab = _vocabulary(profile)
    if not vocab.usable:
        return []
    pairs = _pairs_of(document)
    codes = [code for code, _ in pairs]
    stamps = [ts for _, ts in pairs if ts is not None]
    base = min(stamps) if stamps else None

    out: list[TrialRecord] = []
    for index, (open_index, settle_index, trigger, outcome) in enumerate(
        _classify_trials(codes, boundaries, vocab)
    ):
        open_ts = pairs[open_index][1]
        settle_ts = pairs[settle_index][1] if settle_index is not None else None
        at_ms = open_ts - base if open_ts is not None and base is not None else None
        latency_ms = (
            settle_ts - open_ts
            if settle_ts is not None and open_ts is not None and settle_ts >= open_ts
            else None
        )
        out.append(
            TrialRecord(
                index=index,
                trigger_code=trigger,
                outcome=outcome,
                at_ms=at_ms,
                latency_ms=latency_ms,
            )
        )
    return out
