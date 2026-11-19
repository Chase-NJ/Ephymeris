"""The trial table's row, and the outcome classes it is scored by
(`ANALYTICS.md#the-trial-table`).

Every run becomes one table of `ReplayTrial` rows: a stream-grammar-2 run's
from its headers and outcome codes (`grammar2.py`), a grammar-1 run's from the
legacy decoder (`legacy/decode.py`). Every number is read off the rows.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The outcome classes a trial can end in. Append only: a class's name is
#: written into every derived trial table (`DATA.md#the-trial-table`).
OUTCOME_CLASSES = (
    "correct",
    "wrong_response",
    "hold_broken",
    "omission",
    "withheld",
    "false_alarm",
    "abort_before_stimulus",
    "abort_during_sampling",
)

CORRECT = "correct"

#: The version of the derived trial table a run's `.json` and `.mat` carry, as
#: their block's `replay_version` (`DATA.md#the-trial-table`). **Bump it
#: whenever a run's trial table would change**: a column added, removed or read
#: differently, here or in a grammar-2 run's `grammar2.TrialRow`.
#: `test_derived_trials.py` pins a fingerprint of fixed runs' tables; when it
#: fails, bump this and update the pin. Not `scoring.SCORE_VERSION`: the cache
#: never holds a trial table, so a table change need not make every machine
#: re-read its archive.
REPLAY_VERSION = 5

#: The outcome classes a trial is right in, for P(correct)
#: (`ANALYTICS.md#metrics-from-the-trial-table`). A withhold is a no-go
#: condition's correct answer, so a perfect go/no-go session scores 1.0. Every
#: other class (false alarm, wrong response, omission, hold broken, one added
#: later) is a miss, except the aborts in `EXCLUDED`; those and a trial with no
#: class are excluded.
HITS = frozenset(("correct", "withheld"))

#: The classes a trial is excluded in: an abort is neither right nor wrong. It
#: still counts on the engagement ladder.
EXCLUDED = frozenset(("abort_before_stimulus", "abort_during_sampling"))


def correct_of(outcome: str | None) -> bool | None:
    """A trial's `correct` from its outcome class: in `HITS`, a miss, or None
    (no class, or `EXCLUDED`)."""
    if outcome is None or outcome in EXCLUDED:
        return None
    return outcome in HITS


# --- the row the wire carries ---------------------------------------------------


@dataclass(frozen=True)
class InputCount:
    """Watched rises of one input channel during one phase of a trial."""

    phase: int
    channel: str
    count: int

    def to_json(self) -> dict[str, object]:
        return {"phase": self.phase, "channel": self.channel, "count": self.count}


@dataclass(frozen=True)
class ConditionScore:
    """A legacy trial's verdict under one condition its onset opens."""

    condition: str
    #: A hit, a miss, or None for excluded.
    correct: bool | None

    def to_json(self) -> dict[str, object]:
        return {"condition": self.condition, "correct": self.correct}


@dataclass(frozen=True)
class ReplayTrial:
    """One row of the trial table (`ANALYTICS.md#the-trial-table`), a
    grammar-2 run's and a decoded legacy run's alike
    (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`). Its columns are
    written into every derived table, so a column no decoder fills
    (`phase_entries`, `input_counts`, `counter_n`) stays. Every value is plain
    (numbers, strings, booleans, None, and lists of them or of flat objects), so a
    row serialises as is."""

    index: int
    #: None only on a legacy file with no usable clock.
    at_ms: int | None
    block: str | None = None
    row: str | None = None
    row_name: str | None = None
    level: float | None = None
    phase_entries: tuple[int | None, ...] = ()
    response: str | None = None
    response_edge: str | None = None
    response_ms: int | None = None
    latency_ms: int | None = None
    outcome: str | None = None
    #: When the outcome was settled: its outcome strobe.
    outcome_ms: int | None = None
    #: Right, wrong, or not scored (None): `outcome` in `HITS` on a grammar-2
    #: run, the hit or miss of its condition on a legacy one.
    correct: bool | None = None
    rewarded: bool = False
    reward_line: str | None = None
    reward_ms: int | None = None
    #: None when the run cannot say, as a legacy run cannot.
    correction: bool | None = False
    input_counts: tuple[InputCount, ...] = ()
    #: Never filled: no task has a counter.
    counter_n: int | None = None
    complete: bool = True
    #: The trial opens a presentation on the engagement ladder.
    presented: bool = True
    #: The trial's verdict under every condition its onset opens: one, unless
    #: a profile declares two conditions on one onset.
    scores: tuple[ConditionScore, ...] = ()

    def scored(self, condition: str) -> bool:
        """The trial was scored under `condition`: its onset opens it."""
        return any(s.condition == condition for s in self.scores)

    def verdict(self, condition: str) -> bool | None:
        """Its hit or miss under `condition`, or None (excluded, or not scored under it)."""
        return next((s.correct for s in self.scores if s.condition == condition), None)

    def to_json(self) -> dict[str, object]:
        return {
            "index": self.index,
            "atMs": self.at_ms,
            "block": self.block,
            "row": self.row,
            "rowName": self.row_name,
            "level": self.level,
            "phaseEntries": list(self.phase_entries),
            "response": self.response,
            "responseEdge": self.response_edge,
            "responseMs": self.response_ms,
            "latencyMs": self.latency_ms,
            "outcome": self.outcome,
            "outcomeMs": self.outcome_ms,
            "correct": self.correct,
            "rewarded": self.rewarded,
            "rewardLine": self.reward_line,
            "rewardMs": self.reward_ms,
            "correction": self.correction,
            "inputCounts": [c.to_json() for c in self.input_counts],
            "counterN": self.counter_n,
            "complete": self.complete,
            "presented": self.presented,
            "scores": [s.to_json() for s in self.scores],
        }
