"""The presentation overlay, and the one definition of location normalisation.

NOTHING IN THE COMPILER IMPORTS THIS. It exists for a GUI: the schema says what is
legal, this says what a field is called and which widget edits it. Keeping the two
side by side is the point -- a field added to the schema needs a label the same day,
and tests/test_presentation_covers_schema.py fails if it does not get one.

`normalize_location` is here rather than in the consuming app because a diagnostic's
location and an overlay key have to agree exactly, and two implementations of an
agreement are one implementation and one bug waiting. The app calls this and puts the
result on the wire; the frontend does a dictionary lookup and no parsing at all.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .paths import PRESENTATION_SCHEMA as PRESENTATION_PATH  # noqa: F401

#: YAML arrays whose diagnostics address entries by their `id` field rather than by
#: index -- `contingency.trial_types.go_right.stages`, not `[2].stages`. The rules
#: chose ids because an index means nothing to someone reading the message, and it
#: has the happy consequence that a row's identity survives being reordered.
ID_ADDRESSED = ("contingency.stimuli", "contingency.trial_types")

#: A node id from the graph and capacity rules (TG4xx, TG5xx, TG901).
NODE_RE = re.compile(r"^S\d+$")

#: `stage_schedule[at_trial=20]` -- a selector rather than an index, from TG507.
SELECTOR_RE = re.compile(r"^(?P<head>[a-z_.]+)\[[a-z_]+=[^\]]*\]$")

_INDEX_RE = re.compile(r"\[\d+\]")


@lru_cache(maxsize=1)
def presentation() -> dict:
    return json.loads(PRESENTATION_PATH.read_text())


def normalize_location(location: str | None) -> str | None:
    """A concrete diagnostic location -> the overlay key that names it.

    Returns None for anything that does not address a field: a node id, the root,
    a registry filename, a selector-addressed row, or no location at all. Callers
    must handle that -- a diagnostic with nowhere to land belongs in the panel, and
    silently dropping it is the failure mode worth avoiding.
    """
    if not location or location == "(root)":
        return None
    if NODE_RE.match(location) or location.endswith(".json") or SELECTOR_RE.match(location):
        return None

    # `timing[3].ms` -> `timing[].ms`. Done first so an index cannot be mistaken
    # for a map key by the pass below.
    path = _INDEX_RE.sub("[]", location)

    parts = path.split(".")
    out: list[str] = []
    prefix = ""
    i = 0
    while i < len(parts):
        part = parts[i]
        candidate = f"{prefix}.{part}" if prefix else part
        out.append(part)
        prefix = candidate
        # The segment after a map or an id-addressed array is an instance name, not
        # a schema key, so it collapses to a wildcard.
        if is_keyed_collection(prefix) and i + 1 < len(parts):
            out.append("*")
            prefix = f"{prefix}.*"
            i += 1
        i += 1
    return ".".join(out)


def is_keyed_collection(path: str) -> bool:
    """Whether the segment after `path` names an instance rather than a schema key.

    True for a map (`contingency.ports.left_well`), for the outcome map's seven
    classes, and for the two arrays whose diagnostics address entries by `id`.
    """
    if path in ID_ADDRESSED:
        return True
    return presentation()["sections"].get(path, {}).get("rows") in ("by_key", "by_id")


def field(key: str) -> dict | None:
    """The overlay entry for a normalised key."""
    return presentation()["fields"].get(key)


def placement(location: str | None) -> tuple[str, str | None]:
    """Where a diagnostic belongs on screen: (kind, anchor).

    Five kinds, which is one more than the obvious four -- a row-level location
    like `contingency.outcome_map.correct` names an instance rather than one of its
    fields, and belongs on that row's header:

        field     the normalised overlay key       inline, next to the input
        row       the collection, e.g. `...outcome_map.*`   on the row header
        section   the collection path              on the section header
        node      the node id, e.g. `S17`          in the graph pane
        document  None                             the panel above the form

    `document` is the catch-all and is never wrong, only unhelpful. Nothing returns
    "nowhere": a diagnostic that reaches no reader is the failure this exists to
    prevent, and tests/test_locations_are_addressable.py asserts the mapping stays
    total over the whole broken corpus.
    """
    if not location or location == "(root)":
        return "document", None
    if NODE_RE.match(location):
        return "node", location
    if location.endswith(".json") or SELECTOR_RE.match(location):
        return "document", None

    key = normalize_location(location)
    if key is None:
        return "document", None
    if field(key):
        return "field", key

    sections = presentation()["sections"]
    if key in sections:
        return "section", key
    if key.endswith(".*") and key[: -len(".*")] in sections:
        return "row", key[: -len(".*")]

    # A path under a known section that names no declared field -- a key that must
    # not exist. TG103's `nodes` and TG101's `topology.True` (the YAML `on:` trap,
    # where the offending key parsed as a boolean) both land here. Anchor them on
    # the nearest section so the reader is at least sent to the right part of the
    # document.
    head = key.rsplit(".", 1)[0]
    if head in sections:
        return "section", head
    return "document", None
