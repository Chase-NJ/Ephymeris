"""What changed since an animal's previous run — `DATA.md#what-changed`.

Pure: handed a cohort's runs in chronological order, recorded and recovered
alike, returns one `RunChange` per run. The order is the caller's — session
date, then the run's own start — never session names: "10" sorts before "9" as
a string.

A **recovered** run (an adopted orphan, `DATA.md#orphan-adoption`) is compared
from what its own file records: the task from the embedded profile's hash (or
the sketch name when there is none), the parameters from the values the file
carries. Its **box** is honestly unknown — a file names only the OS port it
used, and ports renumber — so a box change is reported only between two runs
that both know theirs. A file too old to carry its parameters says so
(`paramsKnown: false`), never "changed".
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from ..sessions.models import SessionAnimalRun


@dataclass(frozen=True)
class ComparedRun:
    """One run, as much of it as can be compared."""

    id: str
    session_id: str
    animal_id: str
    box: int | None
    #: What makes two runs the same task: `hash:<profile hash>` when the
    #: declaration is known, else `name:`/`path:` — weaker, and compared by
    #: the task's name instead (`same_task`).
    task_identity: str
    task: str
    config: dict[str, Any] | None
    params_hash: str | None
    recovered: bool = False


def task_label(run: SessionAnimalRun, names: dict[str, str]) -> str:
    """The name the operator knows this run's task by."""
    if run.profile_hash and run.profile_hash in names:
        return names[run.profile_hash]
    return PurePath(run.sketch_path).name if run.sketch_path else "unknown task"


def from_recorded(run: SessionAnimalRun, names: dict[str, str]) -> ComparedRun:
    return ComparedRun(
        id=run.id,
        session_id=run.session_id,
        animal_id=run.animal_id,
        box=run.box_number,
        # The snapshot hash says exactly which declaration decoded the run; a
        # run from before snapshots only has where its sketch was.
        task_identity=f"hash:{run.profile_hash}" if run.profile_hash else f"path:{run.sketch_path}",
        task=task_label(run, names),
        config=run.config,
        params_hash=run.params_hash,
    )


def same_task(a: ComparedRun, b: ComparedRun) -> bool:
    """Two hashes compare exactly — a different hash under the same name is a
    revised definition. Anything weaker (a legacy file names only its sketch)
    compares by name, so an old file is not reported as a revised task merely
    for lacking a snapshot."""
    if a.task_identity.startswith("hash:") and b.task_identity.startswith("hash:"):
        return a.task_identity == b.task_identity
    return a.task.casefold() == b.task.casefold()


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


def compare(runs: Iterable[ComparedRun]) -> dict[str, dict[str, Any]]:
    """`RunChange` payloads keyed by run id (`PROTOCOL.md#shape-runchange`)."""
    previous: dict[str, ComparedRun] = {}
    out: dict[str, dict[str, Any]] = {}
    for run in runs:
        prior = previous.get(run.animal_id)
        previous[run.animal_id] = run
        change: dict[str, Any] = {
            "runId": run.id,
            "sessionId": run.session_id,
            "animalId": run.animal_id,
            "box": run.box,
            "task": run.task,
            "recovered": run.recovered,
            "previousRunId": prior.id if prior else None,
            "previousSessionId": prior.session_id if prior else None,
            "first": prior is None,
            "taskChange": None,
            "boxChange": None,
            "params": [],
            "paramsKnown": True,
        }
        if prior is not None:
            if not same_task(prior, run):
                change["taskChange"] = {"from": prior.task, "to": run.task}
            if prior.box is not None and run.box is not None and prior.box != run.box:
                change["boxChange"] = {"from": prior.box, "to": run.box}
            if prior.config is None or run.config is None:
                # Unrecorded parameters are unknown, never changed.
                change["paramsKnown"] = False
            elif not (prior.params_hash and prior.params_hash == run.params_hash):
                change["params"] = param_changes(prior.config, run.config)
        out[run.id] = change
    return out


def changes_for_runs(
    runs: Iterable[SessionAnimalRun], names: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Recorded runs only — `compare` over `from_recorded`."""
    return compare(from_recorded(run, names) for run in runs)
