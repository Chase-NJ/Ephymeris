"""Rig wiring → wire shapes.

The central rule: a document that is WELL-FORMED and describes an impossible box
is not a command error. It is a successful reply carrying located problems.
`RIG_INVALID` is reserved for a document that is not a document.

`problems` comes from two places and reads as one list:

  * the JSON Schema, for shape -- a `kind` that is not a kind, a missing pin;
  * the wiring rules (`RIG101`-`RIG104`), for sense -- a pin the board does not
    have, two channels on one pin, a response port with no strobe slot, halves
    that describe different boxes.

They are merged rather than reported separately because an operator fixing new
wiring does not care which layer objected, and running one and then the other
would make it a two-pass job.
"""

from __future__ import annotations

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


def preview_payload(rig: store.HardwareStore, document: Any, tasks: Any = None) -> dict[str, Any]:
    """`RigSaved` without the save: what is wrong, and what it would cost.

    `status` describes the wiring currently IN FORCE, not the one being
    previewed -- the operator is comparing a draft against what the rig is
    doing now, and a status echoing the draft back would answer a question
    nobody asked.
    """
    return {
        "status": _status(rig, rig.load() or store.default_document()),
        "problems": problems_for(document),
        "breaks": impact_of(document, tasks),
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
    from ephymeris_sidecar.rig import registry

    try:
        chans = registry.ChannelMap(*registry.split_rig(document))
    except (KeyError, TypeError) as exc:  # pragma: no cover - schema catches these
        return [{"location": "rig.json", "message": str(exc), "code": None}]

    vocab = registry.vocabulary()
    return [
        {"location": loc, "message": msg, "code": code}
        for code, pairs in (
            ("RIG101", chans.disagreements()),
            ("RIG102", chans.pin_problems()),
            ("RIG103", chans.duplicate_pins()),
            ("RIG104", chans.slot_problems(vocab)),
        )
        for loc, msg in pairs
    ]


def impact_of(document: Any, tasks: Any) -> list[dict[str, Any]]:
    """Which stored task profiles this wiring would newly break.

    COMPUTED BEFORE THE WRITE, which is the whole point. Full channel authoring
    means an operator can delete a channel a saved task binds; catching that at
    generation time would be too late — the wiring is written by then and the
    task is already broken.

    NEWLY is load-bearing. A task already failing for its own reasons is not this
    change's fault, and listing it would bury the ones that are — so each profile
    is validated under BOTH wirings and only the difference is reported.

    The rig source is restored in a `finally`: this function installs a
    hypothetical wiring to answer a question, and leaving it installed would mean
    a preview silently changed what the app generates.

    `tasks` is the task-profile store. It is None until one exists, and an empty
    `breaks` on a rig with no profiles is the honest answer either way.
    """
    if tasks is None:
        return []

    import copy

    from ephymeris_sidecar.rig import registry

    entries = list(tasks.list_entries())
    if not entries:
        return []

    before = {e["id"]: tasks.failures(e["id"]) for e in entries}

    saved = registry.current_rig_source()
    try:
        registry.set_rig_source(lambda: copy.deepcopy(document))
        after = {e["id"]: tasks.failures(e["id"]) for e in entries}
    finally:
        registry.set_rig_source(saved)

    out: list[dict[str, Any]] = []
    for entry in entries:
        task_id = entry["id"]
        gained = sorted(after[task_id] - before[task_id])
        if gained:
            out.append({"specId": task_id, "label": entry.get("label"), "codes": gained})
    return out


def _status(rig: store.HardwareStore, doc: dict) -> dict[str, Any]:
    from ephymeris_sidecar.rig import registry

    status = rig.status()
    return {
        "custom": status.custom,
        "derivedFrom": status.derived_from or registry.active_pinout_id(),
        "board": str(doc.get("board", "")),
        "editedAt": status.edited_at,
        "pinoutHash": registry.channels().content_hash(),
    }


def saved_payload(rig: store.HardwareStore, doc: dict) -> dict[str, Any]:
    return {"status": _status(rig, doc), "problems": problems_for(doc), "breaks": []}
