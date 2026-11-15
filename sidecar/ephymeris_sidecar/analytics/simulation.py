"""What `tasks.simulate` serves (`TASKS.md#simulating-a-spine-task`).

One simulated run of an unsaved spine definition, scored by the calls Analytics
makes for a recorded one (`summarize`, `series`, `trial_table_of`), plus what
only a simulation asks: where the blocks switched, and which rows no trial drew.
"""

from __future__ import annotations

from typing import Any

from ..taskdef import generate
from ..taskdef.model import TaskDefinition
from . import stream
from .stream.simulate import DEFAULT_LIMIT_MS, Animal, simulate

__all__ = ["DEFAULT_LIMIT_MS", "Animal", "payload"]

#: What a simulation serves of the run's `RunSummary`: its scores, not the
#: fields a recorded run has (a box, a file, a profile source).
SCORED = ("status", "detail", "metrics", "overall", "replay")


def payload(definition: TaskDefinition, animal: Animal, seed: int, *,
            limit_ms: int = DEFAULT_LIMIT_MS) -> dict[str, Any]:
    """Simulate `definition` against `animal` and report it. Blocking: the
    caller runs it off the loop. Raises ValueError for an animal it cannot be."""
    assert definition.spine is not None
    profile = generate.build_profile(definition)
    result = simulate(profile.to_json(), animal, seed, limit_ms=limit_ms)
    document = result.document
    table = stream.trial_table_of(document, profile)
    trials = table["trials"] if table is not None else []
    summary = stream.summarize(document, profile).to_json()
    return {
        "seed": seed,
        "limitMs": limit_ms,
        "endedBy": result.ended_by,
        **{key: summary[key] for key in SCORED},
        "series": [m.to_json() for m in stream.series(document, profile)],
        "trialTable": table,
        "switches": switches(trials),
        "absent": absent(definition, trials),
    }


def switches(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each trial that runs in another block than the one before it, the first included."""
    out: list[dict[str, Any]] = []
    for t in trials:
        if not out or t["block"] != out[-1]["block"]:
            out.append({"index": t["index"], "block": t["block"]})
    return out


def absent(definition: TaskDefinition, trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every row of the definition no simulated trial drew, with the blocks that list it."""
    spine = definition.spine
    assert spine is not None
    drawn = {t["row"] for t in trials}
    return [{"rowId": row.id, "name": row.name, "blocks": [b.id for b in spine.blocks if row.id in b.rows]}
            for row in spine.rows if row.id not in drawn]
