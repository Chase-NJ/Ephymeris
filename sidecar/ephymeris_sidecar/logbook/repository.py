"""Session-log persistence — `DATA.md#the-session-log`.

Synchronous; callers wrap in `asyncio.to_thread`. Shares the cohort database
and its lock, like `SessionRepository`. Validation that needs the cohort (is
this animal in it?) is the service's; this module checks only what the row
itself can say.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from ..cohorts.db import Database
from .models import (
    MAX_BODY,
    MAX_FIELD,
    NOTE_TAGS,
    SCOPE_KINDS,
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

    def add(self, note: SessionNote) -> SessionNote:
        check_note(note)
        with self._db.lock:
            self._db.conn.execute(
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
            self._db.conn.commit()
        return self.get(note.id)

    def get(self, note_id: str, *, include_deleted: bool = False) -> SessionNote:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM session_notes WHERE id = ?", (note_id,)
            ).fetchone()
        if row is None or (row["deleted_at"] and not include_deleted):
            raise NoteNotFound(note_id)
        return _hydrate(row)

    def save(self, note: SessionNote) -> SessionNote:
        """Write an edited note back, stamping `edited_at`."""
        check_note(note)
        with self._db.lock:
            self._db.conn.execute(
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
            self._db.conn.commit()
        return self.get(note.id)

    def soft_delete(self, note_id: str) -> SessionNote:
        note = self.get(note_id)
        with self._db.lock:
            self._db.conn.execute(
                "UPDATE session_notes SET deleted_at = ? WHERE id = ?", (now_iso(), note_id)
            )
            self._db.conn.commit()
        return note

    def set_resolved(self, note_id: str, resolved: bool, session_id: str | None) -> SessionNote:
        note = self.get(note_id)
        if not note.carry_forward:
            raise NoteInvalid("Only a carry-forward note can be resolved.")
        with self._db.lock:
            self._db.conn.execute(
                "UPDATE session_notes SET resolved_at = ?, resolved_in_session = ? WHERE id = ?",
                (now_iso() if resolved else None, session_id if resolved else None, note_id),
            )
            self._db.conn.commit()
        return self.get(note_id)

    def notes_for_cohort(self, cohort_id: str) -> list[SessionNote]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM session_notes WHERE cohort_id = ? AND deleted_at IS NULL"
                " ORDER BY at, created_at",
                (cohort_id,),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    def notes_for_sessions(self, session_ids: list[str]) -> list[SessionNote]:
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT * FROM session_notes WHERE session_id IN ({marks})"
                " AND deleted_at IS NULL ORDER BY at, created_at",
                tuple(session_ids),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    def open_flags(self, cohort_id: str) -> list[SessionNote]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM session_notes WHERE cohort_id = ? AND carry_forward = 1"
                " AND resolved_at IS NULL AND deleted_at IS NULL ORDER BY at, created_at",
                (cohort_id,),
            ).fetchall()
        return [_hydrate(r) for r in rows]

    # --- session fields ---------------------------------------------------

    def get_log(self, session_id: str) -> SessionLog | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM session_logs WHERE session_id = ?", (session_id,)
            ).fetchone()
        return None if row is None else _hydrate_log(row)

    def logs_for_cohort(self, cohort_id: str) -> list[SessionLog]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT l.* FROM session_logs l JOIN sessions s ON s.id = l.session_id"
                " WHERE s.cohort_id = ?",
                (cohort_id,),
            ).fetchall()
        return [_hydrate_log(r) for r in rows]

    def logs_for_sessions(self, session_ids: list[str]) -> list[SessionLog]:
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT * FROM session_logs WHERE session_id IN ({marks})",
                tuple(session_ids),
            ).fetchall()
        by_id = {row["session_id"]: _hydrate_log(row) for row in rows}
        return [by_id[sid] for sid in session_ids if sid in by_id]

    def upsert_log(self, session_id: str, fields: dict[str, Any]) -> SessionLog:
        """Set `operator` and/or `summary`; a key absent from `fields` is kept."""
        current = self.get_log(session_id) or SessionLog(session_id=session_id)
        operator = fields.get("operator", current.operator)
        summary = fields.get("summary", current.summary)
        for name, value in (("operator", operator), ("summary", summary)):
            if value is not None and len(value) > MAX_FIELD * (5 if name == "summary" else 1):
                raise NoteInvalid(f"The {name} is too long.")
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO session_logs (session_id, operator, summary, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(session_id) DO UPDATE SET operator = excluded.operator,"
                " summary = excluded.summary, updated_at = excluded.updated_at",
                (session_id, _blank_to_none(operator), _blank_to_none(summary), now_iso()),
            )
            self._db.conn.commit()
        return self.get_log(session_id) or SessionLog(session_id=session_id)

    # --- what tidy and prune must keep (DATA.md#tidy-records) ---------------

    def annotated_session_ids(self, cohort_id: str) -> set[str]:
        """Sessions carrying anything the operator wrote — a live note or a
        non-blank log field. Those are user data, never an empty record."""
        with self._db.lock:
            noted = self._db.conn.execute(
                "SELECT DISTINCT session_id FROM session_notes"
                " WHERE cohort_id = ? AND deleted_at IS NULL",
                (cohort_id,),
            ).fetchall()
            logged = self._db.conn.execute(
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


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def new_note_id() -> str:
    return str(uuid.uuid4())
