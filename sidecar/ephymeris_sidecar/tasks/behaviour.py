"""What a spine task's `profile_hash` covers: its behaviour, never its words.

`TASKS.md#profile-and-params-hashes`. A spine profile's hash covers what the
board runs and how replay scores it, so renaming a condition or rewording help
text keeps one history (ADR 0003, *Hashes and data*).

THE LIST IS OF WHAT IS LEFT OUT, NOT OF WHAT IS KEPT. Anything not named in
`UNHASHED` is hashed, so a field added to a row, a phase or a block later is
behaviour by default. A string meant for a person joins the list deliberately,
by path, and `tests/test_behaviour_hash.py` pins the list and walks every leaf
of a generated profile against it.

Paths, not key names: a `name` on a row is a person's word, but a `name` added
anywhere else is hashed until someone says otherwise here.
"""

from __future__ import annotations

from typing import Any

#: Any list element or dict value, in an `UNHASHED` path.
ANY = "*"

#: Every string meant for a person in a spine profile's `to_json`, by path.
#: `strobes` is not here: `profile_hash` leaves it out of every profile, for
#: a different reason (`TASKS.md#profile-and-params-hashes`).
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


def behaviour(declaration: dict[str, Any]) -> dict[str, Any]:
    """`declaration` less every `UNHASHED` path, with the spine's rows keyed by id.

    A new structure; `declaration` is not changed. Keyed by id, reordering
    rows moves nothing: what a block draws is its own ordered `rows` list.
    """
    out = _without(declaration, sorted(UNHASHED))
    spine = out.get("spine")
    if isinstance(spine, dict) and isinstance(spine.get("rows"), list):
        spine["rows"] = _keyed_by_id(spine["rows"])
    return out


def _without(value: Any, paths: list[tuple[str, ...]]) -> Any:
    """`value`, deep-copied, with each path that ends here removed."""
    if not paths:
        return _copy(value)
    if isinstance(value, dict):
        out = {}
        for key, child in value.items():
            if (key,) in paths or (ANY,) in paths:
                continue
            out[key] = _without(child, _below(paths, key))
        return out
    if isinstance(value, list):
        if (ANY,) in paths:
            return []
        return [_without(child, _below(paths, ANY)) for child in value]
    return value


def _below(paths: list[tuple[str, ...]], step: str) -> list[tuple[str, ...]]:
    """The rest of each path whose first step matches `step` (a key, or any)."""
    return [p[1:] for p in paths if len(p) > 1 and p[0] in (step, ANY)]


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


def _keyed_by_id(rows: list[Any]) -> Any:
    """`{id: row less its id}`, or the list as it is when an id is missing or
    repeated: a mapping would then drop a row, and two different tasks would
    hash the same."""
    ids = [r.get("id") if isinstance(r, dict) else None for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        return rows
    return {r["id"]: {k: v for k, v in r.items() if k != "id"} for r in rows}
