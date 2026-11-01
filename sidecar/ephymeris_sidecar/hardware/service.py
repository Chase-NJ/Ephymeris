"""Rig wiring → wire shapes.

The central rule: a document that is WELL-FORMED and describes an impossible box
is not a command error. It is a successful reply carrying located problems.
`RIG_INVALID` is reserved for a document that is not a document.

`problems` comes from two places and reads as one list:

  * the JSON Schema, for shape -- a `kind` that is not a kind, a missing pin;
  * the wiring rules (`RIG101`-`RIG107`, `RIG109`), for sense -- a pin the board does not
    have, two channels on one pin, a response port with no strobe slot, an odor
    line with no onset code of its own, halves that describe different boxes, a
    channel-set declaration that contradicts itself.

They are merged rather than reported separately because an operator fixing new
wiring does not care which layer objected, and running one and then the other
would make it a two-pass job.

WHAT IS IN FORCE, WHAT THE EDITOR SHOWS, AND WHAT IS ON DISK are three things,
and every reply is built from one decision about how they relate (`_served`):
the draft the editor opens, whether its pins must be confirmed (RIG108), and
each notice's sentence about what the editor shows all come from it, so a
notice can never describe a draft the editor is not showing.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from . import store


class InForce(NamedTuple):
    """The wiring in force (`RigDefinition.in_force`): the stored document the
    registry composes, or None for the shipped one; and, when stored wiring
    exists but is not in force, the refusal every box is under."""

    document: dict | None
    problem: str | None
    #: Why stored wiring is not in force: True when it was held (not saved or
    #: confirmed here, or saved here but a save after it did not finish), False
    #: when it did not load. Meaningless without `problem`.
    held: bool = False


def installed(disk: store.Stored) -> InForce:
    """What installing the stored wiring `disk` puts in force: only wiring
    that loads and was saved here; anything else the shipped pins, refused."""
    if disk.state == "loads":
        return InForce(disk.document, None)
    if disk.state == "none":
        return InForce(None, None)
    if disk.state == "held":
        return InForce(None, held_message(disk), held=True)
    return InForce(None, unloaded_message(disk.problems[0][1]))


def unloaded_message(problem: str) -> str:
    """The refusal while stored wiring did not load: what is in force, and what
    that blocks. The wire error says exactly this; `hardware.get` says what
    the file is NOW in a notice of its own."""
    return (
        f"{problem} The shipped pins are in force, so no box can start, be flashed "
        "or identified until this rig's wiring is repaired, confirmed and saved, or reset."
    )


def held_message(disk: store.Stored) -> str:
    """The refusal while stored wiring is held: nobody saved it here, or a
    save after it did not finish."""
    return (
        f"{_names(disk.sources)} {_held_why(disk)}, so the shipped pins are in force and "
        "no box can start, be flashed or identified until its pins are confirmed and it "
        "is saved, or the wiring is reset."
    )


def _held_why(disk: store.Stored) -> str:
    """Why held wiring is held, as true of the file named before it."""
    if disk.interrupted:
        return (
            f"{'was' if len(disk.sources) == 1 else 'were'} saved here, but a save after "
            f"{_it(disk.sources)} did not finish"
        )
    return f"{_is(disk.sources)} not saved or confirmed on this machine"


#: The first notice while a refusal stands. No reason in it: the reason belongs
#: to the file as it was, and the next notice says what it is now.
IN_FORCE_UNLOADED = (
    "The shipped pins are in force: this rig's stored wiring did not load when it "
    "was installed, so no box can start, be flashed or identified until the wiring "
    "is repaired, confirmed and saved, or reset. A restart lifts this only onto the "
    "wiring last saved here."
)
IN_FORCE_HELD = (
    "The shipped pins are in force: this rig's stored wiring was not saved or "
    "confirmed on this machine when it was installed, so it is held, and no box can "
    "start, be flashed or identified until its pins are confirmed and it is saved, "
    "or the wiring is reset. A restart never confirms it."
)
IN_FORCE_INTERRUPTED = (
    "The shipped pins are in force: this rig's stored wiring was saved here, but a "
    "save after it did not finish, so it was held when it was installed, and no box "
    "can start, be flashed or identified until its pins are confirmed and it is saved, "
    "or the wiring is reset. A restart never confirms it."
)


class _Rig(NamedTuple):
    """Everything a reply says about the rig, from one read of the disk."""

    in_force: InForce
    disk: store.Stored
    paths: list[str]


def rig_state(rig: store.HardwareStore, in_force: InForce | None) -> _Rig:
    disk = rig.inspect()
    return _Rig(in_force or installed(disk), disk, [str(p) for p in rig.stored_paths()])


# --------------------------------------------------------------------------- #
# The one decision: what the editor shows
# --------------------------------------------------------------------------- #


def _served(state: _Rig) -> tuple[dict, str]:
    """(the draft `hardware.get` serves, where it comes from): `"disk"`, a
    stored file that is not in force; `"in_force"`; or `"shipped"`.

    The stored file, when it is not in force and there is something in it to
    act on: while the shipped pins are refused, any document there is (to
    check, repair, or confirm the pins of); while wiring is in force, a file
    that would load, or a mismatched pair, and differs from it. A file that
    will not load beside working wiring is not served: the wiring in force is,
    and saving it replaces the file.
    """
    disk, in_force = state.disk, state.in_force
    if disk.document is not None and _content(disk.document) != _content(in_force.document):
        servable = ("loads", "held", "invalid", "mismatched") if in_force.problem else (
            "loads", "held", "mismatched"
        )
        if disk.state in servable:
            return disk.document, "disk"
    if in_force.document is not None:
        return in_force.document, "in_force"
    return store.default_document(), "shipped"


def served_draft(state: _Rig) -> dict:
    return _served(state)[0]


def needs_confirmation(state: _Rig) -> bool:
    """The served draft's pins came from a stored file nobody saved here, or
    one that did not load: they must be confirmed before a save (RIG108)."""
    return _served(state)[1] == "disk" and state.disk.state != "loads"


def _unconfirmed(state: _Rig) -> str:
    """What RIG108 says, for where the draft's pins came from."""
    disk = state.disk
    if disk.state == "mismatched":
        source = (
            f"These pins come from {store.PIN_MAP_FILENAME}, which was not written with "
            f"{store.CHANNEL_SET_FILENAME}."
        )
    elif disk.state == "invalid":
        source = f"These pins come from {_names(disk.sources)}, which did not load."
    elif disk.interrupted:
        it = _it(disk.sources)
        source = (
            f"These pins come from {_names(disk.sources)}, saved here, but a save after "
            f"{it} did not finish, so the record cannot vouch for {it}."
        )
    else:
        source = (
            f"These pins come from {_names(disk.sources)}, which {_is(disk.sources)} not "
            "saved or confirmed on this machine: copied in, or changed outside the app."
        )
    return f"{source} Check every pin against the box and confirm them before saving."


def save_blocked(state: _Rig, *, confirmed_pins: bool) -> str | None:
    """Why the rig's state refuses any save now (`RIG_SAVE_BLOCKED`), or None."""
    if state.in_force.problem and state.disk.state in ("unrepairable", "none"):
        where = ", ".join(state.paths) or "nothing on disk"
        return (
            "There is no stored wiring to repair, so a save is refused: Reset "
            f"replaces it ({where}) and puts the shipped pins in force."
        )
    if needs_confirmation(state) and not confirmed_pins:
        return _unconfirmed(state)
    return None


def _draft_problems(state: _Rig, draft: Any, *, confirmed_pins: bool) -> list[dict[str, Any]]:
    out = problems_for(draft)
    if needs_confirmation(state) and not confirmed_pins:
        out = [{"location": "pins", "message": _unconfirmed(state), "code": "RIG108"}] + out
    return out


# --------------------------------------------------------------------------- #
# Notices: the rig's, each true of what is in force and what the editor shows
# --------------------------------------------------------------------------- #


class _Notice(NamedTuple):
    location: str
    message: str
    #: Saving the served draft clears it, so an unedited draft may be saved.
    cleared_by_save: bool = True


def _notices(state: _Rig) -> list[_Notice]:
    """Where the wiring in force and the stored files part ways, each saying
    what it does and does not block (`RigStatus.notices`). The file is always
    described as it is NOW, beside what is in force; what the editor shows is
    always `_served`'s answer."""
    in_force, disk = state.in_force, state.disk
    names = _names(disk.sources) or store.WIRING_FILENAME
    now = disk.problems[0][1] if disk.problems else ""
    if in_force.problem:
        first = (
            IN_FORCE_UNLOADED if not in_force.held
            else IN_FORCE_INTERRUPTED if disk.interrupted
            else IN_FORCE_HELD
        )
        messages = [first, _now(state, names, now)]
    else:
        messages = _beside_wiring_in_force(state, names, now)
    out = [_Notice(store.WIRING_FILENAME, m) for m in messages]
    if disk.shadows:
        one = len(disk.shadows) == 1
        it = "it" if one else "them"
        out.append(_Notice(
            disk.shadows[0],
            f"{_names(disk.shadows)} {_is(disk.shadows)} on disk beside {names} and "
            f"{_is(disk.shadows)} not read: {names} wins. {'It is' if one else 'They are'} "
            "not wiring saved here (copied in, or left by a save or Reset that did not "
            f"finish), so no save removes {it}; Reset does, or remove {it} by hand.",
            cleared_by_save=False,
        ))
    if disk.record_problem and disk.state != "none":
        out.append(_Notice(
            store.CONFIRMED_FILENAME,
            f"{disk.record_problem}, so no stored wiring is trusted: check every pin "
            "against the box, confirm them and save to record the wiring again, or Reset.",
        ))
    return out


def _now(state: _Rig, names: str, now: str) -> str:
    """While the shipped pins are refused: what the stored wiring is now."""
    disk = state.disk
    if disk.state == "loads":
        return (
            f"Now {names} loads, and it is the wiring last saved here. The editor shows "
            "it, not in force: save it to put it in force."
        )
    if disk.state == "held" and disk.interrupted:
        return (
            f"Now {names} {_is(disk.sources)} on disk: saved here, but a save after "
            f"{_it(disk.sources)} did not finish. The editor shows that wiring, not in force: "
            "check every pin against the box, confirm them, then save to put it in force."
        )
    if disk.state == "held":
        return (
            f"Now {names} {_is(disk.sources)} on disk, not saved or confirmed here. The "
            "editor shows that wiring, not in force: check every pin against the box, "
            "confirm them, then save to put it in force."
        )
    if disk.state == "invalid":
        return (
            f"Now: {now} The editor shows that stored wiring, not in force: repair it, "
            "check and confirm every pin, then save to put it in force."
        )
    if disk.state == "mismatched":
        return (
            f"Now: {now} The editor shows the two files joined, not in force: check "
            "every pin against the box, confirm them, then save to put them in force."
        )
    if disk.state == "unrepairable":
        return (
            f"Now: {now} There is no stored wiring to repair, so the editor shows the "
            f"shipped pins and Save is off. Reset replaces {', '.join(state.paths)}."
        )
    return "Now there is no stored wiring on disk. Save is off; Reset puts the shipped pins in force."


def _beside_wiring_in_force(state: _Rig, names: str, now: str) -> list[str]:
    """While boxes run: what the stored files are, beside the wiring in force."""
    in_force, disk = state.in_force, state.disk
    which = "this rig's own" if in_force.document is not None else "the shipped pins"
    if disk.state == "none":
        if in_force.document is None:
            return []
        return [
            "The stored wiring on disk is gone: it was removed outside the app. The "
            f"editor shows the wiring in force ({which}), and boxes run the wiring in "
            "force; save it to store it again, or a restart would run the shipped pins."
        ]
    if _served(state)[1] == "disk":
        held = disk.state != "loads"
        if disk.state == "mismatched":
            lead, what = now, "the two files joined"
        else:
            differ = "differs" if len(disk.sources) == 1 else "differ"
            lead = f"{names} on disk {differ} from the wiring in force" + (
                ": copied in or changed outside the app, and not saved or confirmed here."
                if held else ", and is wiring saved here before."
            )
            what = "that wiring"
        act = (
            "check every pin against the box, confirm them, then save to put it in force, or Reset"
            if held else "save it to put it in force, or Reset"
        )
        after = (
            "after a restart no box runs until it is confirmed and saved, or reset"
            if held else "a restart would put it in force"
        )
        return [
            f"{lead} The editor shows {what}, not in force: {act}. Until then boxes run "
            f"the wiring in force ({which}); {after}."
        ]
    # From here the editor shows the wiring in force.
    if disk.state == "held":
        return [
            f"{names} on disk is the wiring in force, but it is no longer recorded as "
            "saved here, so after a restart no box would run until it is confirmed. The "
            "editor shows the wiring in force, and boxes run the wiring in force: save it "
            "to record it again, or Reset."
        ]
    if disk.problems:
        return [
            f"{now} The editor shows the wiring in force ({which}), loaded before the "
            "file changed, and boxes run the wiring in force: save it to replace the "
            "file. After a restart no box runs until the wiring is repaired, confirmed "
            "and saved, or reset."
        ]
    return []


def _wire(notices: list[_Notice]) -> list[dict[str, Any]]:
    """`RigStatus.notices`, as the wire carries them."""
    return [{"location": n.location, "message": n.message, "code": None} for n in notices]


def _content(doc: dict | None) -> dict | None:
    """A document's wiring, without when its file was written."""
    return None if doc is None else {k: v for k, v in doc.items() if k != "edited_at"}


def _names(names: tuple[str, ...]) -> str:
    """File names as a notice lists them: `a and b`, or `a, b, c`."""
    return " and ".join(names) if len(names) <= 2 else ", ".join(names)


def _is(names: tuple[str, ...]) -> str:
    """The verb that agrees with `_names(names)`."""
    return "is" if len(names) == 1 else "are"


def _it(names: tuple[str, ...]) -> str:
    """The pronoun that stands for `_names(names)`."""
    return "it" if len(names) == 1 else "them"


# --------------------------------------------------------------------------- #
# Payloads
# --------------------------------------------------------------------------- #


def document_payload(rig: store.HardwareStore, *, in_force: InForce | None = None) -> dict[str, Any]:
    """`RigDocument`: the draft the editor opens, its problems, and the rig's.

    The draft is `served_draft`. `problems` are the draft's; what is wrong
    with the RIG (wiring not in force, a file changed on disk) is
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
    from ephymeris_sidecar.rig.rules import rule_problems

    return [
        {"location": loc, "message": msg, "code": code}
        for code, loc, msg in rule_problems(document)
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
    notices = _notices(state)
    served = served_draft(state)
    draft = served if draft is None else draft
    dirty = _content(draft) != _content(served)
    can_save = (
        save_blocked(state, confirmed_pins=confirmed_pins) is None
        and not _draft_problems(state, draft, confirmed_pins=confirmed_pins)
        # A notice a save clears is cleared by saving this draft, even unedited.
        and (dirty or any(n.cleared_by_save for n in notices))
    )
    return {
        "custom": custom,
        "derivedFrom": str(doc.get("derived_from") or "") or registry.active_pinout_id(),
        "board": str(doc.get("board", "")),
        "editedAt": doc.get("edited_at") if custom else None,
        "pinoutHash": registry.channels().content_hash(),
        "channelSetHash": registry.channel_set().content_hash(),
        "notices": _wire(notices),
        # Every notice offers Reset (or a save) as the way out, so Reset is
        # offered with it, even when nothing of the rig's own is in force.
        "canReset": custom or bool(state.paths) or bool(notices),
        "resetReplaces": state.paths,
        "canSave": can_save,
        "needsPinConfirmation": needs_confirmation(state),
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
