"""Edge codes: the strobe codes a channel-set save allocates (TASKS.md#edge-codes).

Every edge of every channel names the vocabulary code that announces it
(`edges: {"on": "FLUID_2_ON", ...}`). A channel whose edge has no code yet gets
one when the channel set is saved: `plan` says which, and `issue` appends them
to the vocabulary. Both run inside the same rig definition write as the wiring
(`RigDefinition.save_wiring`), and `hardware.preview` runs `plan` alone so the
save preview can list what a save would issue.

THE NAME IS CHOSEN ONCE, then it is data. A code is named `<CHANNEL>_<EDGE>` on
the day it is issued and stored inside the channel's entry, so renaming the
channel carries its codes with it and renames none of them. Deriving the code
from the name at each read is the mistake `generate._onset_macro` records.

APPEND ONLY (TASKS.md#append-only). A name the vocabulary ever gave to anything
else -- live or retired -- is never reused; the plan suffixes `_2`, `_3`, ...
instead. The one name a plan takes back is a live code this allocator issued
(`CHANNEL_SET_ORIGIN`) under exactly the name it would issue, to an edge no
channel in the document holds: a channel set reset to the shipped one, or a
channel deleted and added back. Issuing it again under `_2` would only grow
the vocabulary by codes that mean the same thing.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from ..strobes import store as strobe_store
from . import registry

#: The `origin` a code issued here carries in the vocabulary.
CHANNEL_SET_ORIGIN = "channel_set"


@dataclass(frozen=True)
class Allocation:
    """One code a save issues (`RigAllocation` on the wire)."""

    channel: str
    edge: str
    name: str
    code: int

    def to_json(self) -> dict[str, Any]:
        return {"channel": self.channel, "edge": self.edge, "name": self.name, "code": self.code}


def plan(document: Any, vocab: registry.Vocabulary) -> tuple[Any, list[Allocation]]:
    """The document with every missing edge code filled, and what that issues.

    Pure: the input is never edited and nothing is written. Channels are taken
    in declaration order and each one's edges in its type's order, and each new
    code takes the lowest number still free, so one document always plans the
    same codes against one vocabulary. A document that is not the right shape
    plans nothing; the schema reports it.
    """
    channels = document.get("channels") if isinstance(document, dict) else None
    if not isinstance(channels, dict):
        return document, []

    claimed = {
        code
        for entry in channels.values()
        if isinstance(entry, dict) and isinstance(entry.get("edges"), dict)
        for code in entry["edges"].values()
    }
    numbers: set[int] = set()
    out = copy.deepcopy(document)
    allocations: list[Allocation] = []

    def next_number() -> int:
        for lo, hi in vocab.free_ranges():
            for n in range(lo, hi + 1):
                if n not in numbers:
                    return n
        raise strobe_store.StrobeRefused(
            "invalid", "the strobe vocabulary has no free code left to give a channel edge."
        )

    for name, entry in out["channels"].items():
        if not isinstance(entry, dict):
            continue
        channel_type = entry.get("type") or registry.channel_set_defaults(entry).get("type")
        edges = entry.get("edges") if isinstance(entry.get("edges"), dict) else {}
        missing = [e for e in registry.EDGES.get(channel_type, ()) if not edges.get(e)]
        if not missing:
            continue
        edges = dict(edges)
        for edge in missing:
            base = f"{name.upper()}_{edge.upper()}"
            candidate, n = base, 1
            while True:
                if candidate not in claimed:
                    live = vocab.get(candidate)
                    if live is not None and live.origin == CHANNEL_SET_ORIGIN:
                        break  # this allocator's own code, held by no edge: take it back
                    if live is None and vocab.retired_entry(candidate) is None:
                        number = next_number()
                        numbers.add(number)
                        allocations.append(Allocation(name, edge, candidate, number))
                        break
                n += 1
                candidate = f"{base}_{n}"
            claimed.add(candidate)
            edges[edge] = candidate
        entry["edges"] = edges
    return out, allocations


def issue(vocabulary_document: dict, allocations: list[Allocation]) -> dict:
    """The vocabulary document with every planned code appended.

    Through `strobes/store.add`, so each one meets the same rules as a code
    added on the Strobes page: a new name, a free number, a stated meaning.
    """
    doc = vocabulary_document
    for a in allocations:
        doc = strobe_store.add(
            doc,
            a.name,
            a.code,
            rationale=f"The {a.edge} edge of the {a.channel} channel, issued when the "
            "channel set was saved. Kept if the channel is renamed.",
            origin=CHANNEL_SET_ORIGIN,
        )
    return doc
