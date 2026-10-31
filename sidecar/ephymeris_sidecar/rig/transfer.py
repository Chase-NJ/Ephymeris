"""Moving the channel set between machines
(TASKS.md#moving-the-channel-set-between-machines).

ADR 0003 makes the channel set lab-wide: both machines must hold one document
and emit identical codes. One machine edits it; the other imports it. The
vocabulary travels in the same file, because the channel set names its edge
codes and the numbers behind those names live only in the vocabulary.

PURE. Documents in, a plan or new documents out, or `ChannelSetRefused`. The
write -- one rig definition write, vocabulary then wiring, then one rebuild --
is `RigDefinition.import_channel_set`'s.

REFUSED WHOLE. Any conflict refuses the import, and the plan lists every one
rather than the first, so the operator sees the whole difference at once:

  * `vocabulary`: one name with two codes, one code with two names, a code this
    machine cannot issue (`strobe_store.plan_merge`);
  * `not_here` / `only_here`: a channel one side lacks. The pin map is local
    and keyed by channel name, so a channel the file adds has no pin here, and
    one it drops leaves a pin belonging to no channel;
  * `no_code`: an edge with no code name, which this machine would then issue
    under its own numbers;
  * `rule`: a wiring rule (RIG101-RIG107) the joined document breaks against
    the MERGED vocabulary -- e.g. a code retired here that the file's channel
    names, since a merge never reinstates;
  * `hash`: the joined channel set does not hash to the file's own hash, so
    the file changed after it was exported.

THE PIN MAP NEVER TRAVELS. An import replaces this machine's channel set with
the file's, entries verbatim and in the file's declaration order, and keeps
every pin this machine has.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any

from ..hardware import service as hardware_service
from ..hardware import store as hardware_store
from ..strobes import store as strobe_store
from . import registry

#: The export document version this code writes and reads.
EXPORT_VERSION = 1

#: Refuse before planning: a channel set and a vocabulary, nothing larger.
MAX_EXPORT_BYTES = hardware_store.MAX_RIG_BYTES + strobe_store.MAX_VOCAB_BYTES


class ChannelSetRefused(Exception):
    """An export or import this machine will not take. `reason` is `invalid`
    (not an export, or nothing exportable) or `import_conflict` (`detail` has
    `conflicts`). Nothing was written."""

    def __init__(self, reason: str, message: str, detail: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.detail = detail or {}
        super().__init__(message)


@dataclass
class ImportPlan:
    """What importing another machine's channel set would do here."""

    vocabulary: strobe_store.MergePlan
    here_hash: str
    there_hash: str
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: Channels on both sides whose entry differs.
    changed: list[str] = field(default_factory=list)
    #: The declaration order differs: the odor index (TASKS.md#order-is-meaning).
    reordered: bool = False
    #: Saved tasks the import would newly break; set by the caller, who has them.
    breaks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changes_vocabulary(self) -> bool:
        return bool(self.vocabulary.adds or self.vocabulary.retires)

    @property
    def identical(self) -> bool:
        """Nothing to write: the two machines already agree."""
        return not (self.conflicts or self.changed or self.reordered or self.changes_vocabulary)

    def to_json(self) -> dict[str, Any]:
        return {
            "conflicts": self.conflicts,
            "vocabulary": self.vocabulary.to_json(),
            "changed": self.changed,
            "reordered": self.reordered,
            "breaks": self.breaks,
            "hereHash": self.here_hash,
            "thereHash": self.there_hash,
            "identical": self.identical,
        }


@dataclass(frozen=True)
class Planned:
    """A plan, and the two documents applying it writes. Both are None when
    the plan has a conflict; `vocabulary` is also None when it is unchanged."""

    plan: ImportPlan
    wiring: dict[str, Any] | None
    vocabulary: dict[str, Any] | None


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def export_document(wiring: dict[str, Any], vocabulary: dict[str, Any]) -> dict[str, Any]:
    """The channel set of `wiring` and the whole `vocabulary`, as they travel.

    Refused while any edge has no code: the importer would have to issue its
    own, under its own numbers, and the two machines would part ways at once.
    """
    chans = _compose(wiring)
    missing = _uncoded(chans)
    if missing:
        raise ChannelSetRefused(
            "invalid",
            f"{len(missing)} edge{'' if len(missing) == 1 else 's'} ({', '.join(missing[:4])}"
            f"{', …' if len(missing) > 4 else ''}) "
            f"{'has' if len(missing) == 1 else 'have'} no strobe code yet. Save the wiring on "
            "this machine first: a save issues them, and exporting without them would let the "
            "other machine issue different numbers.",
        )
    channel_set, _pin_map = hardware_store.split(wiring)
    return {
        "channel_set_export_version": EXPORT_VERSION,
        "channel_set_hash": chans.channel_set.content_hash(),
        "channel_set": copy.deepcopy(channel_set),
        "vocabulary": strobe_store.export_document(vocabulary),
    }


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def plan_import(wiring: dict[str, Any], vocabulary: dict[str, Any], other: Any) -> Planned:
    """Compare another machine's export with this machine's wiring and
    vocabulary in force. Writes nothing; raises `ChannelSetRefused('invalid')`
    for a file that is not an export."""
    there_channels, there_vocab, stated_hash = _read_export(other)

    try:
        vocab_plan = strobe_store.plan_merge(vocabulary, there_vocab)
    except strobe_store.StrobeRefused as exc:
        raise ChannelSetRefused("invalid", f"That file's vocabulary will not read: {exc}") from exc

    plan = ImportPlan(
        vocabulary=vocab_plan,
        here_hash=_compose(wiring).channel_set.content_hash(),
        there_hash=stated_hash,
    )
    conflicts = plan.conflicts
    conflicts += [
        {"kind": "vocabulary", "channel": None, "message": c["message"]}
        for c in vocab_plan.conflicts
    ]

    here_channels = wiring["channels"]
    for name in there_channels:
        if name not in here_channels:
            conflicts.append({
                "kind": "not_here",
                "channel": name,
                "message": f"{name} is in that channel set and not on this rig, so it has no pin here.",
            })
    for name in here_channels:
        if name not in there_channels:
            conflicts.append({
                "kind": "only_here",
                "channel": name,
                "message": f"{name} is on this rig and not in that channel set.",
            })

    joined = {k: v for k, v in wiring.items() if k != "edited_at"}
    joined["channels"] = copy.deepcopy(there_channels)
    shape = hardware_store.validate(joined)
    if shape:
        where, what = shape[0]
        raise ChannelSetRefused("invalid", f"That file's channel set is not a channel set: {where}: {what}")

    for edge in _uncoded(_compose(joined)):
        conflicts.append({
            "kind": "no_code",
            "channel": edge.split(".")[0],
            "message": f"{edge} has no strobe code in that file. Save the wiring on the machine "
            "that exported it, then export it again.",
        })

    plan.changed = [n for n in there_channels if n in here_channels and here_channels[n] != there_channels[n]]
    plan.reordered = set(there_channels) == set(here_channels) and list(there_channels) != list(here_channels)

    if conflicts:
        return Planned(plan, None, None)

    merged = vocabulary
    if plan.changes_vocabulary:
        try:
            merged = strobe_store.apply_merge(vocabulary, there_vocab, vocab_plan)
        except strobe_store.StrobeRefused as exc:
            # A code retired there that a port slot here still reports with.
            conflicts.append({"kind": "vocabulary", "channel": None, "message": str(exc)})
            return Planned(plan, None, None)

    with registry.hypothetical(vocabulary=merged):
        rules = hardware_service.problems_for(joined)
    for p in rules:
        conflicts.append({
            "kind": "rule",
            "channel": _channel_at(p["location"]),
            "message": f"{p['code'] or 'shape'} {p['location']}: {p['message']}",
        })

    if not rules and _compose(joined).channel_set.content_hash() != stated_hash:
        conflicts.append({
            "kind": "hash",
            "channel": None,
            "message": "That channel set does not hash to the hash it was exported with: the "
            "file was changed after it was exported. Export it again.",
        })

    if conflicts:
        return Planned(plan, None, None)
    return Planned(plan, joined, merged if plan.changes_vocabulary else None)


def refusal(plan: ImportPlan) -> ChannelSetRefused:
    """The refusal of a plan with conflicts, naming each."""
    n = len(plan.conflicts)
    return ChannelSetRefused(
        "import_conflict",
        f"The two machines disagree in {n} place{'' if n == 1 else 's'}; nothing was imported. "
        + " ".join(c["message"] for c in plan.conflicts[:3])
        + (" …" if n > 3 else ""),
        {"conflicts": plan.conflicts},
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _read_export(other: Any) -> tuple[dict[str, Any], dict[str, Any], str]:
    not_one = "That file is not an exported channel set."
    if not isinstance(other, dict):
        raise ChannelSetRefused("invalid", not_one)
    if len(json.dumps(other).encode()) > MAX_EXPORT_BYTES:
        raise ChannelSetRefused("invalid", "That file is too large to be an exported channel set.")
    version = other.get("channel_set_export_version")
    if version != EXPORT_VERSION:
        raise ChannelSetRefused(
            "invalid",
            f"{not_one} It is version {version!r}; this build reads version {EXPORT_VERSION}."
            if version is not None
            else not_one,
        )
    channel_set = other.get("channel_set")
    channels = channel_set.get("channels") if isinstance(channel_set, dict) else None
    vocab = other.get("vocabulary")
    stated = other.get("channel_set_hash")
    if not isinstance(channels, dict) or not channels or not isinstance(vocab, dict) or not isinstance(stated, str):
        raise ChannelSetRefused("invalid", f"{not_one} It needs a channel set, a vocabulary and a hash.")
    return channels, vocab, stated


def _compose(wiring: dict[str, Any]) -> registry.ChannelMap:
    """The channel map of a document; a channel with no pin is left out, as
    the registry leaves it out."""
    return registry.ChannelMap(*registry.split_rig(wiring))


def _uncoded(chans: registry.ChannelMap) -> list[str]:
    """`channel.edge` for every edge its type has and its entry names no code for."""
    out = []
    for c in chans:
        named = {edge for edge, _code in c.edges}
        out += [f"{c.name}.{edge}" for edge in registry.EDGES.get(c.type, ()) if edge not in named]
    return out


def _channel_at(location: str) -> str | None:
    """`channels.fluid_2.edges` -> `fluid_2`."""
    parts = location.split(".")
    return parts[1] if len(parts) > 1 and parts[0] in ("channels", "pins") else None
