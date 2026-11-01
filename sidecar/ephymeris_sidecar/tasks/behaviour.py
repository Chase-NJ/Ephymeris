"""What a spine task's `profile_hash` covers: its behaviour, never its words.

`TASKS.md#a-spine-tasks-hash-covers-behaviour-only` says what is left out and
why (`0003-phase-spine-task-model.md#hashes-and-data`). The list below is of
what is LEFT OUT, by path: anything not on it is hashed, so a field added to a
row, a phase or a block later is behaviour until someone lists it here.
"""

from __future__ import annotations

import copy
from typing import Any

#: Any list element, in an `UNHASHED` path. A dict step is always a key.
ANY = "*"

#: Every string meant for a person in a spine profile's `to_json`, by path. A
#: listed path leaves out everything beneath it. Not here: `strobes`, which
#: `profile_hash` leaves out of every profile, and `taskName`, which is the
#: task's identity and hashed.
UNHASHED: frozenset[tuple[str, ...]] = frozenset({
    ("legacyNames",),
    # The generator writes a row's name into its reward fields' labels.
    ("config", ANY, "label"),
    ("config", ANY, "help"),
    ("config", ANY, "group"),
    ("config", ANY, "unit"),
    ("liveMetrics", ANY, "label"),
    ("spine", "rows", ANY, "name"),
})


def behaviour_of(declaration: dict[str, Any]) -> dict[str, Any]:
    """`declaration` less every `UNHASHED` path, with the spine's rows keyed by id.

    A new structure; `declaration` is not changed. Keyed by id, reordering
    `spine.rows` moves nothing: what a block draws is its own ordered `rows`.
    """
    out = _without(declaration, sorted(UNHASHED))
    spine = out.get("spine")
    if isinstance(spine, dict) and isinstance(spine.get("rows"), list):
        spine["rows"] = _keyed_by_id(spine["rows"])
    return out


def _without(value: Any, paths: list[tuple[str, ...]]) -> Any:
    """`value`, deep-copied, with each path that ends at one of its keys removed."""
    if not paths:
        return copy.deepcopy(value)
    if isinstance(value, dict):
        return {key: _without(child, _below(paths, key))
                for key, child in value.items() if (key,) not in paths}
    if isinstance(value, list):
        return [_without(child, _below(paths, ANY)) for child in value]
    return value


def _below(paths: list[tuple[str, ...]], step: str) -> list[tuple[str, ...]]:
    """The rest of each path whose first step is `step`: a dict's key, or `ANY` for a list's element."""
    return [p[1:] for p in paths if len(p) > 1 and p[0] == step]


def _keyed_by_id(rows: list[Any]) -> Any:
    """`{id: row less its id}`, or the list as it is when an id is missing or
    repeated: a mapping would then drop a row, and two different tasks would
    hash the same."""
    ids = [r.get("id") if isinstance(r, dict) else None for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return rows
    return {r["id"]: {k: v for k, v in r.items() if k != "id"} for r in rows}
