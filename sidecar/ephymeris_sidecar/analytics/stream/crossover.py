"""A spine run's trial table in the legacy shapes (`ANALYTICS.md#a-spine-run-on-the-cross-session-panels`).

The cross-session panels read `TrialOutcomes`, `ConditionOutcomes` and
`TrialEngagement`, which a legacy run gets from its decoder. A spine run gets
them here, from its replayed trial table and its own snapshot, so one animal's
history reads across the cutover:

    outcomes, conditions, engagement = tallies(result, snapshot_spine)

A trial is RIGHT when its response is the row's one response mapped `correct`
(a row with none or several, such as a bandit's, is read by its class). So a
broken hold at the wrong well is a wrong well, as legacy P(hit) scores the
first well poked. Engagement reads a trial's phase entries: the one place in
analytics that reads a phase's position, and the reason is that a spine run
has no light or poke code to delimit a presentation by
(`ANALYTICS.md#a-spine-run-on-the-cross-session-panels`).

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

from .engagement import TrialEngagement
from .outcomes import ConditionOutcomes, TrialOutcomes
from .spine import Replayed
from .table_metrics import row_metric_id
from .trial_table import CORRECT, ReplayTrial

#: Each spine class's legacy bucket when the response is right, and when it is not.
_RIGHT = {CORRECT: "rewarded", "hold_broken": "hold_failed"}
_BY_CLASS = {"wrong_response": "wrong_well", "omission": "no_response", "withheld": "withheld",
             "false_alarm": "false_alarm", "abort_during_sampling": "aborted"}


def bucket_of(trial: ReplayTrial, correct: str | None) -> str | None:
    """The legacy bucket of one trial: `rewarded`, `unpaid`, `hold_failed`,
    `wrong_well`, `no_response`, `withheld`, `false_alarm` or `aborted`; None
    for a trial no legacy tally counts (an abort before the stimulus, or one
    with no class). `correct` is the row's one correct response's channel, or
    None when the row has no one."""
    outcome = trial.outcome
    if outcome in _RIGHT:
        if correct is not None and trial.response != correct:
            return "wrong_well"
        if outcome == CORRECT:
            return "rewarded" if trial.rewarded else "unpaid"
        return "hold_failed"
    return _BY_CLASS.get(outcome or "")


def _tally(buckets: Iterable[str | None]) -> TrialOutcomes:
    counts = Counter(b for b in buckets if b is not None)
    return TrialOutcomes(
        trials=sum(counts.values()),
        # As the legacy tally does, the administered trials are every answered
        # or unanswered one; an abort during sampling is not among them.
        administered=sum(n for b, n in counts.items() if b != "aborted"),
        rewarded=counts["rewarded"],
        hold_failed=counts["hold_failed"],
        wrong_well=counts["wrong_well"],
        no_response=counts["no_response"],
        aborted=counts["aborted"],
        unpaid=counts["unpaid"],
        withheld=counts["withheld"],
        false_alarm=counts["false_alarm"],
    )


def _correct_channels(spine: dict[str, Any]) -> dict[str, str | None]:
    """Each row's one response mapped correct, as the channel it binds; None for none or several."""
    window = next((p for p in spine.get("spine") or [] if p.get("phase") == "response"), None)
    out: dict[str, str | None] = {}
    for row in spine.get("rows") or []:
        rmap = row.get("map") or {}
        keys = [k for k in (window or {}).get("responses", []) if (rmap.get(k) or {}).get("outcome") == CORRECT]
        out[str(row.get("id"))] = (row.get("bind") or {}).get(keys[0]) if len(keys) == 1 else None
    return out


def _engagement(trials: Sequence[ReplayTrial], phases: Sequence[str]) -> TrialEngagement | None:
    """The ladder off each trial's phase entries: presented, past the engaging
    Wait (the first, before the first Present), and into the first Present.
    None for a spine with no such Wait and Present."""
    present = next((i for i, kind in enumerate(phases) if kind == "present"), None)
    if present is None:
        return None
    wait = next((i for i, kind in enumerate(phases[:present]) if kind == "wait"), None)
    if wait is None:
        return None

    iti = len(phases) - 1  # every trial, an early end's included, enters its ITI

    def past(t: ReplayTrial, phase: int) -> bool:
        """The trial entered `phase` or a phase after it, before the ITI."""
        return any(entry is not None for entry in t.phase_entries[phase:iti])

    return TrialEngagement(presented=len(trials), poked=sum(past(t, wait + 1) for t in trials),
                           odor_delivered=sum(past(t, present) for t in trials))


def tallies(result: Replayed, spine: dict[str, Any]) -> tuple[TrialOutcomes | None, list[ConditionOutcomes],
                                                             TrialEngagement | None]:
    """A replayed spine run's `TrialOutcomes`, per-row `ConditionOutcomes` and
    `TrialEngagement`. The outcomes and conditions are None and empty for a
    spine with no Response window, which answers nothing; every count is over
    complete trials only."""
    trials = [t for t in result.trials if t.complete]
    engagement = _engagement(trials, result.phases)
    if "response" not in result.phases:
        return None, [], engagement
    correct = _correct_channels(spine)
    side = {i.get("channel"): i.get("side") for i in spine.get("inputs") or []}
    bucket = [(t, bucket_of(t, correct.get(t.row or ""))) for t in trials]
    conditions = [
        ConditionOutcomes(metric_id=row_metric_id(row_id), label=name, trigger_code=None,
                          outcomes=_tally(b for t, b in bucket if t.row == row_id),
                          answer_side=side.get(correct.get(row_id)))
        for row_id, name in result.rows
    ]
    return _tally(b for _, b in bucket), conditions, engagement
