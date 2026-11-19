"""The session folder's `log.json` — `DATA.md#the-log-file`.

What a machine knows about a session beyond its run files, written beside
them so it travels with the folder: the session's record (which session this
is, when it ran, its rounds), who ran it and what they made of it, every note,
and the day's weigh-ins. `notes.md` is the same log for a person; this is the
one a machine reads back (`logbook/intake.py`).

Three things about the format do the work:

- **Animals are named.** An animal's id is this machine's own, and the same
  animal has another on the next machine. A note or a weigh-in says who it is
  about by name, with the id beside it for the machine that wrote it.
- **A deleted note stays, as a tombstone**: its id and when it went, never its
  words. Without one, a note deleted here would come back from the copy on the
  other machine at the next read. A removed weigh-in stays the same way.
- **Nothing in it changes unless the log did.** No "written at", no counter:
  the file is compared with what is on disk and left alone when equal, so an
  unchanged session costs no write and no backup copy.

`build` and `parse` are pure. `read` and `write` touch disk and never raise: a
file that cannot be read is no file, and one that cannot be written costs only
itself. A file from a newer build (`log_version` above `VERSION`) is not read
at all, since guessing at a format is how a log gets misfiled.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..sessions.models import Session
from .models import HealthEntry, SessionLog, SessionNote, parse_iso

log = logging.getLogger(__name__)

FILENAME = "log.json"

#: Bumped when a reader of the previous version would misread the file. A new
#: optional key does not need it.
VERSION = 1


@dataclass(frozen=True)
class FileNote:
    id: str
    #: When it was deleted on the machine that wrote the file; a tombstone
    #: carries this and `id` and nothing else.
    deleted_at: str | None = None
    at: str = ""
    created_at: str = ""
    edited_at: str | None = None
    tag: str = ""
    scope_kind: str = "session"
    animal: str | None = None
    animal_id: str | None = None
    box: int | None = None
    body: str = ""
    carry_forward: bool = False
    resolved_at: str | None = None
    #: The id, on the writing machine, of the session a flag was resolved in.
    resolved_in: str | None = None

    @property
    def stamp(self) -> str | None:
        """The latest thing that happened to the note: what "newer" means."""
        return latest(self.created_at, self.edited_at, self.resolved_at, self.deleted_at)


@dataclass(frozen=True)
class FileSession:
    id: str
    prefix: str
    number: str
    date: str
    started_at: str
    ended_at: str | None
    status: str
    rounds: tuple[dict[str, Any], ...]
    duration_minutes: int | None
    operator: str | None
    summary: str | None
    log_updated_at: str | None
    notes: tuple[FileNote, ...]


@dataclass(frozen=True)
class FileWeighIn:
    animal: str | None
    animal_id: str | None
    date: str
    #: When it was removed on the machine that wrote the file; a removed
    #: weigh-in carries this, who and which day, and no weight.
    removed_at: str | None = None
    weight_g: float = 0.0
    baseline: bool = False
    recorded_at: str = ""


@dataclass(frozen=True)
class LogFile:
    sessions: tuple[FileSession, ...]
    weigh_ins: tuple[FileWeighIn, ...]


def latest(*stamps: str | None) -> str | None:
    """The latest of these ISO instants, in its own spelling; None for none
    readable. Compared as instants, never as strings: two machines need not
    spell an offset alike."""
    best: tuple[Any, str] | None = None
    for stamp in stamps:
        moment = parse_iso(stamp)
        if moment is not None and (best is None or moment > best[0]):
            best = (moment, stamp or "")
    return None if best is None else best[1]


def newer(a: str | None, b: str | None) -> bool:
    """Whether instant `a` is strictly after `b`. An unreadable `b` is older
    than anything; an unreadable `a` is newer than nothing."""
    first, second = parse_iso(a), parse_iso(b)
    if first is None:
        return False
    return second is None or first > second


# --- writing ------------------------------------------------------------------


def note_stamp(note: SessionNote) -> str | None:
    return latest(note.created_at, note.edited_at, note.resolved_at, note.deleted_at)


def _note(note: SessionNote, names: dict[str, str]) -> dict[str, Any]:
    if note.deleted_at:
        return {"id": note.id, "deleted_at": note.deleted_at}
    return {
        "id": note.id,
        "at": note.at,
        "created_at": note.created_at,
        "edited_at": note.edited_at,
        "tag": note.tag,
        "scope": {
            "kind": note.scope_kind,
            "animal": names.get(note.animal_id) if note.animal_id else None,
            "animal_id": note.animal_id,
            "box": note.box_number,
        },
        "body": note.body,
        "carry_forward": note.carry_forward,
        "resolved_at": note.resolved_at,
        "resolved_in": note.resolved_in_session,
    }


def build(
    *,
    cohort_name: str,
    sessions: Iterable[Session],
    logs: Iterable[SessionLog],
    notes: Iterable[SessionNote],
    weights: Iterable[HealthEntry],
    animal_names: dict[str, str],
) -> dict[str, Any]:
    """One folder's log. `sessions` are every record sharing the folder,
    `notes` theirs with the deleted ones, `weights` the weigh-ins of their days."""
    by_session: dict[str, list[SessionNote]] = {}
    for note in notes:
        by_session.setdefault(note.session_id, []).append(note)
    log_of = {entry.session_id: entry for entry in logs}
    out_sessions = []
    for session in sorted(sessions, key=lambda s: (s.clock_started_at, s.id)):
        entry = log_of.get(session.id)
        out_sessions.append({
            "id": session.id,
            "prefix": session.prefix_name,
            "number": session.session_number,
            "date": session.date,
            "started_at": session.started_at,
            "ended_at": session.ended_at,
            "status": session.status,
            "rounds": [
                {"order": r.order, "started_at": r.started_at, "ended_at": r.ended_at, "label": r.label}
                for r in session.rounds
            ],
            "duration_minutes": session.duration_minutes,
            "operator": entry.operator if entry else None,
            "summary": entry.summary if entry else None,
            "log_updated_at": entry.updated_at if entry else None,
            "notes": [
                _note(note, animal_names)
                for note in sorted(by_session.get(session.id, []), key=lambda n: (n.at, n.created_at, n.id))
            ],
        })
    return {
        "log_version": VERSION,
        "cohort": cohort_name,
        "sessions": out_sessions,
        "weigh_ins": [
            _weight(w, animal_names)
            for w in sorted(weights, key=lambda w: (w.date, animal_names.get(w.animal_id, w.animal_id).casefold(), w.animal_id))
        ],
    }


def _weight(entry: HealthEntry, names: dict[str, str]) -> dict[str, Any]:
    who = {"animal": names.get(entry.animal_id), "animal_id": entry.animal_id, "date": entry.date}
    if entry.removed_at:
        return {**who, "removed_at": entry.removed_at}
    return {
        **who,
        "weight_g": entry.weight_g,
        "baseline": entry.baseline,
        "recorded_at": entry.recorded_at,
    }


def dumps(document: dict[str, Any]) -> str:
    """Indented and in key order, so two writes of one log are byte-equal and
    the file can be read, and diffed, by a person."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write(folder: Path, text: str) -> Path | None:
    """Write `log.json` whole or not at all; None when unchanged or on any
    failure. Never creates the folder: that is the caller's call
    (`LogbookService`), and never a parent's (`mirror.write_mirror`)."""
    target = folder / FILENAME
    part = folder / f"{FILENAME}.part"
    try:
        if target.is_file() and target.read_text(encoding="utf-8") == text:
            return None
        part.write_text(text, encoding="utf-8", newline="\n")
        os.replace(part, target)
        return target
    except OSError as exc:
        log.warning("logbook: couldn't write %s (%s); the database copy is intact", target, exc)
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        return None


# --- reading ------------------------------------------------------------------


def read(folder: Path) -> tuple[LogFile | None, str | None]:
    """The folder's log and the text it was read from: (None, None) when there
    is no file, (None, text) when there is one that cannot be read."""
    target = folder / FILENAME
    try:
        if not target.is_file():
            return None, None
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("logbook: couldn't read %s (%s)", target, exc)
        return None, ""
    return parse(text, source=str(target)), text


def from_newer_build(text: str) -> bool:
    """Whether this is a log file a later build wrote in a format this one
    does not read. Such a file is neither taken in nor written over: rewriting
    it from here would drop whatever the newer format added."""
    try:
        raw = json.loads(text)
    except ValueError:
        return False
    version = raw.get("log_version") if isinstance(raw, dict) else None
    return isinstance(version, int) and not isinstance(version, bool) and version > VERSION


def parse(text: str, *, source: str = FILENAME) -> LogFile | None:
    """A log file's contents, or None for anything that is not one this build
    can read. Never raises. One bad note or weigh-in is dropped with a warning;
    it does not cost the rest of the file."""
    try:
        raw = json.loads(text)
    except ValueError as exc:
        log.warning("logbook: %s is not JSON (%s)", source, exc)
        return None
    if not isinstance(raw, dict):
        log.warning("logbook: %s is not a log file", source)
        return None
    version = raw.get("log_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        log.warning("logbook: %s names no log_version", source)
        return None
    if version > VERSION:
        log.warning(
            "logbook: %s is log_version %d, newer than this build reads (%d); left alone",
            source, version, VERSION,
        )
        return None
    sessions = tuple(
        session
        for item in _list(raw.get("sessions"))
        if (session := _session(item, source)) is not None
    )
    weigh_ins = tuple(
        weigh_in
        for item in _list(raw.get("weigh_ins"))
        if (weigh_in := _weigh_in(item)) is not None
    )
    return LogFile(sessions=sessions, weigh_ins=weigh_ins)


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _instant(value: Any) -> str | None:
    """An ISO instant with an offset, as every stamp in the log is; else None."""
    return value if isinstance(value, str) and parse_iso(value) is not None else None


def _session(raw: Any, source: str) -> FileSession | None:
    if not isinstance(raw, dict):
        return None
    sid, prefix, date = _text(raw.get("id")), _text(raw.get("prefix")), _text(raw.get("date"))
    number, started = raw.get("number"), _text(raw.get("started_at"))
    if not sid or not prefix or not date or not isinstance(number, str) or not started:
        log.warning("logbook: a session in %s names no id, prefix, number, date or start; skipped", source)
        return None
    minutes = raw.get("duration_minutes")
    return FileSession(
        id=sid,
        prefix=prefix,
        number=number,
        date=date,
        started_at=started,
        ended_at=_text(raw.get("ended_at")),
        status=str(raw.get("status") or "completed"),
        rounds=tuple(r for r in _list(raw.get("rounds")) if isinstance(r, dict)),
        duration_minutes=minutes if isinstance(minutes, int) and not isinstance(minutes, bool) else None,
        operator=_text(raw.get("operator")),
        summary=_text(raw.get("summary")),
        log_updated_at=_instant(raw.get("log_updated_at")),
        notes=tuple(
            note for item in _list(raw.get("notes")) if (note := _file_note(item)) is not None
        ),
    )


def _file_note(raw: Any) -> FileNote | None:
    if not isinstance(raw, dict):
        return None
    nid = _text(raw.get("id"))
    if not nid:
        return None
    deleted = _instant(raw.get("deleted_at"))
    if deleted:
        return FileNote(id=nid, deleted_at=deleted)
    at, created = _instant(raw.get("at")), _instant(raw.get("created_at"))
    body = raw.get("body")
    if not at or not created or not isinstance(body, str):
        return None
    scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
    box = scope.get("box")
    return FileNote(
        id=nid,
        at=at,
        created_at=created,
        edited_at=_instant(raw.get("edited_at")),
        tag=str(raw.get("tag") or ""),
        scope_kind=str(scope.get("kind") or "session"),
        animal=_text(scope.get("animal")),
        animal_id=_text(scope.get("animal_id")),
        box=box if isinstance(box, int) and not isinstance(box, bool) else None,
        body=body,
        carry_forward=raw.get("carry_forward") is True,
        resolved_at=_instant(raw.get("resolved_at")),
        resolved_in=_text(raw.get("resolved_in")),
    )


def _weigh_in(raw: Any) -> FileWeighIn | None:
    if not isinstance(raw, dict):
        return None
    date = _text(raw.get("date"))
    if not date:
        return None
    who = {"animal": _text(raw.get("animal")), "animal_id": _text(raw.get("animal_id")), "date": date}
    removed = _instant(raw.get("removed_at"))
    if removed:
        return FileWeighIn(**who, removed_at=removed)
    recorded, grams = _instant(raw.get("recorded_at")), raw.get("weight_g")
    if not recorded or isinstance(grams, bool) or not isinstance(grams, (int, float)):
        return None
    return FileWeighIn(
        **who,
        weight_g=float(grams),
        baseline=raw.get("baseline") is True,
        recorded_at=recorded,
    )
