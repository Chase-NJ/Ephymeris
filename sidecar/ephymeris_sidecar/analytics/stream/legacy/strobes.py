"""What a legacy run's strobe names say: which trial each outcome strobe settles,
where each presentation starts, and which answer a condition rewards
(`ANALYTICS.md#rewarded-and-response-accuracy`, `ANALYTICS.md#engagement-ladder`).

Recognised by **name** out of the profile's `strobes` map, never by code number:
`TASKS.md#strobes` makes that map the sketch's own declaration of its vocabulary,
and a code number means nothing without it. A task that doesn't declare these
names reports no outcomes, which is why every pattern below is anchored rather
than a loose substring.

`decode.py` reads these into the trial table; nothing else does.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from ....tasks.profile import LiveMetric, TaskProfile

#: `^FLUID` and not `STOP_FLUID_G_R`, which also contains the word and marks the
#: *end* of delivery. Anchoring is the whole defence here.
_REWARD = re.compile(r"^FLUID(_|$)", re.IGNORECASE)
#: Correct well, released before the hold cleared.
_HOLD_FAIL = re.compile(r"^WATER_UNPOKE_EARLY(_|$)", re.IGNORECASE)
_WRONG_WELL = re.compile(r"^WATER_POKE_ERROR(_|$)", re.IGNORECASE)
#: The odor was sampled to completion. Exact — `ODOR_UNPOKE_EARLY` is the
#: opposite event and must never match here.
_SAMPLED = re.compile(r"^ODOR_UNPOKE$", re.IGNORECASE)

#: The trial light going on: the top of a presentation, before the animal has
#: had any chance to act (`ANALYTICS.md#engagement-ladder`). Exact, so `LIGHTS_OFF`
#: — the same word, the opposite edge — can never open a presentation window.
_PRESENTED = re.compile(r"^LIGHTS_ON$", re.IGNORECASE)
#: The animal poked the odor port. Exact for the same reason `_SAMPLED` is:
#: `ODOR_POKE_*` variants, were any ever declared, would be different events.
_ENGAGED = re.compile(r"^ODOR_POKE$", re.IGNORECASE)


@dataclass(frozen=True)
class OutcomeCodes:
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


def _matching(profile: TaskProfile, pattern: re.Pattern[str]) -> frozenset[int]:
    return frozenset(code for code, name in profile.strobes.items() if pattern.match(name.strip()))


def outcome_codes(profile: TaskProfile) -> OutcomeCodes:
    return OutcomeCodes(
        reward=_matching(profile, _REWARD),
        hold_fail=_matching(profile, _HOLD_FAIL),
        wrong_well=_matching(profile, _WRONG_WELL),
        sampled=_matching(profile, _SAMPLED),
    )


def classify_trials(
    codes: list[int], boundaries: frozenset[int], vocab: OutcomeCodes
) -> Iterator[tuple[int, int | None, int, str]]:
    """`(open index, settle index, opening code, classification)` per trial.

    Delimited as the metrics are: uses `boundaries_for`'s union rather than a
    single trigger for the same reason the metrics do — a trial abandoned when
    the next odor fires must close there, or its outcome is stolen by
    whichever trial answers next. A trial runs from its onset to the next
    boundary code, and the first outcome code inside it decides; only a trial
    with none falls through to the sampling check. The settle index is `None`
    for a trial nothing settled.
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


def presentation_codes(profile: TaskProfile) -> tuple[frozenset[int], frozenset[int]]:
    """The trial light's codes and the odor poke's. The ladder needs both: the
    light alone gives a denominator with no numerator, and "the box offered 300
    trials and we can't say whether any were engaged" reads as zero engagement."""
    return _matching(profile, _PRESENTED), _matching(profile, _ENGAGED)


def presentations(
    codes: list[int], boundaries: frozenset[int], lights: frozenset[int], pokes: frozenset[int]
) -> Iterator[tuple[int, bool, int | None]]:
    """`(light index, poked, first onset index)` per presentation
    (`ANALYTICS.md#engagement-ladder`): one window per trial light, up to the next.

    Each stage is latched rather than counted per occurrence, so a presentation
    reaches each rung at most once whatever the animal did inside it: a repeated
    `ODOR_POKE` (the firmware doesn't emit one, but a hand-edited file can hold
    anything) cannot push `poked` past `presented`. Odor delivery implies the
    poke that earned it, even if the poke strobe went missing: the firmware
    cannot reach its odor-on code without one. Strobes before the first trial
    light (`START_SESSION` and friends) belong to no presentation.
    """
    start: int | None = None
    poked = False
    onset: int | None = None
    for index, code in enumerate(codes):
        if code in lights:
            if start is not None:
                yield start, poked, onset
            start, poked, onset = index, False, None
            continue
        if start is None:
            continue
        if code in pokes:
            poked = True
        elif code in boundaries:
            poked = True
            if onset is None:
                onset = index
    if start is not None:
        yield start, poked, onset


#: `WATER_POKE_L` → left. Mirrors `infer.py`'s `_side_label` and the frontend's
#: `correctWellOf`, all three reading the historical suffix rather than assuming
#: it: a rig whose response ports carry no side keeps its slot number.
_ANSWER_SIDE = re.compile(r"^WATER_POKE_(?:PORT_(?P<slot>\d+)|(?P<side>L|R))$")


def answer_side_of(profile: TaskProfile | None, metric: LiveMetric) -> str | None:
    """Which answer a condition rewards — `left`, `right`, `withhold`, `port`.

    > [!CAUTION]
    > **From `success_code` and nothing else.** The tempting fallback — try
    > `alternate_code` when the success code is not a well — is wrong in a way
    > that prints a confident lie: a no-go metric's alternates are *every
    > response port* (the generator's `_enter_codes`, `infer.no_go_alternates`), so
    > the fallback answers "left well" for a condition whose correct answer
    > is to poke nothing. `None` is the honest result whenever the profile
    > cannot prove one, and every consumer treats it as "this condition has no axis" rather than filling it in.
    """
    if profile is None:
        return None
    name = (profile.strobes.get(metric.success_code) or "").strip().upper()
    if not name:
        return None
    if name == "WATER_POKE_NONE":
        return "withhold"
    match = _ANSWER_SIDE.match(name)
    if match is None:
        return None
    if match.group("slot"):
        return "port"
    return "left" if match.group("side") == "L" else "right"
