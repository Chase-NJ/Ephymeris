"""What changed since an animal's previous run — `DATA.md#what-changed`.

Pure: handed a cohort's recorded runs, in chronological order, and the task
names their profile hashes resolve to; returns one `RunChange` per run. The
order is the caller's (`SessionRepository.runs_for_cohort`, by session date and
start), never session names — "10" sorts before "9" as a string.

Only recorded runs are compared. An adopted orphan carries no parameters and
no box assignment of its own, so a diff against one would report changes that
are really just missing knowledge.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import PurePath
from typing import Any

from ..sessions.models import SessionAnimalRun


def task_label(run: SessionAnimalRun, names: dict[str, str]) -> str:
    """The name the operator knows this run's task by."""
    if run.profile_hash and run.profile_hash in names:
        return names[run.profile_hash]
    return PurePath(run.sketch_path).name if run.sketch_path else "unknown task"


def _task_identity(run: SessionAnimalRun) -> str:
    # The snapshot hash says exactly which declaration decoded the run; a run
    # from before snapshots only has where its sketch was.
    return run.profile_hash or f"path:{run.sketch_path}"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def param_changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Key-level differences, sorted by key. An absent side is `None`."""
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if key not in before or key not in after or _canonical(old) != _canonical(new):
            changes.append({"key": key, "from": old, "to": new})
    return changes


def changes_for_runs(
    runs: Iterable[SessionAnimalRun], names: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """`RunChange` payloads keyed by run id (`PROTOCOL.md#shape-runchange`)."""
    previous: dict[str, SessionAnimalRun] = {}
    out: dict[str, dict[str, Any]] = {}
    for run in runs:
        prior = previous.get(run.animal_id)
        previous[run.animal_id] = run
        change: dict[str, Any] = {
            "runId": run.id,
            "sessionId": run.session_id,
            "animalId": run.animal_id,
            "box": run.box_number,
            "task": task_label(run, names),
            "previousRunId": prior.id if prior else None,
            "previousSessionId": prior.session_id if prior else None,
            "first": prior is None,
            "taskChange": None,
            "boxChange": None,
            "params": [],
            "paramsKnown": True,
        }
        if prior is not None:
            if _task_identity(prior) != _task_identity(run):
                change["taskChange"] = {
                    "from": task_label(prior, names),
                    "to": task_label(run, names),
                }
            if prior.box_number != run.box_number:
                change["boxChange"] = {"from": prior.box_number, "to": run.box_number}
            if prior.config is None or run.config is None:
                # Pre-v6 runs recorded no parameters. Unknown is not changed.
                change["paramsKnown"] = False
            elif not (
                prior.params_hash and prior.params_hash == run.params_hash
            ):
                change["params"] = param_changes(prior.config, run.config)
        out[run.id] = change
    return out
