"""Rig wiring → wire shapes.

The counterpart to `specs/service.py`, and it borrows that module's central
rule: a document that is WELL-FORMED and describes an impossible box is not a
command error. It is a successful reply carrying located problems, exactly as a
spec that will not compile is a successful `specs.compile`. `RIG_INVALID` is
reserved for a document that is not a document.

`problems` comes from two places and reads as one list:

  * the JSON Schema, for shape -- a `kind` that is not a kind, a missing pin;
  * TG226-229, for sense -- a pin the board does not have, two channels on one
    pin, a response port with no strobe slot, halves that describe different
    boxes.

They are merged rather than reported separately because an operator fixing new
wiring does not care which layer objected, and running one and then the other
would make it a two-pass job.
"""

from __future__ import annotations

import copy
from typing import Any

from . import store


def document_payload(rig: store.HardwareStore) -> dict[str, Any]:
    """`RigDocument`: the wiring, plus everything wrong with it.

    An unedited rig gets the SHIPPED pinout as an editable document rather than
    nothing, so the editor opens something real. The operator's first save turns
    that into their own; until then nothing is written.
    """
    doc = rig.load() or store.default_document()
    return {
        "document": doc,
        "status": _status(rig, doc),
        "problems": problems_for(doc),
    }


def preview_payload(rig: store.HardwareStore, document: Any, specs: Any) -> dict[str, Any]:
    """`RigSaved` without the save: what is wrong, and what it would cost.

    `status` describes the wiring currently IN FORCE, not the one being
    previewed -- the operator is comparing a draft against what the rig is
    doing now, and a status echoing the draft back would answer a question
    nobody asked.
    """
    return {
        "status": _status(rig, rig.load() or store.default_document()),
        "problems": problems_for(document),
        "breaks": impact_of(document, specs),
    }


def problems_for(document: Any) -> list[dict[str, Any]]:
    """Schema violations and wiring-rule failures, merged and located."""
    out = [
        {"location": loc, "message": msg, "code": None}
        for loc, msg in store.validate(document)
    ]
    if out:
        # The rules need a composable document. One that failed the schema may
        # not have the sections they read, and "channels is not an object" is a
        # better first message than a KeyError from a rule.
        return out
    return _rule_problems(document)


def _rule_problems(document: Any) -> list[dict[str, Any]]:
    from ephymeris_sidecar.taskgraph import registries

    try:
        chans = registries.ChannelMap(*registries._split_rig(document))
    except (KeyError, TypeError) as exc:  # pragma: no cover - schema catches these
        return [{"location": "rig.json", "message": str(exc), "code": None}]

    vocab = registries.vocabulary()
    return [
        {"location": loc, "message": msg, "code": code}
        for code, pairs in (
            ("TG226", chans.disagreements()),
            ("TG227", chans.pin_problems()),
            ("TG228", chans.duplicate_pins()),
            ("TG229", chans.slot_problems(vocab)),
        )
        for loc, msg in pairs
    ]


def impact_of(document: Any, specs: Any) -> list[dict[str, Any]]:
    """Which stored tasks this wiring would newly stop compiling.

    COMPUTED BEFORE THE WRITE, which is the whole point. Full channel authoring
    means an operator can delete a channel a saved task binds; TG223 catches
    that at compile, by which time the wiring is written and the task is broken.

    NEWLY is load-bearing. A task already failing for its own reasons is not
    this change's fault, and listing it would bury the ones that are — so each
    spec is compiled under BOTH wirings and only the difference is reported.

    The rig source is restored in a `finally`: this function installs a
    hypothetical wiring to answer a question, and leaving it installed would
    mean a preview silently changed what the app compiles.
    """
    from ephymeris_sidecar.taskgraph import registries

    entries = list(specs.list_entries())
    if not entries:
        return []

    before = {e["specId"]: _failures(specs, e["specId"]) for e in entries}

    saved = registries.current_rig_source()
    try:
        registries.set_rig_source(lambda: copy.deepcopy(document))
        after = {e["specId"]: _failures(specs, e["specId"]) for e in entries}
    finally:
        registries.set_rig_source(saved)

    out: list[dict[str, Any]] = []
    for entry in entries:
        spec_id = entry["specId"]
        gained = sorted(after[spec_id] - before[spec_id])
        if gained:
            out.append({"specId": spec_id, "label": entry.get("label"), "codes": gained})
    return out


def _failures(specs: Any, spec_id: str) -> set[str]:
    """The error codes this spec compiles with right now, or an empty set.

    A spec that will not even load is not this wiring's problem, and reporting
    it as one would make every rig edit look destructive on a rig with one
    broken task.
    """
    from ephymeris_sidecar.specs import compiler

    record = specs.get(spec_id)
    if record is None:
        return set()
    try:
        text = record.read_text()
    except OSError:
        return set()
    try:
        result = compiler.compile(text, spec_id=spec_id)
    except Exception:  # pragma: no cover - a compiler crash is not a rig fault
        return set()
    return {d.code for d in result.bag if d.severity.name == "ERROR"}


def _status(rig: store.HardwareStore, doc: dict) -> dict[str, Any]:
    from ephymeris_sidecar.taskgraph import registries

    status = rig.status()
    return {
        "custom": status.custom,
        "derivedFrom": status.derived_from or registries.active_pinout_id(),
        "board": str(doc.get("board", "")),
        "editedAt": status.edited_at,
        "pinoutHash": registries.channels().content_hash(),
    }


def saved_payload(rig: store.HardwareStore, doc: dict) -> dict[str, Any]:
    return {"status": _status(rig, doc), "problems": problems_for(doc), "breaks": []}
