"""Moving a task between machines (TASKS.md#moving-a-task-between-machines).

ADR 0003 makes the channel set lab-wide so a task moves between the two lab
machines without being rebuilt: exported on one, it compiles on the other
against that machine's pins and strobes the same codes.

PURE. Documents in; an export, a plan, or a `TaskTransferRefused` out. The
write -- the definition file, its regenerated folder, the rescan -- is the
`tasks.import` handler's, inside one rig definition write.

THE DEFINITION TRAVELS VERBATIM. It is never re-serialised through
`TaskDefinition`, which drops what this build's model does not know: another
build's fields ride through untouched. The model is parsed only to read which
channels the task names.

THE FILE CARRIES NO PIN. Beside the definition it carries what each channel
the task names IS on the exporting machine (the fields
`ChannelSet.content_hash` covers), and the number the exporting machine's
vocabulary gives each code the task strobes, so the importer can say exactly
where its channel set or its numbers disagree. An import never writes the
vocabulary: only the channel-set import brings codes over
(`rig/transfer.py`).

REFUSED WHOLE. Any conflict refuses the import, and the plan lists every one,
as the channel-set import does (`rig/transfer.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ..rig import registry
from .model import TaskDefinition, TaskDefinitionError
from .spine import STRUCTURAL
from .store import MAX_DEFINITION_BYTES
from .validate import validate

#: The export document version this code writes and reads.
EXPORT_VERSION = 1

#: A definition and the few channels it names, nothing larger.
MAX_EXPORT_BYTES = MAX_DEFINITION_BYTES + 64 * 1024

#: What a channel IS, as the file carries it and the import compares it: the
#: fields `ChannelSet.content_hash` covers, less the name, in this order.
CHANNEL_FIELDS = (
    "kind", "type", "role", "active_level", "debounce_ms",
    "serves", "well", "port_slot", "onset_strobe", "edges",
)


class TaskTransferRefused(Exception):
    """An export or import this machine will not take. Nothing was written."""


class TaskTransferInvalid(TaskTransferRefused):
    """Not an exported task at all, or a task this machine cannot export
    (`TASK_TRANSFER_INVALID`)."""


class TaskImportConflict(TaskTransferRefused):
    """An import whose plan has conflicts (`TASK_IMPORT_CONFLICT`).
    `conflicts` lists every one."""

    def __init__(self, conflicts: list[dict[str, Any]]) -> None:
        self.conflicts = conflicts
        n = len(conflicts)
        super().__init__(
            f"That task disagrees with this machine in {n} place{'' if n == 1 else 's'}; "
            "nothing was imported. " + " ".join(c["message"] for c in conflicts[:3])
            + (" …" if n > 3 else "")
        )


class TaskImportReplaces(TaskTransferRefused):
    """An import that would replace a saved task, applied without `confirm`
    (`TASK_IMPORT_REPLACES`)."""


@dataclass
class ImportPlan:
    """What importing another machine's task would do here."""

    task_id: str
    name: str
    #: The definition the file carries, verbatim: what applying writes.
    definition: dict[str, Any]
    here_hash: str
    file_hash: str
    file_hash_version: int
    #: This rig's channel set hashes, by the file's rule, to the file's hash.
    same_channel_set: bool
    #: A task with this id is saved here, and applying replaces it.
    replaces: bool = False
    #: The saved task with this id already is this document: nothing to write.
    identical: bool = False
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: The definition judged on this rig, as `tasks.get` reports it.
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "conflicts": self.conflicts,
            "taskId": self.task_id,
            "name": self.name,
            "replaces": self.replaces,
            "identical": self.identical,
            "sameChannelSet": self.same_channel_set,
            "hereHash": self.here_hash,
            "fileHash": self.file_hash,
            "fileHashVersion": self.file_hash_version,
            "diagnostics": self.diagnostics,
        }


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #


def export_document(
    document: dict[str, Any], channels: registry.ChannelMap, vocabulary: registry.Vocabulary
) -> dict[str, Any]:
    """The stored `document` as it travels, with what each channel it names
    is on this rig and the number of each code it strobes (`channels` and
    `vocabulary`, the rig definition in force).

    Refused while the task names a channel this rig lacks, or strobes a code
    this vocabulary does not hold live: the file could not say what that
    channel is or what number that code has, so the importer could not check it.
    """
    definition = _parse(document, "That task will not read")
    named = named_channels(definition)
    missing = sorted(n for n in named if n not in channels)
    if missing:
        raise TaskTransferInvalid(
            f"{definition.name} names {_listing(missing)}, which this rig does not have. "
            "Fix the task here first: the file must say what each channel it names is."
        )
    entries = {c.name: channel_entry(c) for c in channels if c.name in named}
    codes = sorted(codes_used(definition, entries, vocabulary))
    unnumbered = [name for name in codes if vocabulary.get(name) is None]
    if unnumbered:
        raise TaskTransferInvalid(
            f"{definition.name} strobes {_listing(unnumbered)}, which "
            f"{'is not a live code' if len(unnumbered) == 1 else 'are not live codes'} in this "
            "machine's vocabulary. Fix the task or the wiring here first: the file must say "
            "what number each code it strobes has."
        )
    return {
        "task_export_version": EXPORT_VERSION,
        "channel_set_hash": channels.channel_set.content_hash(),
        "channel_set_hash_version": registry.CHANNEL_SET_HASH_VERSION,
        "channels": entries,
        "codes": {name: vocabulary.code_of(name) for name in codes},
        "definition": json.loads(json.dumps(document)),
    }


def named_channels(definition: TaskDefinition) -> set[str]:
    """Every channel the definition names: a trial row's odor, response and
    reward channels, and each value of a spine row's binding. A field that
    names a channel joins here, or the import never checks that channel."""
    if definition.spine is not None:
        names = {c for row in definition.spine.rows for c in row.bind.values()}
    else:
        names = {
            c
            for t in definition.trials
            for c in (t.odor_channel, t.response_channel, t.reward_channel)
        }
    return {n for n in names if n}


def codes_used(
    definition: TaskDefinition, entries: dict[str, dict[str, Any]], vocabulary: registry.Vocabulary
) -> set[str]:
    """The name of every code the task strobes because of what it names:
    each named channel's edge codes and declared onset (`entries`, as the file
    carries them), a trial row's onset code and its response port's slot
    codes, and a spine's structural codes. A field that makes a task strobe
    another code joins here, or the import never checks its number."""
    names: set[Any] = set()
    for entry in entries.values():
        edges = entry.get("edges")
        names |= set(edges.values()) if isinstance(edges, dict) else set()
        names.add(entry.get("onset_strobe"))
    if definition.spine is not None:
        names |= set(STRUCTURAL.values())
    else:
        for trial in definition.trials:
            names.add(trial.onset_strobe)
            slot = (entries.get(trial.response_channel or "") or {}).get("port_slot")
            if isinstance(slot, int) and not isinstance(slot, bool):
                names |= set((vocabulary.port_slot(slot) or {}).values())
    return {n for n in names if isinstance(n, str) and n}


def channel_entry(channel: registry.Channel) -> dict[str, Any]:
    """What `channel` is, as the file carries it: `CHANNEL_FIELDS`, each left
    out while it has no value. No pin, label or rationale."""
    values = {
        "kind": channel.kind,
        "type": channel.type,
        "role": channel.role,
        "active_level": channel.active_level,
        "debounce_ms": channel.debounce_ms,
        "serves": channel.serves,
        "well": channel.well,
        "port_slot": channel.port_slot,
        "onset_strobe": channel.onset_strobe,
        "edges": dict(channel.edges) or None,
    }
    return {k: v for k, v in values.items() if v not in (None, "")}


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #


def plan_import(
    file: Any,
    *,
    channels: registry.ChannelMap,
    vocabulary: registry.Vocabulary,
    tasks: Any,
    bundled_named: Callable[[str], Any],
) -> ImportPlan:
    """Compare another machine's export with this machine. Writes nothing;
    raises `TaskTransferInvalid` for a file that is not an export.

    `channels` and `vocabulary` are the rig definition in force; `tasks` the
    task store (`list_entries()` and `document(id)`); `bundled_named(name)` is
    truthy when a shipped sketch has that name.

    EVERY CONFLICT, NOT THE FIRST. Only the channels and codes the task names
    are judged: a difference elsewhere in the channel set or the vocabulary
    changes nothing this task compiles or strobes. The import never touches
    either; a difference is reported, never resolved.
    """
    document, there, numbered, stated_hash, hash_version = _read_export(file)
    definition = _parse(document, "That file's task will not read")
    undescribed = sorted(named_channels(definition) - set(there))
    if undescribed:
        raise TaskTransferInvalid(
            f"That file is not an exported task: its task names {_listing(undescribed)}, "
            "which the file does not describe. Export it again."
        )

    here_hash = channels.channel_set.content_hash(version=hash_version)
    stored = tasks.document(definition.id)
    plan = ImportPlan(
        task_id=definition.id,
        name=definition.name,
        definition=document,
        here_hash=here_hash,
        file_hash=stated_hash,
        file_hash_version=hash_version,
        same_channel_set=here_hash == stated_hash,
        replaces=stored is not None,
        identical=stored == document,
        diagnostics=[d.to_json() for d in validate(definition)],
    )
    conflicts = plan.conflicts
    conflicts += [
        _conflict("not_here", name, f"{name} is named by that task and not on this rig, so it has no pin here.")
        for name in there
        if name not in channels
    ]
    for name, entry in there.items():
        here = channels.get(name)
        differences = _differences(channel_entry(here), entry) if here is not None else []
        if differences:
            conflicts.append(_conflict("differs", name, f"{name} differs: {'; '.join(differences)}."))
    conflicts += _order_conflicts([c.name for c in channels], list(there))
    conflicts += _code_conflicts(numbered, codes_used(definition, there, vocabulary), vocabulary)

    if bundled_named(definition.name):
        conflicts.append(_conflict(
            "bundled_name",
            None,
            f"A sketch that ships with Ephymeris is already called {definition.name!r}. "
            "Rename the task on the other machine, then export it again.",
        ))
    twin = next(
        (e for e in tasks.list_entries()
         if e["id"] != definition.id and str(e["name"]).casefold() == definition.name.casefold()),
        None,
    )
    if twin is not None:
        conflicts.append(_conflict(
            "name_taken",
            None,
            f"Another task here is already called {twin['name']!r}. Rename one of them, "
            "then import again: two tasks with one name share a sketch folder.",
        ))
    return plan


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse(document: Any, refusal: str) -> TaskDefinition:
    try:
        return TaskDefinition.from_json(document)
    except TaskDefinitionError as exc:
        raise TaskTransferInvalid(f"{refusal}: {exc}") from exc


def _listing(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


THERE = "in that task's channel set"


def _differences(here: dict[str, Any], there: dict[str, Any]) -> list[str]:
    """`<field> is <here> here and <there> in that task's channel set`, for
    each field that differs, in `CHANNEL_FIELDS` order; an edge per edge."""
    out = []
    for name in CHANNEL_FIELDS:
        mine, theirs = here.get(name), there.get(name)
        if name == "edges" and isinstance(mine or {}, dict) and isinstance(theirs or {}, dict):
            mine, theirs = mine or {}, theirs or {}
            for edge in [*theirs, *(e for e in mine if e not in theirs)]:
                if mine.get(edge) != theirs.get(edge):
                    out.append(f"edges.{edge} is {_shown(mine.get(edge))} here and {_shown(theirs.get(edge))} {THERE}")
        elif mine != theirs:
            out.append(f"{name} is {_shown(mine)} here and {_shown(theirs)} {THERE}")
    return out


def _shown(value: Any) -> str:
    return "unset" if value is None else str(value)


def _order_conflicts(here: list[str], there: list[str]) -> list[dict[str, Any]]:
    """An `order` conflict for every channel the task names whose place among
    them differs. Declaration order is the odor index
    (TASKS.md#order-is-meaning), the rule `rig/transfer.py` applies to the
    whole channel set; counted among the channels both sides have, so a
    channel one side lacks shifts no one."""
    shared_here = [n for n in here if n in there]
    shared_there = [n for n in there if n in here]
    return [
        _conflict(
            "order",
            name,
            f"{name} is the task's channel {at + 1} here and {shared_there.index(name) + 1} "
            f"{THERE}, counting only the {len(shared_here)} channels both have. Declaration "
            "order is the odor index, so the two must list their channels in one order.",
        )
        for at, (name, theirs) in enumerate(zip(shared_here, shared_there))
        if name != theirs
    ]


def _code_conflicts(
    numbered: dict[str, int], used: set[str], vocabulary: registry.Vocabulary
) -> list[dict[str, Any]]:
    """A `code` conflict for every code the file numbers otherwise than this
    vocabulary, or that is not live here, and for every code the task would
    strobe here that the file gives no number. Never resolved by writing the
    vocabulary: it is append only and lab-wide, and only the channel-set
    import brings codes over."""
    first = "Import the other machine's channel set first, so both give it one number."
    out = []
    for name, number in numbered.items():
        entry = vocabulary.get(name)
        if entry is None:
            out.append(_conflict(
                "code", None,
                f"{name} is code {number} in that task's vocabulary and not a live code here. {first}",
            ))
        elif entry.code != number:
            out.append(_conflict(
                "code", None,
                f"{name} is code {number} in that task's vocabulary and {entry.code} here. {first}",
            ))
    out += [
        _conflict(
            "code", None,
            f"That task would strobe {name} here, and the file gives it no number. "
            "Export it again from the other machine.",
        )
        for name in sorted(used - set(numbered))
    ]
    return out


def _conflict(kind: str, channel: str | None, message: str) -> dict[str, Any]:
    """One `TaskImportConflict`."""
    return {"kind": kind, "channel": channel, "message": message}


def _read_export(file: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, int], str, int]:
    not_one = "That file is not an exported task."
    if not isinstance(file, dict):
        raise TaskTransferInvalid(not_one)
    if len(json.dumps(file).encode()) > MAX_EXPORT_BYTES:
        raise TaskTransferInvalid("That file is too large to be an exported task.")
    version = file.get("task_export_version")
    if version != EXPORT_VERSION:
        raise TaskTransferInvalid(
            f"{not_one} It is version {version!r}; this build reads version {EXPORT_VERSION}."
            if version is not None
            else not_one
        )
    document = file.get("definition")
    there = file.get("channels")
    codes = file.get("codes")
    stated = file.get("channel_set_hash")
    if (
        not isinstance(document, dict)
        or not isinstance(there, dict)
        or any(not isinstance(v, dict) for v in there.values())
        or not isinstance(codes, dict)
        or any(type(v) is not int for v in codes.values())
        or not isinstance(stated, str)
    ):
        raise TaskTransferInvalid(
            f"{not_one} It needs a definition, its channels, its codes and a channel-set hash."
        )
    return document, there, codes, stated, _hash_version(file.get("channel_set_hash_version"))


def _hash_version(version: Any) -> int:
    known = registry.CHANNEL_SET_HASH_VERSIONS
    if type(version) is int and version > max(known):
        raise TaskTransferInvalid(
            f"That file's channel-set hash is version {version}, made by a newer build of "
            f"Ephymeris than this one (which reads versions {', '.join(map(str, known))}). "
            "Update this machine, then import again."
        )
    if type(version) is not int or version not in known:
        raise TaskTransferInvalid(
            f"That file's channel_set_hash_version, {version!r}, is not a channel-set hash "
            "version. Export it again."
        )
    return version
