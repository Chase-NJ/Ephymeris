"""The vocabulary document, and every edit to it.

Layout, under the sidecar's own data dir (beside `ephymeris.db`):

    <data_dir>/strobes/vocabulary.json

THE ONE SOURCE OF EVERY STROBE CODE. The generated `TaskPins.h` defines `BF_*`
from it, `tasks/profile.py` fills every profile's `strobes` map from it, and the
Strobes page edits it. It used to be three hand-mirrored copies (a bundled JSON
registry, `BoxStrobes.h`, each sketch's `task.json`) held in step by a test.

SEEDED, NOT MERGED. The first start on a machine copies the shipped default;
after that the default is never read again there. A merge on every start would
mean a code an operator removed came back with the next app update — the same
argument `hardware/store.py` makes for the rig document. There is deliberately
no Reset: a reset could drop a code this machine added and then reissue its
number to something else.

EVERY OPERATION HERE IS PURE: document in, new document out, or `StrobeRefused`.
The evidence a hazardous edit is judged against — which firmware names a code,
which recorded session contains one — is `usage.py`'s, gathered by the caller
and passed in, so the rules can be tested without an archive.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..rig.registry import STROBE_NAME, Vocabulary, default_vocabulary_document

log = logging.getLogger(__name__)

VOCAB_FILENAME = "vocabulary.json"

#: The document version this code writes. 2 stored `free_ranges`; 3 derives
#: them from `reserved` and the bounds.
VOCAB_VERSION = 3

#: Refuse before parsing. The lab's vocabulary is ~25 KB with its prose; a
#: megabyte is not a vocabulary.
MAX_VOCAB_BYTES = 512 * 1024

#: The origin stamped on a code added from the Strobes page.
OPERATOR_ORIGIN = "operator"


class StrobeRefused(Exception):
    """An edit the rules do not allow, or allow only with `confirm`.

    `reason` is one of the `ErrCode`s `app.py` maps it to, lower-cased:
    `invalid`, `required`, `in_recorded_session`, `would_break_tasks`,
    `import_conflict`, `unreadable`.
    """

    def __init__(self, reason: str, message: str, detail: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.detail = detail or {}
        super().__init__(message)


class VocabularyStore:
    """Reads and writes `<data_dir>/strobes/vocabulary.json`."""

    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "strobes"
        self.path = self.root / VOCAB_FILENAME

    def ensure_seeded(self) -> bool:
        """Write the shipped default if this machine has no vocabulary yet.

        Returns True when it wrote one. Never overwrites, whatever is on disk:
        a damaged document is a thing to repair, and replacing it would forget
        every code this machine added.
        """
        if self.path.exists():
            return False
        doc = default_vocabulary_document()
        doc["seeded_at"] = _now()
        self._write(doc)
        log.info("strobe vocabulary seeded from the shipped default at %s", self.path)
        return True

    def load(self) -> dict | None:
        """The document, or None when it is missing or will not read.

        None is the registry's cue to decode with the shipped default, which is
        logged there. Edits go through `load_strict`, which refuses instead.
        """
        try:
            return self.load_strict()
        except StrobeRefused as exc:
            log.error("strobe vocabulary unusable: %s", exc)
            return None

    def load_strict(self) -> dict:
        """The document, or `StrobeRefused('unreadable')`.

        WHY EDITS REFUSE RATHER THAN FALL BACK. Reading falls back to the seed
        so a damaged file costs labels, not a session. Editing must not: a code
        issued against the seed could take a number this machine already gave
        to something else, and that is the one mistake the vocabulary exists to
        prevent.
        """
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise StrobeRefused("unreadable", f"the strobe vocabulary is unreadable: {exc}") from exc
        if len(raw) > MAX_VOCAB_BYTES:
            raise StrobeRefused(
                "unreadable",
                f"the strobe vocabulary is {len(raw)} bytes, over the {MAX_VOCAB_BYTES} limit",
            )
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StrobeRefused("unreadable", f"the strobe vocabulary will not parse: {exc}") from exc
        doc = upgrade(doc)
        problems = validate(doc)
        if problems:
            raise StrobeRefused(
                "unreadable",
                f"the strobe vocabulary is invalid: {problems[0][0]}: {problems[0][1]}",
                {"problems": [{"location": loc, "message": msg} for loc, msg in problems]},
            )
        return doc

    def save(self, doc: dict) -> dict:
        """Validate, stamp and write. Returns the document as stored.

        Validation happens BEFORE the write: there is no state in which the file
        on disk is one the registry would refuse.
        """
        problems = validate(doc)
        if problems:
            raise StrobeRefused(
                "invalid",
                f"{problems[0][0]}: {problems[0][1]}",
                {"problems": [{"location": loc, "message": msg} for loc, msg in problems]},
            )
        stored = dict(doc)
        stored["edited_at"] = _now()
        self._write(stored)
        return stored

    def _write(self, doc: dict) -> None:
        """Write-then-rename, so a crash mid-save leaves the old document whole."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def upgrade(doc: Any) -> Any:
    """A version-2 document (stored `free_ranges`) read as version 3.

    Only an IMPORTED file can be v2 — a machine's own document starts at 3 —
    so this exists to let a vocabulary exported by an older build be merged.
    `free_ranges` is dropped rather than translated: it was the complement of
    the codes, and the shipped reservation is the one thing it said besides.
    """
    if not isinstance(doc, dict) or doc.get("vocab_version") != 2:
        return doc
    out = {k: v for k, v in doc.items() if k not in ("free_ranges", "_free_ranges_why")}
    out["vocab_version"] = VOCAB_VERSION
    out.setdefault("reserved", default_vocabulary_document().get("reserved", []))
    for entry in (out.get("retired") or {}).values():
        if isinstance(entry, dict):
            entry.pop("retired", None)
    return out


def validate(doc: Any) -> list[tuple[str, str]]:
    """(location, message) for every way this is not a usable vocabulary.

    Every problem, not the first — the same argument the rig document makes.
    The rules are the append-only guarantees in a form a file can be checked
    against: one number per name, one name per number across live AND retired,
    every code issuable on the wire, every port-slot name live.
    """
    if not isinstance(doc, dict):
        return [("vocabulary", "the vocabulary must be a JSON object")]
    out: list[tuple[str, str]] = []
    if doc.get("vocab_version") != VOCAB_VERSION:
        out.append(("vocab_version", f"expected {VOCAB_VERSION}, found {doc.get('vocab_version')!r}"))
        return out

    lo, hi = doc.get("code_min"), doc.get("code_max")
    if not _is_int(lo) or not _is_int(hi) or lo > hi:
        return out + [("code_max", "code_min and code_max must be integers, min <= max")]
    if hi > 999:
        # emitStrobe formats `%03d` and the host's parser is `^\d{1,3}\t\d+$`.
        out.append(("code_max", "a code above 999 is unparseable on the host and silently dropped"))
    reserved = doc.get("reserved", [])
    if not isinstance(reserved, list) or not all(
        isinstance(r, list) and len(r) == 2 and all(_is_int(x) for x in r) and r[0] <= r[1]
        for r in reserved
    ):
        out.append(("reserved", "reserved must be a list of [low, high] integer pairs"))
        reserved = []

    seen_codes: dict[int, str] = {}
    for section in ("codes", "retired"):
        entries = doc.get(section, {})
        if not isinstance(entries, dict):
            out.append((section, f"{section} must be an object"))
            continue
        for name, entry in entries.items():
            if name.startswith("_"):
                continue
            at = f"{section}.{name}"
            if not STROBE_NAME.match(name):
                out.append((at, "a name is upper snake case: letters, digits, underscores"))
            if name.startswith("BF_"):
                out.append((at, "the BF_ prefix is added by the header; leave it off the name"))
            if not isinstance(entry, dict) or not _is_int(entry.get("code")):
                out.append((at, "needs an integer code"))
                continue
            code = entry["code"]
            if not lo <= code <= hi:
                out.append((f"{at}.code", f"{code} is outside {lo}..{hi}"))
            if any(r_lo <= code <= r_hi for r_lo, r_hi in reserved):
                out.append((f"{at}.code", f"{code} is in a reserved range"))
            if code in seen_codes:
                out.append((f"{at}.code", f"{code} is already {seen_codes[code]}"))
            else:
                seen_codes[code] = name

    codes = doc.get("codes", {}) if isinstance(doc.get("codes"), dict) else {}
    retired = doc.get("retired", {}) if isinstance(doc.get("retired"), dict) else {}
    for name in codes:
        if not name.startswith("_") and name in retired:
            out.append((f"codes.{name}", "a name cannot be both live and retired"))

    slots = doc.get("port_slots", {})
    if not isinstance(slots, dict):
        out.append(("port_slots", "port_slots must be an object"))
    else:
        for slot, fields in slots.items():
            if slot.startswith("_"):
                continue
            if not slot.isdigit() or not isinstance(fields, dict):
                out.append((f"port_slots.{slot}", "a slot is a number mapping to six code names"))
                continue
            for role, name in fields.items():
                if name not in codes:
                    out.append((f"port_slots.{slot}.{role}", f"{name} is not a live code"))
    return out


# --------------------------------------------------------------------------- #
# Edits
# --------------------------------------------------------------------------- #


def add(
    doc: dict, name: str, code: int, *, rationale: str, emitted_on: str = ""
) -> dict:
    """A new live code. Refused unless the name is new and the number free.

    "New" is across live AND retired: a retired name reissued under a fresh
    number would read as one event type in any analysis spanning the change.
    """
    vocab = Vocabulary(doc)
    name = (name or "").strip()
    if not STROBE_NAME.match(name) or name.startswith("BF_"):
        raise StrobeRefused(
            "invalid",
            f"{name!r} is not a code name: upper snake case, starting with a letter, "
            "without the BF_ prefix (the header adds it).",
        )
    if name in vocab:
        raise StrobeRefused("invalid", f"{name} is already code {vocab.code_of(name)}.")
    if vocab.retired_entry(name) is not None:
        raise StrobeRefused(
            "invalid",
            f"{name} is retired as code {vocab.retired_entry(name).code}. Reinstate it "
            "rather than issuing the name a second number.",
        )
    if not _is_int(code) or not vocab.is_free(code):
        taken = (vocab.name_of(code) or vocab.retired_name(code)) if _is_int(code) else None
        why = (
            f"it is {taken}" if taken
            else "it is reserved" if _is_int(code) and vocab.is_reserved(code)
            else f"it is outside {vocab.code_min}..{vocab.code_max}"
        )
        raise StrobeRefused("invalid", f"{code} cannot be issued: {why}.")
    if not (rationale or "").strip():
        raise StrobeRefused(
            "invalid",
            "say what the code means. A number in the archive with no recorded "
            "meaning is a question nobody will be able to answer later.",
        )
    out = copy.deepcopy(doc)
    out["codes"][name] = {
        "code": code,
        "origin": OPERATOR_ORIGIN,
        "added_at": _now(),
        **({"emitted_on": emitted_on.strip()} if emitted_on.strip() else {}),
        "rationale": rationale.strip(),
    }
    out["codes"] = _sorted_section(out["codes"])
    return out


def edit(doc: dict, name: str, *, rationale: str, emitted_on: str = "") -> dict:
    """Reword what a live code means. The name and the number never change."""
    entry = doc.get("codes", {}).get(name)
    if not isinstance(entry, dict):
        raise StrobeRefused("invalid", f"{name} is not a live code.")
    if not (rationale or "").strip():
        raise StrobeRefused("invalid", "a code's meaning cannot be blank.")
    out = copy.deepcopy(doc)
    target = out["codes"][name]
    target["rationale"] = rationale.strip()
    if emitted_on.strip():
        target["emitted_on"] = emitted_on.strip()
    else:
        target.pop("emitted_on", None)
    return out


def retire(doc: dict, name: str) -> dict:
    """Move a live code to `retired`: reserved forever, emitted by nothing.

    Refused for a port-slot code, because a slot with a missing code is a
    response port that silently reports nothing (`RIG104`'s reason to exist).
    Whether firmware still names the code is the CALLER's check — it needs the
    sketch library — and so is the confirm for tasks it would break.
    """
    entry = doc.get("codes", {}).get(name)
    if not isinstance(entry, dict):
        raise StrobeRefused("invalid", f"{name} is not a live code.")
    _refuse_if_slotted(doc, name, "retired")
    out = copy.deepcopy(doc)
    live = out["codes"].pop(name)
    out.setdefault("retired", {})[name] = {
        "code": live["code"],
        # Kept so a reinstated code comes back as what it was.
        "origin": live.get("origin", "firmware"),
        "retired_at": _now(),
        **({"emitted_on": live["emitted_on"]} if live.get("emitted_on") else {}),
        **({"rationale": live["rationale"]} if live.get("rationale") else {}),
    }
    out["retired"] = _sorted_section(out["retired"])
    return out


def reinstate(doc: dict, name: str) -> dict:
    """A retired code back to live, under its own name, number and meaning.

    Safe by construction: the name and number were never issued to anything
    else, because retiring kept both out of the free pool.
    """
    entry = doc.get("retired", {}).get(name)
    if not isinstance(entry, dict):
        raise StrobeRefused("invalid", f"{name} is not retired.")
    if name in doc.get("codes", {}):  # pragma: no cover - validate() forbids it
        raise StrobeRefused("invalid", f"{name} is already live.")
    out = copy.deepcopy(doc)
    old = out["retired"].pop(name)
    out["codes"][name] = {
        "code": old["code"],
        "origin": old.get("origin", "firmware"),
        "reinstated_at": _now(),
        **({"emitted_on": old["emitted_on"]} if old.get("emitted_on") else {}),
        "rationale": old.get("rationale", ""),
        **({"seen_in": old["seen_in"]} if old.get("seen_in") else {}),
    }
    out["codes"] = _sorted_section(out["codes"])
    return out


def remove(doc: dict, name: str, *, sessions_containing: int) -> dict:
    """Delete a code outright, returning its number to the free pool.

    THE BAR IS NOT "UNUSED". It is that no recorded session has ever contained
    the code, and the caller must have checked the archive to say so —
    `sessions_containing` is that check's answer, required rather than
    defaulted so a call site cannot skip it by omission. A code emitted once,
    to a file that still exists, goes to `retired` instead, whatever anyone
    argues.
    """
    section = "codes" if name in doc.get("codes", {}) else "retired"
    entry = doc.get(section, {}).get(name)
    if not isinstance(entry, dict):
        raise StrobeRefused("invalid", f"{name} is not in the vocabulary.")
    if sessions_containing > 0:
        raise StrobeRefused(
            "in_recorded_session",
            f"{name} is in {sessions_containing} recorded "
            f"session{'' if sessions_containing == 1 else 's'}. Removing it would let "
            f"code {entry['code']} be issued again, and every analysis spanning that "
            "change would read two different events as one. Retire it instead.",
        )
    _refuse_if_slotted(doc, name, "removed")
    out = copy.deepcopy(doc)
    del out[section][name]
    return out


@dataclass
class MergePlan:
    """What importing another machine's vocabulary would do."""

    adds: list[dict[str, Any]] = field(default_factory=list)
    retires: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: Codes this machine has and the other does not. Reported, never acted on:
    #: absence in an export is not a request to delete.
    only_here: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "adds": self.adds,
            "retires": self.retires,
            "conflicts": self.conflicts,
            "onlyHere": self.only_here,
        }


def plan_merge(doc: dict, other: Any) -> MergePlan:
    """Compare another machine's vocabulary with this one, changing nothing.

    A UNION, NEVER A REPLACEMENT. Two machines in one lab each add codes; the
    import brings over what this one lacks and nothing else. A conflict — one
    name with two numbers, or one number with two names — is exactly the
    divergence a shared archive cannot survive, so any conflict refuses the
    whole import rather than picking a winner.

    Retirement travels: a code retired there and live here is retired here
    too, because some session on that machine contains it and its emitter is
    gone. Never the reverse — a code live there and retired here stays
    retired; reinstating is a decision for someone looking at this machine.
    """
    other = upgrade(other)
    problems = validate(other)
    if problems:
        loc, msg = problems[0]
        raise StrobeRefused("invalid", f"that file is not a strobe vocabulary: {loc}: {msg}")

    def index(d: dict) -> dict[str, tuple[int, str]]:
        out: dict[str, tuple[int, str]] = {}
        for section in ("codes", "retired"):
            for name, entry in d.get(section, {}).items():
                if not name.startswith("_") and isinstance(entry, dict):
                    out[name] = (entry["code"], section)
        return out

    here, there = index(doc), index(other)
    by_code_here = {code: name for name, (code, _s) in here.items()}
    plan = MergePlan()

    for name, (code, section) in sorted(there.items(), key=lambda kv: kv[1][0]):
        mine = here.get(name)
        if mine is not None and mine[0] != code:
            plan.conflicts.append({
                "name": name, "code": code,
                "message": f"{name} is {mine[0]} here and {code} there",
            })
            continue
        holder = by_code_here.get(code)
        if holder is not None and holder != name:
            plan.conflicts.append({
                "name": name, "code": code,
                "message": f"{code} is {holder} here and {name} there",
            })
            continue
        if mine is None:
            if any(lo <= code <= hi for lo, hi in doc.get("reserved", [])) or not (
                doc["code_min"] <= code <= doc["code_max"]
            ):
                plan.conflicts.append({
                    "name": name, "code": code,
                    "message": f"{code} is not issuable on this machine",
                })
                continue
            plan.adds.append({"name": name, "code": code, "retired": section == "retired"})
        elif mine[1] == "codes" and section == "retired":
            plan.retires.append({"name": name, "code": code})

    plan.only_here = sorted(n for n in here if n not in there)
    return plan


def apply_merge(doc: dict, other: dict, plan: MergePlan) -> dict:
    """The document with `plan` applied. Refuses if the plan has a conflict."""
    if plan.conflicts:
        raise StrobeRefused(
            "import_conflict",
            f"{len(plan.conflicts)} code{'' if len(plan.conflicts) == 1 else 's'} "
            "disagree between the two machines; nothing was imported.",
            {"conflicts": plan.conflicts},
        )
    other = upgrade(other)
    out = copy.deepcopy(doc)
    for add_ in plan.adds:
        section = "retired" if add_["retired"] else "codes"
        entry = copy.deepcopy(other[section][add_["name"]])
        entry["imported_at"] = _now()
        out.setdefault(section, {})[add_["name"]] = entry
    for ret in plan.retires:
        out = retire(out, ret["name"])
    out["codes"] = _sorted_section(out["codes"])
    out["retired"] = _sorted_section(out.get("retired", {}))
    return out


def export_document(doc: dict) -> dict:
    """The document as it travels: the vocabulary, without this machine's stamps."""
    return {k: v for k, v in doc.items() if k not in ("seeded_at", "edited_at")}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _refuse_if_slotted(doc: dict, name: str, verb: str) -> None:
    for slot, fields in doc.get("port_slots", {}).items():
        if not slot.startswith("_") and isinstance(fields, dict) and name in fields.values():
            raise StrobeRefused(
                "required",
                f"{name} is how a response port on slot {slot} reports, and cannot be "
                f"{verb} while the slot names it — a port with a missing code reports "
                "nothing, silently.",
            )


def _sorted_section(section: dict) -> dict:
    """By code, with `_`-prefixed notes first — the order a reader scans in."""
    notes = {k: v for k, v in section.items() if k.startswith("_")}
    entries = sorted(
        ((k, v) for k, v in section.items() if not k.startswith("_")),
        key=lambda kv: kv[1].get("code", 0) if isinstance(kv[1], dict) else 0,
    )
    return {**notes, **dict(entries)}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
