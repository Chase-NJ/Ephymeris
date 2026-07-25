"""Prefix and session persistence — `data-saving.md` §3–§4.

Synchronous; callers wrap in `asyncio.to_thread`. Shares the cohort database
and its lock, so a session write is atomic against a concurrent cohort edit.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from ..cohorts.db import Database
from .models import (
    GroupRun,
    Prefix,
    PrefixNameTaken,
    Session,
    SessionAnimalRun,
    SessionNotFound,
    SessionStatus,
)

log = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid.uuid4())


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # --- prefixes ---------------------------------------------------------

    def list_prefixes(self) -> list[Prefix]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM prefixes ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [Prefix(id=r["id"], name=r["name"]) for r in rows]

    def create_prefix(self, name: str) -> Prefix:
        clean = (name or "").strip()
        if not clean:
            raise PrefixNameTaken("A prefix needs a name.")
        prefix = Prefix(id=_new_id(), name=clean)
        with self._db.lock:
            try:
                self._db.conn.execute(
                    "INSERT INTO prefixes (id, name) VALUES (?, ?)",
                    (prefix.id, prefix.name),
                )
                self._db.conn.commit()
            except sqlite3.IntegrityError as exc:
                self._db.conn.rollback()
                raise PrefixNameTaken(clean) from exc
        return prefix

    def delete_prefix(self, prefix_id: str) -> None:
        """Non-destructive on disk — only removes the dropdown entry (§3)."""
        with self._db.lock:
            self._db.conn.execute("DELETE FROM prefixes WHERE id = ?", (prefix_id,))
            self._db.conn.commit()

    def get_prefix(self, prefix_id: str) -> Prefix | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM prefixes WHERE id = ?", (prefix_id,)
            ).fetchone()
        return None if row is None else Prefix(id=row["id"], name=row["name"])

    def suggest_session_number(self, prefix_id: str) -> str | None:
        """Highest existing numeric session number for this prefix, +1 (§2.2).

        Degrades to `None` for a prefix with no numeric history yet — the UI
        shows no suggestion rather than a wrong one. Session numbers are free
        text (§10), so non-numeric values are simply ignored here. Aborted
        sessions never wrote data, so they don't claim their number.
        """
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT session_number FROM sessions"
                " WHERE prefix_id = ? AND status != 'aborted'",
                (prefix_id,),
            ).fetchall()
        highest: int | None = None
        for row in rows:
            match = re.fullmatch(r"\d+", str(row["session_number"]).strip())
            if match:
                value = int(match.group())
                highest = value if highest is None else max(highest, value)
        return None if highest is None else str(highest + 1)

    def session_numbers_on(self, prefix_id: str, date: str) -> list[str]:
        """Session numbers already used for this prefix on `date` (§2.2).

        Feeds the *soft* same-day warning only. Reusing a number is legal
        (`data-saving.md` §1) — appending to an existing folder is a supported
        way to resume an interrupted run — so this never blocks. Aborted
        sessions are excluded: they wrote nothing, so there is no folder the
        warning could truthfully be about.
        """
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT session_number FROM sessions"
                " WHERE prefix_id = ? AND date = ? AND status != 'aborted'",
                (prefix_id, date),
            ).fetchall()
        return [str(row["session_number"]) for row in rows]

    # --- sessions ---------------------------------------------------------

    def create_session(
        self,
        cohort_id: str,
        prefix: Prefix,
        session_number: str,
        date: str,
        folder_path: str,
    ) -> Session:
        session = Session(
            id=_new_id(),
            cohort_id=cohort_id,
            prefix_id=prefix.id,
            prefix_name=prefix.name,
            session_number=session_number.strip(),
            date=date,
            started_at=_now(),
            status="configuring",
            folder_path=folder_path,
        )
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO sessions"
                " (id, cohort_id, prefix_id, prefix_name, session_number, date,"
                "  started_at, ended_at, status, folder_path, group_runs)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.cohort_id,
                    session.prefix_id,
                    session.prefix_name,
                    session.session_number,
                    session.date,
                    session.started_at,
                    None,
                    session.status,
                    session.folder_path,
                    "[]",
                ),
            )
            self._db.conn.commit()
        return session

    def get_session(self, session_id: str) -> Session:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return self._hydrate(row)

    def set_status(self, session_id: str, status: SessionStatus) -> Session:
        ended = _now() if status in ("completed", "aborted") else None
        with self._db.lock:
            self._db.conn.execute(
                "UPDATE sessions SET status = ?,"
                " ended_at = COALESCE(?, ended_at) WHERE id = ?",
                (status, ended, session_id),
            )
            self._db.conn.commit()
        return self.get_session(session_id)

    def set_group_runs(self, session_id: str, runs: list[GroupRun]) -> Session:
        with self._db.lock:
            self._db.conn.execute(
                "UPDATE sessions SET group_runs = ? WHERE id = ?",
                (json.dumps([r.to_json() for r in runs]), session_id),
            )
            self._db.conn.commit()
        return self.get_session(session_id)

    # --- animal runs (written at finalization) ----------------------------

    def record_animal_run(self, run: SessionAnimalRun) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT OR REPLACE INTO session_animal_runs"
                " (id, session_id, animal_id, box_number, sketch_path, file_path,"
                "  started_at, ended_at, stop_reason)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.session_id,
                    run.animal_id,
                    run.box_number,
                    run.sketch_path,
                    run.file_path,
                    run.started_at,
                    run.ended_at,
                    run.stop_reason,
                ),
            )
            self._db.conn.commit()

    def runs_for(self, session_id: str) -> list[SessionAnimalRun]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM session_animal_runs WHERE session_id = ? ORDER BY started_at",
                (session_id,),
            ).fetchall()
        return [
            SessionAnimalRun(
                id=r["id"],
                session_id=r["session_id"],
                animal_id=r["animal_id"],
                box_number=r["box_number"],
                sketch_path=r["sketch_path"],
                file_path=r["file_path"],
                started_at=r["started_at"],
                ended_at=r["ended_at"],
                stop_reason=r["stop_reason"],
            )
            for r in rows
        ]

    # --- internals --------------------------------------------------------

    @staticmethod
    def _hydrate(row: sqlite3.Row) -> Session:
        raw_runs = json.loads(row["group_runs"] or "[]")
        return Session(
            id=row["id"],
            cohort_id=row["cohort_id"],
            prefix_id=row["prefix_id"],
            prefix_name=row["prefix_name"],
            session_number=row["session_number"],
            date=row["date"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            status=row["status"],
            folder_path=row["folder_path"],
            group_runs=[GroupRun.from_json(r) for r in raw_runs],
        )
