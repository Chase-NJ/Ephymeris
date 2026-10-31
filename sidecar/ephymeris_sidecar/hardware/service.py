"""Rig wiring → wire shapes.

The central rule: a document that is WELL-FORMED and describes an impossible box
is not a command error. It is a successful reply carrying located problems.
`RIG_INVALID` is reserved for a document that is not a document.

`problems` comes from two places and reads as one list:

  * the JSON Schema, for shape -- a `kind` that is not a kind, a missing pin;
  * the wiring rules (`RIG101`-`RIG107`), for sense -- a pin the board does not
    have, two channels on one pin, a response port with no strobe slot, an odor
    line with no onset code of its own, halves that describe different boxes, a
    channel-set declaration that contradicts itself.

They are merged rather than reported separately because an operator fixing new
wiring does not care which layer objected, and running one and then the other
would make it a two-pass job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from . import store


class InForce(NamedTuple):
    """The wiring in force (`RigDefinition.in_force`): the stored document the
    registry composes, or None for the shipped one; and, when stored wiring
    did not load, the refusal every box is under (`unloaded_message`)."""

    document: dict | None
    problem: str | None


def unloaded_message(problem: str) -> str:
    """The refusal while stored wiring did not load: what is in force, and what
    that blocks. The wire error says exactly this; `hardware.get` says what
    the file is NOW in a notice of its own."""
    return (
        f"{problem} The shipped pins are in force, so no box can start, be flashed "
        "or identified until this rig's wiring is saved or reset, or Ephymeris "
        "restarts onto a file that loads."
    )


#: The notice for wiring in force that did not load. No reason in it: the
#: reason belongs to the file as it was, and the next notice says what it is now.
IN_FORCE_UNLOADED = (
    "The shipped pins are in force: this rig's stored wiring did not load when it "
    "was installed, so no box can start, be flashed or identified until the wiring "
    "is saved or reset, or Ephymeris restarts onto a file that loads."
)


class _Rig(NamedTuple):
    """Everything a reply says about the rig, from one read of the disk."""

    in_force: InForce
    disk: Any  # store._Stored
    paths: list[str]


def rig_state(rig: store.HardwareStore, in_force: InForce | None) -> _Rig:
    disk = rig.inspect()
    if in_force is None:
        # What installing the file now would put in force.
        in_force = InForce(
            disk.document if not disk.problems else None,
            unloaded_message(disk.problems[0][1]) if disk.problems else None,
        )
    return _Rig(in_force, disk, [str(p) for p in rig.stored_paths()])


def served_draft(state: _Rig) -> dict:
    """The draft `hardware.get` serves. The wiring in force; or, while stored
    wiring did not load, the stored document itself (broken, or with pins to
    confirm) so it can be repaired -- the shipped pins when there is nothing
    to repair."""
    if state.in_force.problem:
        if state.disk.state in ("loads", "invalid", "mismatched") and state.disk.document:
            return state.disk.document
        return store.default_document()
    if state.in_force.document is not None:
        return state.in_force.document
    return store.default_document()


def save_blocked(state: _Rig, *, confirmed_pins: bool) -> str | None:
    """Why the rig's state refuses any save now (`RIG_SAVE_BLOCKED`), or None."""
    if not state.in_force.problem:
        return None
    if state.disk.state in ("unrepairable", "none"):
        where = ", ".join(state.paths) or "nothing on disk"
        return (
            "There is no stored wiring to repair, so a save is refused: Reset "
            f"replaces it ({where}) and puts the shipped pins in force."
        )
    if state.disk.state == "mismatched" and not confirmed_pins:
        return (
            f"These pins come from {store.PIN_MAP_FILENAME}, which was not written with "
            f"{store.CHANNEL_SET_FILENAME}. Check every pin against the box and confirm "
            "them before saving."
        )
    return None


def _draft_problems(state: _Rig, draft: Any, *, confirmed_pins: bool) -> list[dict[str, Any]]:
    out = problems_for(draft)
    if state.in_force.problem and state.disk.state == "mismatched" and not confirmed_pins:
        out = [{
            "location": "pins",
            "message": save_blocked(state, confirmed_pins=False),
            "code": "RIG108",
        }] + out
    return out


def document_payload(rig: store.HardwareStore, *, in_force: InForce | None = None) -> dict[str, Any]:
    """`RigDocument`: the draft the editor opens, its problems, and the rig's.

    The draft is `served_draft`. `problems` are the draft's; what is wrong
    with the RIG (unloaded wiring, a file changed on disk) is
    `status.notices`, which stand through every edit and never block the save
    that clears them. Whether a save may be made is `status.canSave`, decided
    here. `in_force` defaults to what the file would install now.
    """
    state = rig_state(rig, in_force)
    doc = served_draft(state)
    return {
        "document": doc,
        "status": _status(rig, state, draft=doc, confirmed_pins=False),
        "problems": _draft_problems(state, doc, confirmed_pins=False),
    }


def notices_for(state: _Rig) -> list[dict[str, Any]]:
    """Where the wiring in force and the stored file part ways, each saying
    what it does and does not block (`RigStatus.notices`). The file is always
    described as it is NOW, beside what is in force."""
    in_force, disk = state.in_force, state.disk
    out: list[dict[str, Any]] = []
    if in_force.problem:
        out.append(_flag(IN_FORCE_UNLOADED))
        now = disk.problems[0][1] if disk.problems else ""
        if disk.state == "loads":
            name = Path(state.paths[0]).name if state.paths else store.WIRING_FILENAME
            out.append(_flag(
                f"Now {name} loads. The draft below is that file, not in force until it "
                "is saved or reset, or Ephymeris restarts."
            ))
        elif disk.state == "invalid":
            out.append(_flag(
                f"Now: {now} The draft below is that stored wiring, not in force: "
                "repair it and save to put it in force."
            ))
        elif disk.state == "mismatched":
            out.append(_flag(
                f"Now: {now} The draft below joins the two files. Check every pin "
                "against the box, confirm them, then save."
            ))
        elif disk.state == "unrepairable":
            out.append(_flag(
                f"Now: {now} There is no stored wiring to repair, so the draft is the "
                f"shipped pins and Save is off. Reset replaces {', '.join(state.paths)}."
            ))
        else:
            out.append(_flag(
                "Now there is no stored wiring on disk. Save is off; Reset puts the "
                "shipped pins in force."
            ))
        return out
    if disk.problems:
        out.append(_flag(
            f"{disk.problems[0][1]} The wiring shown is the one in force, loaded before "
            "the file changed, and boxes run the wiring in force. A restart onto this "
            "file would stop every box until the wiring is saved or reset."
        ))
    elif _content(disk.document) != _content(in_force.document):
        out.append(_flag(
            f"{store.WIRING_FILENAME} on disk "
            + ("is gone" if disk.document is None else "differs from the wiring in force")
            + ": it changed outside the app, and is not in force until this wiring "
            "is saved or reset, or Ephymeris restarts. The wiring shown is the one in "
            "force; until then boxes run the wiring in force."
        ))
    return out


def _flag(message: str) -> dict[str, Any]:
    return {"location": store.WIRING_FILENAME, "message": message, "code": None}


def _content(doc: dict | None) -> dict | None:
    """A document's wiring, without when its file was written."""
    return None if doc is None else {k: v for k, v in doc.items() if k != "edited_at"}


def preview_payload(
    rig: store.HardwareStore,
    document: Any,
    breaks: list[dict[str, Any]],
    *,
    in_force: InForce | None = None,
    confirmed_pins: bool = False,
) -> dict[str, Any]:
    """`RigSaved` without the save: what is wrong with the draft, and what it
    would cost (`breaks`, from the rig definition's impact check).

    `status` describes the wiring currently IN FORCE -- its notices stand
    whatever the draft says -- and whether THIS draft may be saved.
    """
    state = rig_state(rig, in_force)
    return {
        "status": _status(rig, state, draft=document, confirmed_pins=confirmed_pins),
        "problems": _draft_problems(state, document, confirmed_pins=confirmed_pins),
        "breaks": breaks,
        "allocations": [a.to_json() for a in planned_allocations(document)],
    }


def planned_allocations(document: Any) -> list:
    """The edge codes a save of `document` would issue (TASKS.md#edge-codes),
    against the vocabulary in force. Nothing for a document that fails the
    schema: it will not be saved, so it will issue nothing."""
    from ephymeris_sidecar.rig import allocation, registry

    if store.validate(document):
        return []
    return allocation.plan(document, registry.vocabulary())[1]


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
        return [{"location": "wiring.json", "message": str(exc), "code": None}]

    vocab = registry.vocabulary()
    return [
        {"location": loc, "message": msg, "code": code}
        for code, pairs in (
            ("RIG101", chans.disagreements()),
            ("RIG102", chans.pin_problems()),
            ("RIG103", chans.duplicate_pins()),
            ("RIG104", chans.slot_problems(vocab)),
            ("RIG105", chans.sync_problems()),
            ("RIG106", chans.onset_problems(vocab)),
            ("RIG107", chans.edge_problems(vocab)),
        )
        for loc, msg in pairs
    ]


def _status(
    rig: store.HardwareStore,
    state: _Rig | None = None,
    *,
    draft: Any = None,
    confirmed_pins: bool = False,
) -> dict[str, Any]:
    """`RigStatus`: of the wiring IN FORCE, with the rig's notices, and
    whether `draft` may be saved (the served draft when none is given)."""
    from ephymeris_sidecar.rig import registry

    state = state or rig_state(rig, None)
    in_force = state.in_force
    doc = in_force.document if in_force.document is not None else store.default_document()
    custom = in_force.document is not None
    notices = notices_for(state)
    served = served_draft(state)
    draft = served if draft is None else draft
    dirty = _content(draft) != _content(served)
    can_save = (
        save_blocked(state, confirmed_pins=confirmed_pins) is None
        and not _draft_problems(state, draft, confirmed_pins=confirmed_pins)
        # A notice is cleared by saving this draft, even unedited.
        and (dirty or bool(notices))
    )
    return {
        "custom": custom,
        "derivedFrom": str(doc.get("derived_from") or "") or registry.active_pinout_id(),
        "board": str(doc.get("board", "")),
        "editedAt": doc.get("edited_at") if custom else None,
        "pinoutHash": registry.channels().content_hash(),
        "channelSetHash": registry.channel_set().content_hash(),
        "notices": notices,
        # Every notice offers Reset (or a save) as the way out, so Reset is
        # offered with it, even when nothing of the rig's own is in force.
        "canReset": custom or bool(state.paths) or bool(notices),
        "resetReplaces": state.paths,
        "canSave": can_save,
        "needsPinConfirmation": bool(in_force.problem) and state.disk.state == "mismatched",
    }


def saved_payload(
    rig: store.HardwareStore, doc: dict, *, in_force: InForce | None = None
) -> dict[str, Any]:
    return {
        "status": _status(rig, rig_state(rig, in_force)),
        "problems": problems_for(doc),
        "breaks": [],
        "allocations": [],
    }
