"""Moving the channel set between machines
(TASKS.md#moving-the-channel-set-between-machines).

ADR 0003 makes the channel set lab-wide: both machines must hold one document
and emit identical codes. One machine edits it; the other imports it. The
vocabulary travels in the same file, because the channel set names its edge
codes and the numbers behind those names live only in the vocabulary.

PURE. Documents in, a plan or new documents out, or a `ChannelSetRefused`. The
write -- one rig definition write, vocabulary then wiring, then one rebuild --
is `RigDefinition.import_channel_set`'s.

REFUSED WHOLE. Any conflict refuses the import, and the plan lists every one
rather than the first, so the operator sees the whole difference at once. The
kinds, and when each applies, are TASKS.md's table; `plan_import` is where each
is judged.

THE PIN MAP NEVER TRAVELS. An import replaces this machine's channel set with
the file's, entries verbatim and in the file's declaration order, and keeps
every pin this machine has.
"""

from __future__ import annotations

import copy
import dataclasses
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
    """An export or import this machine will not take. Nothing was written."""


class ChannelSetInvalid(ChannelSetRefused):
    """Not an exported channel set at all, or nothing this machine can export
    (`CHANNEL_SET_INVALID`)."""


class ChannelSetImportConflict(ChannelSetRefused):
    """An import whose plan has conflicts (`CHANNEL_SET_IMPORT_CONFLICT`).
    `conflicts` lists every one."""

    def __init__(self, conflicts: list[dict[str, Any]]) -> None:
        self.conflicts = conflicts
        n = len(conflicts)
        super().__init__(
            f"The two machines disagree in {n} place{'' if n == 1 else 's'}; nothing was "
            "imported. " + " ".join(c["message"] for c in conflicts[:3]) + (" …" if n > 3 else "")
        )


@dataclass
class ImportPlan:
    """What importing another machine's channel set would do here."""

    vocabulary: strobe_store.MergePlan
    #: This rig's channel-set hash now, by the current rule.
    here_hash: str
    #: This rig's channel-set hash after a clean import, by the current rule:
    #: computed here, over the file's channel set. Not the file's own hash,
    #: which an older build made by an older rule.
    imported_hash: str
    #: The hash the file states, and the rule it was made by.
    file_hash: str
    file_hash_version: int
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: Channels on both sides whose entry differs.
    changed: list[str] = field(default_factory=list)
    #: Saved tasks the import would newly break; set by the caller, who has them.
    breaks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def changes_vocabulary(self) -> bool:
        return bool(self.vocabulary.adds or self.vocabulary.retires)

    @property
    def identical(self) -> bool:
        """Nothing to write: the two machines already agree."""
        return not (self.conflicts or self.changed or self.changes_vocabulary)

    def to_json(self) -> dict[str, Any]:
        return {
            "conflicts": self.conflicts,
            "vocabulary": self.vocabulary.to_json(),
            "changed": self.changed,
            "breaks": self.breaks,
            "hereHash": self.here_hash,
            "importedHash": self.imported_hash,
            "fileHash": self.file_hash,
            "fileHashVersion": self.file_hash_version,
            "identical": self.identical,
        }


@dataclass(frozen=True)
class Planned:
    """A plan, and the documents applying it writes, in the order it writes
    them: `adds` (the vocabulary with only its new codes), `wiring`, then
    `vocabulary` (with the retirements too). All are None when the plan has a
    conflict; a vocabulary step is None when it changes nothing.

    THE ORDER IS WHAT MAKES A FAILURE RECOVERABLE. Each step leaves a wiring
    and a vocabulary that load together: adding a code breaks no wiring, the
    new wiring names only codes the adds made live, and only then is a code
    retired -- one the old wiring may still name. A failure between any two
    steps leaves a rig that restarts on its own wiring, and importing again
    finishes the rest.
    """

    plan: ImportPlan
    wiring: dict[str, Any] | None
    vocabulary: dict[str, Any] | None
    adds: dict[str, Any] | None = None


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
        raise ChannelSetInvalid(
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
        "channel_set_hash_version": registry.CHANNEL_SET_HASH_VERSION,
        "channel_set": copy.deepcopy(channel_set),
        "vocabulary": strobe_store.export_document(vocabulary),
    }


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def plan_import(wiring: dict[str, Any], vocabulary: dict[str, Any], other: Any) -> Planned:
    """Compare another machine's export with this machine's wiring and
    vocabulary in force. Writes nothing; raises `ChannelSetInvalid` for a file
    that is not an export.

    EVERY CONFLICT, NOT THE FIRST, with two exceptions that are restatements:
    the wiring rules and the hash are judged only once both sides have the same
    channels (a channel one side lacks would come back as RIG101 on every
    rule), and the hash is not judged over a `rule` or `no_code` conflict,
    which already names the edit.
    """
    there_channels, there_vocab, stated_hash, hash_version = _read_export(other)
    try:
        vocab_plan = strobe_store.plan_merge(vocabulary, there_vocab)
    except strobe_store.StrobeRefused as exc:
        raise ChannelSetInvalid(f"That file's vocabulary will not read: {exc}") from exc

    here_channels = wiring["channels"]
    joined = {k: v for k, v in wiring.items() if k != "edited_at"}
    joined["channels"] = copy.deepcopy(there_channels)
    shape = hardware_store.validate(joined)
    if shape:
        where, what = shape[0]
        raise ChannelSetInvalid(f"That file's channel set is not a channel set: {where}: {what}")

    plan = ImportPlan(
        vocabulary=vocab_plan,
        here_hash=_compose(wiring).channel_set.content_hash(),
        imported_hash=_compose(joined).channel_set.content_hash(),
        file_hash=stated_hash,
        file_hash_version=hash_version,
        changed=[n for n in there_channels if n in here_channels and here_channels[n] != there_channels[n]],
    )
    conflicts = plan.conflicts
    conflicts += [_conflict("vocabulary", None, c["message"]) for c in vocab_plan.conflicts]
    conflicts += [
        _conflict("not_here", name, f"{name} is in that channel set and not on this rig, so it has no pin here.")
        for name in there_channels
        if name not in here_channels
    ]
    conflicts += [
        _conflict("only_here", name, f"{name} is on this rig and not in that channel set.")
        for name in here_channels
        if name not in there_channels
    ]
    conflicts += _order_conflicts(list(here_channels), list(there_channels))
    same_channels = set(there_channels) == set(here_channels)

    composed = _compose(joined)
    uncoded = [
        _conflict(
            "no_code",
            edge.split(".")[0],
            f"{edge} has no strobe code in that file. Save the wiring on the machine that "
            "exported it, then export it again.",
        )
        for edge in _uncoded(composed)
    ]
    conflicts += uncoded

    # Judged against the vocabulary the import would leave, less any code in
    # conflict: those are already listed, and a merge cannot be built with them.
    merged = adds = vocabulary
    if vocab_plan.adds or vocab_plan.retires:
        unconflicted = dataclasses.replace(vocab_plan, conflicts=[])
        try:
            merged = strobe_store.apply_merge(vocabulary, there_vocab, unconflicted)
            adds = strobe_store.apply_merge(
                vocabulary, there_vocab, dataclasses.replace(unconflicted, retires=[])
            )
        except strobe_store.StrobeRefused as exc:
            # A code retired there that a port slot here still reports with.
            conflicts.append(_conflict("vocabulary", None, str(exc)))

    rules: list[dict[str, Any]] = []
    if same_channels:
        with registry.hypothetical(vocabulary=merged):
            rules = hardware_service.problems_for(joined)
        conflicts += [
            _conflict("rule", _channel_at(p["location"]), f"{p['code'] or 'shape'} {p['location']}: {p['message']}")
            for p in rules
        ]
        # By the rule the file's hash was made with: an export from a build
        # whose hash ignored order is checked by that rule, and its order by
        # the `order` conflicts above.
        if not rules and not uncoded and composed.channel_set.content_hash(version=hash_version) != stated_hash:
            conflicts.append(_conflict(
                "hash",
                None,
                "That channel set does not hash to the hash it was exported with: the file "
                "was changed after it was exported. Export it again.",
            ))

    if conflicts:
        return Planned(plan, None, None)
    return Planned(
        plan,
        joined,
        merged if plan.changes_vocabulary else None,
        adds=adds if vocab_plan.adds else None,
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _order_conflicts(here: list[str], there: list[str]) -> list[dict[str, Any]]:
    """An `order` conflict for every channel both sides have whose place among
    them differs. Declaration order is the odor index
    (TASKS.md#order-is-meaning): adopting another order would put another line
    behind each odor position, with every trial still looking correct."""
    shared_here = [n for n in here if n in there]
    shared_there = [n for n in there if n in here]
    # Counted among the shared channels only, so a channel one side lacks
    # shifts no one; a channel listed here differs at that count by definition.
    return [
        _conflict(
            "order",
            name,
            f"{name} is shared channel {shared_here.index(name) + 1} here and {at + 1} in that "
            f"channel set, counting only the {len(shared_here)} channels both have. Declaration "
            "order is the odor index, so the two must list their channels in one order.",
        )
        for at, (name, mine) in enumerate(zip(shared_there, shared_here))
        if name != mine
    ]


def _conflict(kind: str, channel: str | None, message: str) -> dict[str, Any]:
    """One `ChannelSetConflict`."""
    return {"kind": kind, "channel": channel, "message": message}


def _read_export(other: Any) -> tuple[dict[str, Any], dict[str, Any], str, int]:
    not_one = "That file is not an exported channel set."
    if not isinstance(other, dict):
        raise ChannelSetInvalid(not_one)
    if len(json.dumps(other).encode()) > MAX_EXPORT_BYTES:
        raise ChannelSetInvalid("That file is too large to be an exported channel set.")
    version = other.get("channel_set_export_version")
    if version != EXPORT_VERSION:
        raise ChannelSetInvalid(
            f"{not_one} It is version {version!r}; this build reads version {EXPORT_VERSION}."
            if version is not None
            else not_one,
        )
    channel_set = other.get("channel_set")
    channels = channel_set.get("channels") if isinstance(channel_set, dict) else None
    vocab = other.get("vocabulary")
    stated = other.get("channel_set_hash")
    if not isinstance(channels, dict) or not channels or not isinstance(vocab, dict) or not isinstance(stated, str):
        raise ChannelSetInvalid(f"{not_one} It needs a channel set, a vocabulary and a hash.")
    return channels, vocab, stated, _hash_version(other)


def _hash_version(other: dict[str, Any]) -> int:
    """The rule the file's hash was made by. Absent means version 1: an export
    made before the hash covered declaration order. Only an integer is a
    version, and only one above every version this build knows means a newer
    build made the file; anything else is a file that is not an export."""
    if "channel_set_hash_version" not in other:
        return 1
    version = other["channel_set_hash_version"]
    known = registry.CHANNEL_SET_HASH_VERSIONS
    if type(version) is not int or version < min(known):
        raise ChannelSetInvalid(
            f"That file's channel_set_hash_version, {version!r}, is not a channel-set hash "
            "version. Export it again."
        )
    if version > max(known):
        raise ChannelSetInvalid(
            f"That file's channel-set hash is version {version}, made by a newer build of "
            f"Ephymeris than this one (which reads versions {', '.join(map(str, known))}). "
            "Update this machine, then import again."
        )
    return version  # the versions run 1..max with no gap


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
