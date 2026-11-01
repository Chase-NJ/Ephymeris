"""A legacy run as a trial table (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`).

`table_of(document, profile)` reads a legacy run's strobes, through the profile
that names them, into the same `ReplayTrial` rows a replayed spine run has.
Every legacy figure is then a function of those rows (`outcomes.py`,
`engagement.py`, `table_metrics.py`, `curves.py`), and each comes out exactly as
the strobe scorer reported it before the table existed
(`tests/test_legacy_pin.py`).

A row is one of two things, in stream order:

- **an odor-onset trial**: one per trigger code, ending at the next boundary
  code, as `ANALYTICS.md#boundary-codes` defines a trial;
- **a presentation that never reached odor**: a trial-light window with no
  onset in it, which only the engagement ladder counts.

Each onset's verdict (hit, miss, excluded) comes from `MetricAccumulator`, the
class Mission Control scores with, fed one strobe at a time: live ≡ offline
still holds by construction. Its outcome comes from `strobes.classify_trials`.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ....tasks.profile import TaskProfile
from ..document import _pairs_of
from ..trial_table import ReplayTrial
from . import strobes
from .trials import MetricAccumulator, boundaries_for

#: Today's outcome buckets and the classes that mean the same thing
#: (`taskdef/lowering.py`'s `OUTCOME_CLASSES`). Inverted by `legacy_outcome`.
OUTCOME_CLASS = {
    "rewarded": "correct",
    "hold_failed": "hold_broken",
    "wrong_well": "wrong_response",
    "no_response": "omission",
    "aborted": "abort_during_sampling",
}
#: A presentation the animal poked and let go of before any odor: the ladder's
#: `pokeAborted`.
POKED_NO_ODOR = "abort_before_stimulus"

#: The columns a legacy table cannot fill, named in `TrialTable.gaps`.
GAP_PHASES = "phase-entries"
GAP_COUNTS = "input-counts"
#: A no-go condition's answered trials have no outcome class: no strobe tells a
#: withhold from a false alarm in the outcome vocabulary.
GAP_NO_GO = "no-go-outcomes"
#: The profile names no reward vocabulary: no trial has an outcome.
GAP_OUTCOMES = "outcomes"
#: The profile names no trial light or odor poke: `presented` says nothing.
GAP_PRESENTATIONS = "presentations"


@dataclass(frozen=True)
class Condition:
    """One declared `liveMetrics` entry: a legacy row's `row`."""

    id: str
    label: str
    trigger: int
    window: int
    #: `left`, `right`, `withhold`, `port`, or None (`strobes.answer_side_of`).
    answer_side: str | None


@dataclass(frozen=True)
class LegacyTable:
    """A legacy run's trial table, and what its profile lets it say."""

    trials: tuple[ReplayTrial, ...]
    #: The profile's conditions, in authored order.
    conditions: tuple[Condition, ...]
    #: The profile names the reward vocabulary, so outcomes can be tallied. A run
    #: with no trials still tallies zeros when it can, and nothing when it can't.
    outcomes: bool
    #: The profile names the trial light and the odor poke.
    engagement: bool
    #: Strobes in the file, for the cumulative curve's window.
    events: int

    @property
    def gaps(self) -> tuple[str, ...]:
        out = [GAP_PHASES, GAP_COUNTS]
        if not self.outcomes:
            out.append(GAP_OUTCOMES)
        elif any(c.answer_side == "withhold" for c in self.conditions):
            out.append(GAP_NO_GO)
        if not self.engagement:
            out.append(GAP_PRESENTATIONS)
        return tuple(out)

    def to_json(self) -> dict[str, Any]:
        return {"kind": "legacy", "phases": [], "gaps": list(self.gaps),
                "trials": [t.to_json() for t in self.trials]}


def conditions_of(profile: TaskProfile | None) -> tuple[Condition, ...]:
    if profile is None:
        return ()
    return tuple(
        Condition(id=m.id, label=m.label, trigger=m.trigger_code, window=m.window_size,
                  answer_side=strobes.answer_side_of(profile, m))
        for m in profile.live_metrics
    )


def legacy_outcome(trial: ReplayTrial) -> str:
    """An onset trial's bucket in today's tally: `OUTCOME_CLASS` inverted, and a
    flagged no-go trial (no class) is `no_response`, where today counts it."""
    for bucket, name in OUTCOME_CLASS.items():
        if trial.outcome == name:
            return bucket
    return "no_response"


def table_of(document: dict[str, Any], profile: TaskProfile | None) -> LegacyTable:
    """A legacy run's document as its trial table."""
    return _table(_pairs_of(document), profile)


def table_of_codes(codes: list[int], profile: TaskProfile | None) -> LegacyTable:
    """The same, for bare codes: every time is unknown."""
    return _table([(code, None) for code in codes], profile)


def _table(pairs: list[tuple[int, int | None]], profile: TaskProfile | None) -> LegacyTable:
    codes = [code for code, _ in pairs]
    conditions = conditions_of(profile)
    if profile is None or not conditions:
        return LegacyTable((), conditions, False, False, len(codes))
    boundaries = boundaries_for(profile)
    vocab = strobes.outcome_codes(profile)
    lights, pokes = strobes.presentation_codes(profile)
    can_tally, can_engage = vocab.usable, bool(lights) and bool(pokes)

    stamps = [ts for _, ts in pairs if ts is not None]
    base = min(stamps) if stamps else None

    def ms(index: int | None) -> int | None:
        ts = pairs[index][1] if index is not None else None
        return ts - base if ts is not None and base is not None else None

    by_trigger: dict[int, list[Condition]] = {}
    for c in conditions:
        by_trigger.setdefault(c.trigger, []).append(c)
    opens = [i for i, code in enumerate(codes) if code in boundaries]
    classes = list(strobes.classify_trials(codes, boundaries, vocab)) if can_tally else None

    # The verdicts: each accumulator fed every strobe, as live. A count that
    # moves at strobe i settles the trial open before i (a success code that is
    # also a boundary settles the old trial before it opens the next).
    scores: list[dict[str, bool | None]] = [{c.id: None for c in by_trigger[codes[o]]} for o in opens]
    decided: list[int | None] = [None] * len(opens)
    accumulators = [(m.id, MetricAccumulator(m, boundaries)) for m in profile.live_metrics]
    current = -1
    for i, code in enumerate(codes):
        for mid, acc in accumulators:
            counted, hits = acc.counted_total, acc.hits_total
            acc.offer(code)
            if acc.counted_total != counted and current >= 0 and mid in scores[current]:
                scores[current][mid] = acc.hits_total != hits
                if mid == by_trigger[codes[opens[current]]][0].id:
                    decided[current] = i
        if code in boundaries:
            current += 1

    presented: set[int] = set()
    odorless: list[tuple[int, bool]] = []
    if can_engage:
        for light, poked, onset in strobes.presentations(codes, boundaries, lights, pokes):
            if onset is not None:
                presented.add(onset)
            else:
                odorless.append((light, poked))

    rows: list[tuple[int, int, ReplayTrial]] = []
    for k, o in enumerate(opens):
        condition = by_trigger[codes[o]][0]
        correct = scores[k][condition.id]
        at = ms(o)
        settle, bucket = (classes[k][1], classes[k][3]) if classes is not None else (None, None)
        outcome = OUTCOME_CLASS[bucket] if bucket is not None else None
        if bucket == "no_response" and condition.answer_side == "withhold":
            outcome = None  # withheld or a false alarm: the outcome strobes cannot say
        r = decided[k]
        withheld = condition.answer_side == "withhold" and correct
        response_ms = ms(r) if r is not None and not withheld else None
        latency = response_ms - at if response_ms is not None and at is not None else None
        rows.append((o, 0, ReplayTrial(
            index=0,
            at_ms=at,
            row=condition.id,
            row_name=condition.label,
            response=(profile.strobes.get(codes[r]) or str(codes[r])) if response_ms is not None and r is not None else None,
            response_ms=response_ms,
            latency_ms=latency if latency is None or latency >= 0 else None,
            outcome=outcome,
            outcome_ms=ms(settle),
            correct=correct,
            rewarded=bucket == "rewarded",
            reward_line=(profile.strobes.get(codes[settle]) or str(codes[settle]))
            if bucket == "rewarded" and settle is not None else None,
            reward_ms=None,
            correction=None,
            complete=True,
            presented=o in presented,
            scores=tuple(scores[k].items()),
        )))
    for light, poked in odorless:
        rows.append((light, 1, ReplayTrial(
            index=0, at_ms=ms(light), outcome=POKED_NO_ODOR if poked else None,
            correction=None, complete=True, presented=True,
        )))
    rows.sort(key=lambda r: (r[0], r[1]))
    trials = tuple(_indexed(t, i) for i, (_, _, t) in enumerate(rows))
    return LegacyTable(trials, conditions, can_tally, can_engage, len(codes))


def _indexed(trial: ReplayTrial, index: int) -> ReplayTrial:
    return replace(trial, index=index)
