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
    that blocks. The wire error and `hardware.get` both say exactly this."""
    return (
        f"{problem} The shipped pins are in force, so no box can start, be flashed "
        "or identified until this rig's wiring is saved or reset, or Ephymeris "
        "restarts onto a file that loads."
    )


def document_payload(rig: store.HardwareStore, *, in_force: InForce | None = None) -> dict[str, Any]:
    """`RigDocument`: the draft the editor opens, its problems, and the rig's.

    The draft is the wiring IN FORCE -- what the registry composes and every
    box runs -- except while stored wiring did not load. Then it is that stored
    document, broken, so the operator can repair their own wiring rather than
    retype it over the shipped pins; or the shipped pins when it will not even
    parse. `problems` are the draft's. What is wrong with the RIG (unloaded
    wiring, a file changed on disk) is `status.notices`, which stand through
    every edit and never block the save that clears them. An unedited rig gets
    the shipped pinout, so the editor opens something real. `in_force`
    defaults to what the file would install now.
    """
    in_force = in_force or _from_disk(rig)
    if in_force.problem:
        doc = rig.stored_document() or store.default_document()
    else:
        doc = in_force.document if in_force.document is not None else store.default_document()
    return {
        "document": doc,
        "status": _status(rig, in_force),
        "problems": problems_for(doc),
    }


def notices_for(rig: store.HardwareStore, in_force: InForce) -> list[dict[str, Any]]:
    """Where the wiring in force and the stored file part ways, each saying
    what it does and does not block (`RigStatus.notices`)."""
    disk, disk_problems = rig.snapshot()
    out: list[dict[str, Any]] = []
    if in_force.problem:
        draft = (
            " The draft below is that stored wiring, which is not in force: repair it "
            "and save to put it in force."
            if rig.stored_document() is not None
            else (
                " The stored file will not even parse, so the draft below starts from "
                "the shipped pins."
                if rig.exists()
                else ""
            )
        )
        out.append(_flag(in_force.problem + draft))
    if disk_problems and in_force.problem is None:
        out.append(_flag(
            f"{disk_problems[0][1]} The wiring shown is the one in force, loaded before "
            "the file changed, and boxes run the wiring in force. A restart onto this "
            "file would stop every box until the wiring is saved or reset."
        ))
    elif not disk_problems and _content(disk) != _content(in_force.document):
        until = (
            "until then the refusal above stands"
            if in_force.problem
            else "until then boxes run the wiring in force"
        )
        out.append(_flag(
            f"{store.WIRING_FILENAME} on disk "
            + ("is gone" if disk is None else "differs from the wiring in force")
            + ": it changed outside the app, and is not in force until this wiring "
            "is saved or reset, or Ephymeris restarts. "
            + ("The draft is the stored file; " if in_force.problem else "The wiring shown is the one in force; ")
            + f"{until}."
        ))
    return out


def _from_disk(rig: store.HardwareStore) -> InForce:
    """What installing the file now would put in force."""
    disk, problems = rig.snapshot()
    return InForce(disk, unloaded_message(problems[0][1]) if problems else None)


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
) -> dict[str, Any]:
    """`RigSaved` without the save: what is wrong with the draft, and what it
    would cost (`breaks`, from the rig definition's impact check).

    `status` describes the wiring currently IN FORCE, not the one being
    previewed -- the operator is comparing a draft against what the rig is
    doing now, and its notices stand whatever the draft says.
    """
    return {
        "status": _status(rig, in_force),
        "problems": problems_for(document),
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


def _status(rig: store.HardwareStore, in_force: InForce | None = None) -> dict[str, Any]:
    """`RigStatus`: of the wiring IN FORCE, with the rig's notices."""
    from ephymeris_sidecar.rig import registry

    in_force = in_force or _from_disk(rig)
    doc = in_force.document if in_force.document is not None else store.default_document()
    custom = in_force.document is not None
    notices = notices_for(rig, in_force)
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
        "canReset": custom or rig.exists() or bool(notices),
    }


def saved_payload(
    rig: store.HardwareStore, doc: dict, *, in_force: InForce | None = None
) -> dict[str, Any]:
    return {
        "status": _status(rig, in_force),
        "problems": problems_for(doc),
        "breaks": [],
        "allocations": [],
    }
