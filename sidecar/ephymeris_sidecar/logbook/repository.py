"""Session-log persistence — `DATA.md#the-session-log`.

Synchronous; callers wrap in `asyncio.to_thread`. Shares the cohort database
and its units of work, like `SessionRepository` (`DATA.md#transactions`). Validation that needs the cohort (is
this animal in it?) is the service's; this module checks only what the row
itself can say.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ..cohorts.db import Database, Tx
from .models import (
    MAX_BODY,
    MAX_FIELD,
    NOTE_TAGS,
    SCOPE_KINDS,
    HealthEntry,
    NoteInvalid,
    NoteNotFound,
    SessionLog,
    SessionNote,
)


def now_iso() -> str:
    """UTC with milliseconds: two notes taken in one second still order."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _hydrate(row: sqlite3.Row) -> SessionNote:
    return SessionNote(
        id=row["id"],
        session_id=row["session_id"],
        cohort_id=row["cohort_id"],
        at=row["at"],
        created_at=row["created_at"],
        edited_at=row["edited_at"],
        deleted_at=row["deleted_at"],
        tag=row["tag"],
        scope_kind=row["scope_kind"],
        animal_id=row["animal_id"],
        box_number=row["box_number"],
        body=row["body"],
        carry_forward=bool(row["carry_forward"]),
        resolved_at=row["resolved_at"],
        resolved_in_session=row["resolved_in_session"],
    )


def check_note(note: SessionNote) -> None:
    """Refuse a note the log could not render honestly."""
    if note.tag not in NOTE_TAGS:
        raise NoteInvalid(f"Unknown tag “{note.tag}”.")
    if note.scope_kind not in SCOPE_KINDS:
        raise NoteInvalid(f"Unknown scope “{note.scope_kind}”.")
    if note.scope_kind == "animal" and not note.animal_id:
        raise NoteInvalid("An animal note needs an animal.")
    if note.scope_kind == "box" and not (
        isinstance(note.box_number, int) and 1 <= note.box_number <= 6
    ):
        raise NoteInvalid("A box note needs a box number 1–6.")
    if not note.body.strip():
        raise NoteInvalid("A note needs some text.")
    if len(note.body) > MAX_BODY:
        raise NoteInvalid(f"A note is limited to {MAX_BODY:,} characters.")


class LogbookRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- notes ------------------------------------------------------------

    def add(self, note: SessionNote, *, tx: Tx | None = None) -> SessionNote:
        check_note(note)
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT INTO session_notes"
                " (id, session_id, cohort_id, at, created_at, edited_at, deleted_at,"
                "  tag, scope_kind, animal_id, box_number, body, carry_forward,"
                "  resolved_at, resolved_in_session)"
                " VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, ?, NULL, NULL)",
                (
                    note.id,
                    note.session_id,
                    note.cohort_id,
                    note.at,
                    note.created_at,
                    note.tag,
                    note.scope_kind,
                    note.animal_id,
                    note.box_number,
                    note.body,
                    int(note.carry_forward),
                ),
            )
        return self.get(note.id)

    def get(self, note_id: str, *, include_deleted: bool = False) -> SessionNote:
        with self._db.read() as q:
            row = q.execute(
                "SELECT * FROM session_notes WHERE id = ?", (note_id,)
            ).fetchone()
        if row is None or (row["deleted_at"] and not include_deleted):
            raise NoteNotFound(note_id)
        return _hydrate(row)

    def save(self, note: SessionNote, *, tx: Tx | None = None) -> SessionNote:
        """Write an edited note back, stamping `edited_at`."""
        check_note(note)
        with self._db.write(tx) as unit:
            unit.execute(
                "UPDATE session_notes SET at = ?, edited_at = ?, tag = ?, scope_kind = ?,"
                " animal_id = ?, box_number = ?, body = ?, carry_forward = ?"
                " WHERE id = ? AND deleted_at IS NULL",
                (
                    note.at,
                    now_iso(),
                    note.tag,
                    note.scope_kind,
                    note.animal_id,
                    note.box_number,
                    note.body,
                    int(note.carry_forward),
                    note.id,
                ),
            )
        return self.get(note.id)

    def soft_delete(self, note_id: str, *, tx: Tx | None = None) -> SessionNote:
        note = self.get(note_id)
        with self._db.write(tx) as unit:
            unit.execute(
                "UPDATE session_notes SET deleted_at = ? WHERE id = ?", (now_iso(), note_id)
            )
        return note

    def set_resolved(
        self, note_id: str, resolved: bool, session_id: str | None, *, tx: Tx | None = None
    ) -> SessionNote:
        note = self.get(note_id)
        if not note.carry_forward:
            raise NoteInvalid("Only a carry-forward note can be resolved.")
        with self._db.write(tx) as unit:
            unit.execute(
                "UPDATE session_notes SET resolved_at = ?, resolved_in_session = ? WHERE id = ?",
                (now_iso() if resolved else None, session_id if resolved else None, note_id),
            )
        return self.get(note_id)

    def notes_for_cohort(self, cohort_id: str) -> list[SessionNote]:
        with self._db.read() as q:
            rows = q.execute(
                "SELECT * FROM session_notes WHERE cohort_id = ? AND deleted_at IS NULL"
                " ORDER BY at, created_at",
                (cohort_id,),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    def notes_for_sessions(self, session_ids: list[str]) -> list[SessionNote]:
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        with self._db.read() as q:
            rows = q.execute(
                f"SELECT * FROM session_notes WHERE session_id IN ({marks})"
                " AND deleted_at IS NULL ORDER BY at, created_at",
                tuple(session_ids),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    def every_note_for_sessions(self, session_ids: list[str]) -> list[SessionNote]:
        """These sessions' notes **with the deleted ones**, for the folder's
        log file, which carries a deletion as a tombstone (`DATA.md#the-log-file`)."""
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        with self._db.read() as q:
            rows = q.execute(
                f"SELECT * FROM session_notes WHERE session_id IN ({marks})"
                " ORDER BY at, created_at, id",
                tuple(session_ids),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    def find(self, note_id: str) -> SessionNote | None:
        """A note by id, deleted or not; None when this database has none."""
        with self._db.read() as q:
            row = q.execute("SELECT * FROM session_notes WHERE id = ?", (note_id,)).fetchone()
        return None if row is None else _hydrate(row)

    def put(self, note: SessionNote, *, tx: Tx | None = None) -> None:
        """Write a note exactly as given, every stamp included: a note read
        from another machine's log file (`logbook/intake.py`). Never for a note
        written here, whose stamps `add` and `save` set."""
        check_note(note)
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT OR REPLACE INTO session_notes"
                " (id, session_id, cohort_id, at, created_at, edited_at, deleted_at,"
                "  tag, scope_kind, animal_id, box_number, body, carry_forward,"
                "  resolved_at, resolved_in_session)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    note.id,
                    note.session_id,
                    note.cohort_id,
                    note.at,
                    note.created_at,
                    note.edited_at,
                    note.deleted_at,
                    note.tag,
                    note.scope_kind,
                    note.animal_id,
                    note.box_number,
                    note.body,
                    int(note.carry_forward),
                    note.resolved_at,
                    note.resolved_in_session,
                ),
            )

    def mark_deleted(self, note_id: str, deleted_at: str, *, tx: Tx | None = None) -> None:
        """Hide a note as of a moment another machine recorded."""
        with self._db.write(tx) as unit:
            unit.execute(
                "UPDATE session_notes SET deleted_at = ? WHERE id = ?", (deleted_at, note_id)
            )

    def set_animal(self, note_id: str, animal_id: str, *, tx: Tx | None = None) -> None:
        """Re-point a note at this machine's id for the animal it names. Not
        an edit: the words and every stamp stay as they were."""
        with self._db.write(tx) as unit:
            unit.execute(
                "UPDATE session_notes SET animal_id = ? WHERE id = ?", (animal_id, note_id)
            )

    def open_flags(self, cohort_id: str) -> list[SessionNote]:
        with self._db.read() as q:
            rows = q.execute(
                "SELECT * FROM session_notes WHERE cohort_id = ? AND carry_forward = 1"
                " AND resolved_at IS NULL AND deleted_at IS NULL ORDER BY at, created_at",
                (cohort_id,),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    # --- session fields ---------------------------------------------------

    def get_log(self, session_id: str) -> SessionLog | None:
        with self._db.read() as q:
            row = q.execute(
                "SELECT * FROM session_logs WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else _hydrate_log(row)

    def logs_for_cohort(self, cohort_id: str) -> list[SessionLog]:
        with self._db.read() as q:
            rows = q.execute(
                "SELECT l.* FROM session_logs l JOIN sessions s ON s.id = l.session_id"
                " WHERE s.cohort_id = ?",
                (cohort_id,),
            ).fetchall()
        return [_hydrate_log(r) for r in rows]

    def logs_for_sessions(self, session_ids: list[str]) -> list[SessionLog]:
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        with self._db.read() as q:
            rows = q.execute(
                f"SELECT * FROM session_logs WHERE session_id IN ({marks})",
                tuple(session_ids),
            ).fetchall()
        by_id = {row["session_id"]: _hydrate_log(row) for row in rows}
        return [by_id[sid] for sid in session_ids if sid in by_id]

    def upsert_log(
        self, session_id: str, fields: dict[str, Any], *, tx: Tx | None = None
    ) -> SessionLog:
        """Set `operator` and/or `summary`; a key absent from `fields` is kept."""
        current = self.get_log(session_id) or SessionLog(session_id=session_id)
        operator = fields.get("operator", current.operator)
        summary = fields.get("summary", current.summary)
        for name, value in (("operator", operator), ("summary", summary)):
            if value is not None and len(value) > MAX_FIELD * (5 if name == "summary" else 1):
                raise NoteInvalid(f"The {name} is too long.")
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT INTO session_logs (session_id, operator, summary, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET operator = excluded.operator,"
                " summary = excluded.summary, updated_at = excluded.updated_at",
                (session_id, _blank_to_none(operator), _blank_to_none(summary), now_iso()),
            )
        return self.get_log(session_id) or SessionLog(session_id=session_id)

    # --- weigh-ins (DATA.md#weigh-ins) --------------------------------------

    def get_health(self, animal_id: str, date: str) -> HealthEntry | None:
        """The day's weigh-in, or None when there is none or it was removed."""
        entry = self.find_health(animal_id, date)
        return None if entry is None or entry.removed_at else entry

    def find_health(self, animal_id: str, date: str) -> HealthEntry | None:
        """The day's row, removed or not."""
        with self._db.read() as q:
            row = q.execute(
                "SELECT * FROM animal_health WHERE animal_id = ? AND date = ?", (animal_id, date)
            ).fetchone()
        return None if row is None else _hydrate_health(row)

    def set_health(
        self,
        animal_id: str,
        date: str,
        weight_g: float,
        baseline: bool | None = None,
        *,
        tx: Tx | None = None,
    ) -> HealthEntry:
        """Write the day's weigh-in. `baseline` None keeps the mark a row
        already has; a new row, or one written over a removed one, starts
        unmarked."""
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT INTO animal_health (animal_id, date, weight_g, baseline, recorded_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(animal_id, date) DO UPDATE SET weight_g = excluded.weight_g,"
                " baseline = CASE WHEN animal_health.removed_at IS NOT NULL THEN excluded.baseline"
                "            ELSE COALESCE(?, animal_health.baseline) END,"
                " recorded_at = excluded.recorded_at, removed_at = NULL",
                (
                    animal_id,
                    date,
                    weight_g,
                    int(bool(baseline)),
                    now_iso(),
                    None if baseline is None else int(baseline),
                ),
            )
        entry = self.get_health(animal_id, date)
        assert entry is not None
        return entry

    def delete_health(self, animal_id: str, date: str, *, tx: Tx | None = None) -> bool:
        """Remove the day's weigh-in, its baseline mark with it. The row
        stays, marked: a removal has to outlast the copies of it that other
        machines and older log files still hold."""
        with self._db.write(tx) as unit:
            cursor = unit.execute(
                "UPDATE animal_health SET removed_at = ?, baseline = 0"
                " WHERE animal_id = ? AND date = ? AND removed_at IS NULL",
                (now_iso(), animal_id, date),
            )
        return cursor.rowcount > 0

    def health_for_animals(
        self,
        animal_ids: list[str],
        dates: list[str] | None = None,
        *,
        removed: bool = False,
    ) -> list[HealthEntry]:
        """These animals' weigh-ins, oldest first; with `dates`, those days'
        only. `removed` adds the removed ones, for the log file alone."""
        if not animal_ids or dates == []:
            return []
        found: list[HealthEntry] = []
        with self._db.read() as q:
            for at in range(0, len(animal_ids), 500):
                chunk = animal_ids[at:at + 500]
                marks = ",".join("?" * len(chunk))
                rows = q.execute(
                    f"SELECT * FROM animal_health WHERE animal_id IN ({marks})", tuple(chunk)
                ).fetchall()
                found.extend(_hydrate_health(row) for row in rows)
        if not removed:
            found = [entry for entry in found if not entry.removed_at]
        if dates is not None:
            wanted = set(dates)
            found = [entry for entry in found if entry.date in wanted]
        return sorted(found, key=lambda entry: (entry.date, entry.animal_id))

    def put_log(
        self,
        session_id: str,
        operator: str | None,
        summary: str | None,
        updated_at: str,
        *,
        tx: Tx | None = None,
    ) -> None:
        """Write a session's fields with the stamp they were written under on
        another machine (`logbook/intake.py`); `upsert_log` stamps now."""
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT INTO session_logs (session_id, operator, summary, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET operator = excluded.operator,"
                " summary = excluded.summary, updated_at = excluded.updated_at",
                (session_id, _blank_to_none(operator), _blank_to_none(summary), updated_at),
            )

    def put_health(self, entry: HealthEntry, *, tx: Tx | None = None) -> None:
        """Write a weigh-in exactly as given, its stamp and baseline mark
        included: one read from another machine's log file."""
        with self._db.write(tx) as unit:
            unit.execute(
                "INSERT OR REPLACE INTO animal_health"
                " (animal_id, date, weight_g, baseline, recorded_at, removed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entry.animal_id,
                    entry.date,
                    entry.weight_g,
                    int(entry.baseline),
                    entry.recorded_at,
                    entry.removed_at,
                ),
            )

    # --- what tidy and prune must keep (DATA.md#tidy-records) ---------------

    def annotated_session_ids(self, cohort_id: str) -> set[str]:
        """Sessions carrying anything the operator wrote — a live note or a
        non-blank log field. Those are user data, never an empty record."""
        with self._db.read() as q:
            noted = q.execute(
                "SELECT DISTINCT session_id FROM session_notes"
                " WHERE cohort_id = ? AND deleted_at IS NULL",
                (cohort_id,),
            ).fetchall()
            logged = q.execute(
                "SELECT l.session_id FROM session_logs l JOIN sessions s ON s.id = l.session_id"
                " WHERE s.cohort_id = ? AND (TRIM(COALESCE(l.operator, '')) != ''"
                " OR TRIM(COALESCE(l.summary, '')) != '')",
                (cohort_id,),
            ).fetchall()
        return {row[0] for row in noted} | {row[0] for row in logged}


def _hydrate_log(row: sqlite3.Row) -> SessionLog:
    return SessionLog(
        session_id=row["session_id"],
        operator=row["operator"],
        summary=row["summary"],
        updated_at=row["updated_at"],
    )


def _hydrate_health(row: sqlite3.Row) -> HealthEntry:
    return HealthEntry(
        animal_id=row["animal_id"],
        date=row["date"],
        weight_g=row["weight_g"],
        baseline=bool(row["baseline"]),
        recorded_at=row["recorded_at"],
        removed_at=row["removed_at"],
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def new_note_id() -> str:
    return str(uuid.uuid4())
