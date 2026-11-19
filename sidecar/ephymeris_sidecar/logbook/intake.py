"""Reading a session folder's `log.json` into this machine's log —
`DATA.md#the-log-file`.

The database is where the log is kept and worked on; the folder's file is how
it travels (`DECISIONS.md#0011-the-log-travels-in-the-session-folder`). So a
folder that arrives from another machine carries notes this database has never
seen, and this is where they are taken in: by a Rescan, which may also record
the session itself, and before every rewrite of the file, so that nothing a
file holds is overwritten unread.

**A merge, never a replace**, and every rule is per item:

- A note is known by its id. One this database lacks is added; one it has
  takes the file's words only when the file's is **newer** (`FileNote.stamp`).
  A tombstone deletes a note it is newer than. A note the file does not
  mention is left alone: absence is not a deletion, or the older of two
  copies would erase everything written since it was made.
- Operator and summary go together, the newer `updated_at` winning.
- A weigh-in is known by animal and day, the newer `recorded_at` winning; a
  removal takes out a weigh-in it is newer than.
- **A session record is never changed.** One this database has is this
  machine's own account of the session. One it lacks is recorded only by a
  Rescan, as ended: a session is open only on the machine running it.

Animals are matched by name, since ids are each machine's own. A note about an
animal this cohort does not have is kept, under the id the file gave, and
named in the result; when the animal is later added, the next read re-points
the note. A weigh-in for one has nowhere to be kept and is left in the file.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

from ..cohorts.db import Database, Tx
from ..sessions.models import Round, Session, SessionNotFound
from ..sessions.tidy import session_key
from . import logfile
from .logfile import FileNote, FileSession, LogFile
from .models import (
    MAX_WEIGHT_G,
    MIN_WEIGHT_G,
    HealthEntry,
    NoteInvalid,
    SessionNote,
)
from .repository import LogbookRepository, check_note

log = logging.getLogger(__name__)


@dataclass
class Intake:
    """What reading one or more log files brought in."""

    #: Files read, whatever they held.
    files: int = 0
    #: Files that are there and cannot be read: damaged, or a newer build's.
    unreadable: int = 0
    #: Session records made, for sessions another machine ran.
    sessions: int = 0
    #: Notes added, brought up to date or deleted.
    notes: int = 0
    #: Sessions whose operator and summary were taken.
    logs: int = 0
    weigh_ins: int = 0
    #: Animals a note or weigh-in names that the cohort does not have.
    unknown_animals: set[str] = field(default_factory=set)
    #: Sessions here whose log changed: who to announce and re-mirror.
    touched: set[str] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return bool(self.sessions or self.notes or self.logs or self.weigh_ins)

    def add(self, other: "Intake") -> None:
        self.files += other.files
        self.unreadable += other.unreadable
        self.sessions += other.sessions
        self.notes += other.notes
        self.logs += other.logs
        self.weigh_ins += other.weigh_ins
        self.unknown_animals |= other.unknown_animals
        self.touched |= other.touched

    def to_json(self) -> dict[str, Any]:
        """The wire's `RescanLogs`."""
        return {
            "files": self.files,
            "unreadable": self.unreadable,
            "sessions": self.sessions,
            "notes": self.notes,
            "logs": self.logs,
            "weighIns": self.weigh_ins,
            "unknownAnimals": sorted(self.unknown_animals, key=str.casefold),
        }


class LogIntake:
    def __init__(self, *, db: Database, cohorts: Any, sessions: Any) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._repo = LogbookRepository(db)

    def read_cohort(self, cohort_id: str, folders: Iterable[Path]) -> Intake:
        """Read every one of these session folders' log files, recording the
        sessions this database lacks. For a Rescan, under the archive's lock
        (`DATA.md#the-cohort-archive`). A folder that fails costs only itself."""
        total = Intake()
        for folder in sorted({Path(f) for f in folders}):
            try:
                document, text = logfile.read(folder)
                if text is None:
                    continue
                total.files += 1
                if document is None:
                    total.unreadable += 1
                    continue
                total.add(self.take(cohort_id, folder, document, create_sessions=True))
            except Exception:  # noqa: BLE001 - one folder's log never costs the rescan
                log.exception("logbook: couldn't take in the log of %s", folder)
                total.unreadable += 1
        return total

    def take(
        self, cohort_id: str, folder: Path, document: LogFile, *, create_sessions: bool
    ) -> Intake:
        """Merge one folder's log file into the database, in one unit of work:
        a file is taken whole or not at all."""
        cohort = self._cohorts.get(cohort_id)
        animals = _Animals(cohort)
        result = Intake()
        with self._db.write() as tx:
            local = self._sessions.list_sessions(cohort_id, include_aborted=True)
            by_id = {s.id: s for s in local}
            by_key: dict[tuple[str, str, str], Session] = {}
            # The earliest record that wrote anything owns a folder's name, as
            # for recovered runs (`analytics/archive.py`'s `_adoption_owners`).
            for session in sorted(local, key=lambda s: (s.date, s.started_at, s.id)):
                if session.status != "aborted":
                    by_key.setdefault(
                        session_key(session.prefix_name, session.session_number, session.date), session
                    )

            home: dict[str, Session] = {}
            for incoming in document.sessions:
                target = by_id.get(incoming.id) or by_key.get(
                    session_key(incoming.prefix, incoming.number, incoming.date)
                )
                if target is None and create_sessions:
                    target = self._record(cohort_id, folder, incoming, tx)
                    by_id[target.id] = target
                    result.sessions += 1
                    result.touched.add(target.id)
                if target is not None:
                    home[incoming.id] = target

            for incoming in document.sessions:
                target = home.get(incoming.id)
                if target is None:
                    continue
                for note in incoming.notes:
                    if self._note(note, target, home, animals, result, tx):
                        result.notes += 1
                        result.touched.add(target.id)
                if self._fields(incoming, target, tx):
                    result.logs += 1
                    result.touched.add(target.id)

            days = {s.date: s.id for s in home.values()}
            for weigh_in in document.weigh_ins:
                if self._weigh_in(weigh_in, animals, result, tx):
                    result.weigh_ins += 1
                    if weigh_in.date in days:
                        result.touched.add(days[weigh_in.date])
        return result

    # --- sessions -----------------------------------------------------------

    def _record(self, cohort_id: str, folder: Path, incoming: FileSession, tx: Tx) -> Session:
        """Record a session another machine ran. Its id is kept, so the same
        file read twice finds the record it made; an id some other cohort's
        session already has (a folder copied between cohorts) gets a new one."""
        session_id = incoming.id
        try:
            self._sessions.get_session(session_id)
            session_id = str(uuid.uuid4())
        except SessionNotFound:
            pass
        rounds = [
            Round(
                order=int(raw.get("order", index)) if _is_int(raw.get("order", index)) else index,
                started_at=str(raw.get("started_at") or ""),
                ended_at=raw.get("ended_at") if isinstance(raw.get("ended_at"), str) else None,
                label=raw.get("label") if isinstance(raw.get("label"), str) else None,
            )
            for index, raw in enumerate(incoming.rounds)
            if isinstance(raw.get("started_at"), str) and raw.get("started_at")
        ]
        # Closed, whatever the file says: nothing is running here, and an open
        # record would hold this machine's rig for a session that is not on it.
        ends = [r.ended_at for r in rounds if r.ended_at]
        for open_round in rounds:
            if open_round.ended_at is None:
                open_round.ended_at = max(ends) if ends else open_round.started_at
        ended = incoming.ended_at or logfile.latest(*(r.ended_at for r in rounds)) or incoming.started_at
        log.info(
            "logbook: recording %s_%s (%s) from %s",
            incoming.prefix, incoming.number, incoming.date, folder / logfile.FILENAME,
        )
        return self._sessions.import_session(
            session_id=session_id,
            cohort_id=cohort_id,
            prefix_name=incoming.prefix,
            session_number=incoming.number,
            date=incoming.date,
            started_at=incoming.started_at,
            ended_at=ended,
            status="aborted" if incoming.status == "aborted" else "completed",
            folder_path=str(folder),
            rounds=rounds,
            duration_minutes=incoming.duration_minutes,
            tx=tx,
        )

    # --- notes --------------------------------------------------------------

    def _note(
        self,
        incoming: FileNote,
        target: Session,
        home: dict[str, Session],
        animals: "_Animals",
        result: Intake,
        tx: Tx,
    ) -> bool:
        """Whether the note changed anything here."""
        held = self._repo.find(incoming.id)
        if held is not None and held.cohort_id != target.cohort_id:
            return False  # another cohort's note of that id: not this folder's to touch
        if incoming.deleted_at:
            if held is None or held.deleted_at:
                return False
            if not logfile.newer(incoming.deleted_at, logfile.note_stamp(held)):
                return False
            self._repo.mark_deleted(held.id, incoming.deleted_at, tx=tx)
            return True

        animal_id = None
        if incoming.scope_kind == "animal":
            animal_id = animals.resolve(incoming.animal_id, incoming.animal)
            if animal_id is None:
                result.unknown_animals.add(incoming.animal or incoming.animal_id or "an unnamed animal")
                animal_id = incoming.animal_id
        if held is not None and not logfile.newer(incoming.stamp, logfile.note_stamp(held)):
            # Nothing newer to take. But an animal this cohort has since been
            # given is worth re-pointing an unchanged note at.
            if (
                incoming.stamp == logfile.note_stamp(held)
                and held.scope_kind == "animal"
                and animal_id
                and animal_id != held.animal_id
                and animals.known(animal_id)
            ):
                self._repo.set_animal(held.id, animal_id, tx=tx)
                return True
            return False

        resolved_in = home.get(incoming.resolved_in or "")
        note = SessionNote(
            id=incoming.id,
            # A note a tidy has since filed under another record stays there.
            session_id=held.session_id if held is not None else target.id,
            cohort_id=target.cohort_id,
            at=incoming.at,
            created_at=incoming.created_at,
            edited_at=incoming.edited_at,
            deleted_at=None,
            tag=incoming.tag,
            scope_kind=incoming.scope_kind,
            animal_id=animal_id if incoming.scope_kind == "animal" else None,
            box_number=incoming.box if incoming.scope_kind == "box" else None,
            body=incoming.body,
            carry_forward=incoming.carry_forward,
            resolved_at=incoming.resolved_at if incoming.carry_forward else None,
            resolved_in_session=resolved_in.id if resolved_in and incoming.resolved_at else None,
        )
        try:
            check_note(note)
        except NoteInvalid as exc:
            log.warning("logbook: a note in %s's log file was left out: %s", target.folder_path, exc)
            return False
        self._repo.put(note, tx=tx)
        return True

    # --- operator and summary -----------------------------------------------

    def _fields(self, incoming: FileSession, target: Session, tx: Tx) -> bool:
        if incoming.log_updated_at is None:
            return False
        held = self._repo.get_log(target.id)
        if held is None:
            # Nothing here and nothing there is nothing to take.
            if not (incoming.operator or "").strip() and not (incoming.summary or "").strip():
                return False
        elif not logfile.newer(incoming.log_updated_at, held.updated_at):
            return False
        # A newer blank is taken too: a field cleared there is cleared here.
        self._repo.put_log(
            target.id, incoming.operator, incoming.summary, incoming.log_updated_at, tx=tx
        )
        return True

    # --- weigh-ins ----------------------------------------------------------

    def _weigh_in(
        self, incoming: logfile.FileWeighIn, animals: "_Animals", result: Intake, tx: Tx
    ) -> bool:
        if not _is_day(incoming.date):
            return False
        animal_id = animals.resolve(incoming.animal_id, incoming.animal)
        if animal_id is None:
            result.unknown_animals.add(incoming.animal or incoming.animal_id or "an unnamed animal")
            return False
        held = self._repo.find_health(animal_id, incoming.date)
        if incoming.removed_at:
            # A removal takes out a weigh-in it is newer than, and nothing else.
            if held is None or held.removed_at:
                return False
            if not logfile.newer(incoming.removed_at, held.recorded_at):
                return False
            self._repo.put_health(
                HealthEntry(
                    animal_id=animal_id,
                    date=incoming.date,
                    weight_g=held.weight_g,
                    baseline=False,
                    recorded_at=held.recorded_at,
                    removed_at=incoming.removed_at,
                ),
                tx=tx,
            )
            return True
        if not MIN_WEIGHT_G <= incoming.weight_g <= MAX_WEIGHT_G:
            return False
        if held is not None and not logfile.newer(
            incoming.recorded_at, held.removed_at or held.recorded_at
        ):
            return False
        self._repo.put_health(
            HealthEntry(
                animal_id=animal_id,
                date=incoming.date,
                weight_g=incoming.weight_g,
                baseline=incoming.baseline,
                recorded_at=incoming.recorded_at,
            ),
            tx=tx,
        )
        return True


class _Animals:
    """A cohort's animals by id and by name, former members included
    (`DATA.md#former-members`): the roster's name wins one both have."""

    def __init__(self, cohort: Any) -> None:
        self._ids: set[str] = set()
        self._by_name: dict[str, str] = {}
        for former in cohort.former_animals:
            self._ids.add(former.id)
            if former.name:
                self._by_name[former.name.strip().casefold()] = former.id
        for animal in cohort.animals:
            self._ids.add(animal.id)
            self._by_name[animal.name.strip().casefold()] = animal.id

    def known(self, animal_id: str) -> bool:
        return animal_id in self._ids

    def resolve(self, animal_id: str | None, name: str | None) -> str | None:
        """This machine's id for an animal a file names: by name first, since
        the id is the writing machine's, then the id itself when it is one of
        this cohort's own (a file this machine wrote, about an animal since
        renamed)."""
        if name:
            found = self._by_name.get(name.strip().casefold())
            if found is not None:
                return found
        if animal_id and animal_id in self._ids:
            return animal_id
        return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_day(value: str) -> bool:
    """A real calendar day written `YYYY-MM-DD`, as a session's `date` is."""
    try:
        return calendar_date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False
