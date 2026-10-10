"""The rig definition: the rig wiring plus the strobe vocabulary in force.

Both halves feed every generated `TaskPins.h`, so they are owned together
(TASKS.md#the-rig-definition, GLOSSARY.md#rig-definition).
"""

from __future__ import annotations

from typing import Any

from . import registry


def impact_of(
    tasks: Any, *, wiring: dict | None = None, vocabulary: dict | None = None
) -> list[dict[str, Any]]:
    """Which stored task profiles a hypothetical rig definition would newly break.

    COMPUTED BEFORE THE WRITE, which is the whole point. Full channel authoring
    means an operator can delete a channel a saved task binds, and retiring a
    code can strand a task that emits it; catching either at generation time
    would be too late -- the document is written by then and the task already
    broken.

    NEWLY is load-bearing. A task already failing for its own reasons is not
    this change's fault, and listing it would bury the ones that are -- so each
    profile is validated under BOTH definitions and only the difference is
    reported.

    The hypothetical is context-local (`registry.hypothetical`), so nothing else
    reading the rig definition meanwhile can see it.

    `tasks` is the task-profile store: `list_entries()` and `failures(id)`, the
    latter reading the rig definition in force. It is None until one exists, and
    an empty answer on a rig with no profiles is the honest answer either way.
    """
    if tasks is None:
        return []
    entries = list(tasks.list_entries())
    if not entries:
        return []

    before = {e["id"]: tasks.failures(e["id"]) for e in entries}
    with registry.hypothetical(rig=wiring, vocabulary=vocabulary):
        after = {e["id"]: tasks.failures(e["id"]) for e in entries}

    out: list[dict[str, Any]] = []
    for entry in entries:
        gained = sorted(after[entry["id"]] - before[entry["id"]])
        if gained:
            out.append({"specId": entry["id"], "label": entry.get("label"), "codes": gained})
    return out
