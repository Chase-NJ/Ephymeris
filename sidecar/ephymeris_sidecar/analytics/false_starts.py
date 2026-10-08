"""False starts: runs an animal restarted before they got going — `DATA.md#false-starts`.

A box is started, something is wrong (the wrong animal, a dry line, a door
left open), it is stopped within a minute or two and started again. Both runs
are real files and both are real runs, and DATA.md#edge-cases forbids any view
silently keeping one of them. But counting the first one makes every
per-session figure lie a little: a second point on the strategy plane, a
second curve, an unweighted session mean dragged by a run of three trials, and
a "what changed" that diffs the real run against the aborted one and calls it
unchanged.

So a false start is **set aside, never hidden**: left out of every metric and
every comparison, still listed — muted and labelled — wherever runs are listed.

THE RULE IS TWO CONDITIONS, AND BOTH ARE REQUIRED:

1. **Restarted** — a later run of the same animal exists in the same session.
   A run nobody restarted is the animal's session, however short; an animal
   that quit after four trials is data, not a false start.
2. **Short** — fewer than `MAX_TRIALS` trials (odor onsets, `TrialOutcomes.trials`).
   A long first run interrupted for a real reason keeps counting.

A run whose trial count is unknown (no profile could score it) is never set
aside automatically: "I couldn't tell" must fail toward counting. A person can
always decide otherwise — `run_flags` holds per-run overrides, in both
directions, and an override beats the rule.

Pure: facts in, verdicts out. The service gathers the facts from wherever it
has them (a fresh index, or the cache for the session log).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..sessions.paths import parse_name_time

#: Fewer trials than this, and restarted, is a false start. The same number as
#: the cohort's default minimum for trusting a rate (`DEFAULT_MIN_COUNTED`) —
#: below it a run says nothing reliable on its own anyway — but declared here,
#: because a cohort raising its reliability threshold must not start setting
#: aside runs it used to count.
MAX_TRIALS = 10


@dataclass(frozen=True)
class RunFacts:
    """What the rule needs to know about one run."""

    run_id: str
    session_id: str
    animal_id: str
    #: Sortable within one session. See `order_key`.
    order: str
    #: Odor-onset trials, or None when no profile could score the run.
    trials: int | None


@dataclass(frozen=True)
class Verdict:
    """Whether one run is set aside, and on whose word."""

    run_id: str
    #: What the rule says.
    automatic: bool
    #: What a person said, when someone did: True marked it, False restored it.
    override: bool | None
    #: The run that restarted this one — the next run of the same animal in
    #: the same session — or None when nothing did.
    restarted_by: str | None

    @property
    def false_start(self) -> bool:
        return self.override if self.override is not None else self.automatic

    @property
    def source(self) -> str | None:
        """`automatic`, `marked` or `restored` — why the run is (or isn't) set
        aside, when that is anything but the default of counting it."""
        if self.override is True:
            return "marked"
        if self.override is False and self.automatic:
            return "restored"
        if self.override is None and self.automatic:
            return "automatic"
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "falseStart": self.false_start,
            "falseStartSource": self.source,
            "restartedBy": self.restarted_by,
        }


def order_key(file_path: str | None, started_at: str | None) -> str:
    """The start time a run's FILE was named with, else the row's own.

    Not `started_at` alone: a recorded run stamps UTC with an offset and an
    adopted one a naive local time from its folder, and one session can hold
    both (a recovered file beside its recorded siblings). Every file stem
    carries the local `HHMMSS` it was opened at (`DATA.md#names`), which
    compares like with like.
    """
    stamp = parse_name_time(file_path) if file_path else None
    return stamp or (started_at or "")


def trials_of(summary: Mapping[str, Any] | None) -> int | None:
    """Odor-onset trials out of a cached `RunSummary`, or None if unscored.

    `outcomes.trials` when the profile could tally outcomes; otherwise the sum
    of the live metrics' `triggered` counts, which are the same onsets counted
    per condition (a profile need not name its reward codes to score a
    metric). Neither: None, and the rule counts the run.
    """
    summary = summary or {}
    outcomes = summary.get("outcomes")
    if isinstance(outcomes, Mapping) and _is_count(outcomes.get("trials")):
        return outcomes["trials"]
    metrics = summary.get("metrics")
    if isinstance(metrics, list) and metrics:
        triggered = [m.get("triggered") for m in metrics if isinstance(m, Mapping)]
        if triggered and all(_is_count(t) for t in triggered):
            return sum(triggered)
    return None


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def classify(
    runs: Iterable[RunFacts], overrides: Mapping[str, bool] | None = None
) -> dict[str, Verdict]:
    """A verdict for every run, keyed by run id."""
    overrides = overrides or {}
    by_pair: dict[tuple[str, str], list[RunFacts]] = {}
    for run in runs:
        by_pair.setdefault((run.session_id, run.animal_id), []).append(run)

    out: dict[str, Verdict] = {}
    for group in by_pair.values():
        group.sort(key=lambda r: (r.order, r.run_id))
        for index, run in enumerate(group):
            later = group[index + 1] if index + 1 < len(group) else None
            automatic = (
                later is not None and run.trials is not None and run.trials < MAX_TRIALS
            )
            out[run.run_id] = Verdict(
                run_id=run.run_id,
                automatic=automatic,
                override=overrides.get(run.run_id),
                restarted_by=later.run_id if later is not None else None,
            )
    return out
