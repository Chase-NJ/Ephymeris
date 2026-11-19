"""A run's odors table — `DATA.md#the-odors-table`.

One row per odor line a trial type presents: its line, the operator's name
for it, its onset code, the side it rewards, how long its reward valve opens
and its weight in the pool. The one home for "which odor, which well, how
much".

Built from the run's own profile snapshot and its parameters and nothing
else, so a recovered or copied file has the table its original has. Never
from the stream: what an odor rewards is what the task said, not what the
animal did.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ...sessions.run_document import params_of, with_odors
from ...tasks.profile import TaskProfile, embedded_profile
from .legacy.strobes import answer_side_of

#: An odor line's onset strobe, and the line it names (`TASKS.md#onset-codes`).
ONSET = re.compile(r"^ODOR_(\d+)_ON$")

#: A row's columns, in order; `sessions/matwriter.py` writes one field per column.
COLUMNS = ("line", "name", "onset_code", "side", "reward_ms", "pool_weight")

#: What a grammar-1 profile's answer side is called here: the trial header's
#: words (`tasks/profile.py`'s `TRIAL_SIDES`).
_SIDES = {"left": "left", "right": "right", "withhold": "no_go"}


def odor_table(profile: TaskProfile | None, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The odors table of a run of `profile` on `params`, by `metadataKey`.

    From the profile's `trialTypes` (`TASKS.md#trial-types-in-the-profile`)
    where it has them. A profile from before that key gives what its success
    codes prove (`_proven`), and one that proves nothing gives no rows.
    """
    if profile is None:
        return []
    if profile.trial_types is None:
        return _proven(profile)
    codes = {name: code for code, name in profile.strobes.items()}
    return [_row(trial, codes, params) for trial in profile.trial_types]


def _row(trial: Mapping[str, Any], codes: Mapping[str, int], params: Mapping[str, Any]) -> dict[str, Any]:
    onset, side = trial.get("onset"), trial.get("side")
    return {
        "line": _line(onset),
        "name": trial.get("name") if isinstance(trial.get("name"), str) else None,
        "onset_code": codes.get(onset) if isinstance(onset, str) else None,
        "side": side,
        # A no-go odor pays nothing. A go odor pays what the run was sent, and
        # None when the run records no value for its key.
        "reward_ms": 0 if side == "no_go" else _value(params, trial.get("rewardKey")),
        "pool_weight": _value(params, trial.get("weightKey")),
    }


def _proven(profile: TaskProfile) -> list[dict[str, Any]]:
    """The rows a profile with no `trialTypes` can prove: one per live metric
    that opens on an odor's onset and whose success code names a well or the
    withhold (`legacy/strobes.answer_side_of`), as profiles from before stream
    grammar 2 do. Its reward and weight are not known from here."""
    rows: dict[int, dict[str, Any]] = {}
    for metric in profile.live_metrics:
        side = _SIDES.get(answer_side_of(profile, metric) or "")
        line = _line(profile.strobes.get(metric.trigger_code))
        if side is None or line is None or line in rows:
            continue
        _, bar, stimulus = metric.label.rpartition(" | ")
        rows[line] = {
            "line": line,
            "name": stimulus.rstrip(")").strip() if bar else "",
            "onset_code": metric.trigger_code,
            "side": side,
            "reward_ms": None,
            "pool_weight": None,
        }
    return list(rows.values())


def _line(onset: Any) -> int | None:
    match = ONSET.match(onset) if isinstance(onset, str) else None
    return int(match.group(1)) if match else None


def _value(params: Mapping[str, Any], key: Any) -> Any:
    return params.get(key) if isinstance(key, str) else None


def with_odor_table(document: dict[str, Any]) -> dict[str, Any]:
    """A version-2 `document` with the odors table its own snapshot and
    parameters give."""
    return with_odors(document, odor_table(embedded_profile(document), params_of(document)))
