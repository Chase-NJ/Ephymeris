"""Prefix and session persistence — `data.md` §3.1–§4.

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
from typing import Any

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


def _hydrate_run(row: sqlite3.Row) -> SessionAnimalRun:
    return SessionAnimalRun(
        id=row["id"],
        session_id=row["session_id"],
        animal_id=row["animal_id"],
        box_number=row["box_number"],
        sketch_path=row["sketch_path"],
        file_path=row["file_path"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        stop_reason=row["stop_reason"],
        profile_hash=row["profile_hash"],
        config=_load_config(row["config_json"]),
        params_hash=row["params_hash"],
    )


def _load_config(raw: str | None) -> dict[str, Any] | None:
    """Decode a run's stored task parameters (§6.9).

    A row written before v6, or by a build that stored something unreadable,
    reads back as `None` rather than raising: this is a record of what a run
    used, and a corrupt one must not take the run's whole history with it.
    """
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        log.warning("run has unreadable config_json; treating it as absent")
        return None
    return value if isinstance(value, dict) else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid.uuid4())


def _id_chunks(ids: list[str], size: int = 400) -> list[list[str]]:
    """Bounded `IN (...)` batches — SQLite's variable limit is 999 on older
    builds, and a real archive's cohort has thousands of runs."""
    return [ids[i : i + size] for i in range(0, len(ids), size)]


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
        (`data.md` §1) — appending to an existing folder is a supported
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
        duration_minutes: int | None = None,
        recording: bool = False,
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
            duration_minutes=duration_minutes,
            recording={"runs": []} if recording else None,
        )
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO sessions"
                " (id, cohort_id, prefix_id, prefix_name, session_number, date,"
                "  started_at, ended_at, status, folder_path, group_runs,"
                "  duration_minutes, recording_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    session.duration_minutes,
                    json.dumps(session.recording) if session.recording is not None else None,
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

    def set_recording(self, session_id: str, recording: dict[str, Any]) -> Session:
        with self._db.lock:
            self._db.conn.execute(
                "UPDATE sessions SET recording_json = ? WHERE id = ?",
                (json.dumps(recording), session_id),
            )
            self._db.conn.commit()
        return self.get_session(session_id)

    # --- animal runs (written at finalization) ----------------------------

    def record_animal_run(self, run: SessionAnimalRun) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT OR REPLACE INTO session_animal_runs"
                " (id, session_id, animal_id, box_number, sketch_path, file_path,"
                "  started_at, ended_at, stop_reason, profile_hash, config_json,"
                "  params_hash)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    run.profile_hash,
                    None if run.config is None else json.dumps(run.config, sort_keys=True),
                    run.params_hash,
                ),
            )
            self._db.conn.commit()

    # --- pruning (data.md §8.6) -------------------------------------------
    #
    # The only deletions in this repository, and they exist for one caller:
    # `analytics.rescan`'s reconciliation. A run record outlives its file
    # forever otherwise — nothing else in the app ever removes one — and
    # Analytics keeps serving that run's last good numbers, so a session the
    # operator deleted from disk goes on charting.
    #
    # This removes **bookkeeping only**, the same line the cohort delete draws
    # (`cohorts.md` §9): the app deletes its own records, never the user's data.
    # Here that is inverted and holds all the same — the data is already gone,
    # and the record is what's left over.

    def delete_runs(self, run_ids: list[str]) -> int:
        if not run_ids:
            return 0
        removed = 0
        with self._db.lock:
            for chunk in _id_chunks(run_ids):
                marks = ",".join("?" * len(chunk))
                cursor = self._db.conn.execute(
                    f"DELETE FROM session_animal_runs WHERE id IN ({marks})",
                    tuple(chunk),
                )
                removed += cursor.rowcount
            self._db.conn.commit()
        return removed

    def delete_sessions(self, session_ids: list[str]) -> int:
        """Drop session rows. The caller decides which; this only enforces the
        one rule no caller may override — **a session that is still open is
        never deleted.** `configuring` and `running` describe a session the
        runner is holding right now, whose folder legitimately may not exist
        yet, and whose disappearance mid-flow would strand it."""
        if not session_ids:
            return 0
        removed = 0
        with self._db.lock:
            for chunk in _id_chunks(session_ids):
                marks = ",".join("?" * len(chunk))
                cursor = self._db.conn.execute(
                    f"DELETE FROM sessions WHERE id IN ({marks})"
                    " AND status NOT IN ('configuring', 'running')",
                    tuple(chunk),
                )
                removed += cursor.rowcount
            self._db.conn.commit()
        return removed

    def runs_for(self, session_id: str) -> list[SessionAnimalRun]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM session_animal_runs WHERE session_id = ? ORDER BY started_at",
                (session_id,),
            ).fetchall()
        return [_hydrate_run(r) for r in rows]

    def runs_for_cohort(self, cohort_id: str) -> list[SessionAnimalRun]:
        """Every run across every session of one cohort (`websocket-protocol.md` §3.4).

        One join rather than a query per session: the whole cohort table is a
        single `analytics.summary` payload, and per-session calls would mean a
        round trip per session.
        """
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT r.* FROM session_animal_runs r"
                " JOIN sessions s ON s.id = r.session_id"
                " WHERE s.cohort_id = ?"
                " ORDER BY s.date, s.started_at, r.started_at",
                (cohort_id,),
            ).fetchall()
        return [_hydrate_run(r) for r in rows]

    # --- listing (websocket-protocol.md §3.4) ----------------------------------------

    def list_sessions(
        self, cohort_id: str, *, include_aborted: bool = False
    ) -> list[Session]:
        """A cohort's sessions, oldest first. **Never touches the filesystem.**

        Ordering is `(date, started_at)` — never `session_number`, which is
        free text (§10) and would sort "10" before "9".

        Aborted sessions are excluded by default: one never wrote data, so
        including it produces an empty session that reads as one where every
        animal failed.
        """
        clause = "" if include_aborted else " AND status != 'aborted'"
        with self._db.lock:
            rows = self._db.conn.execute(
                f"SELECT * FROM sessions WHERE cohort_id = ?{clause}"
                " ORDER BY date, started_at",
                (cohort_id,),
            ).fetchall()
        return [self._hydrate(row) for row in rows]

    def list_unfinished(self) -> list[Session]:
        """Every session still open — `configuring` or `running` — across all
        cohorts, oldest first. Feeds `sessions.active`; deliberately global,
        unlike `list_sessions`, because the caller by definition doesn't know
        a cohort id yet.
        """
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT * FROM sessions WHERE status IN ('configuring', 'running')"
                " ORDER BY date, started_at"
            ).fetchall()
        return [self._hydrate(row) for row in rows]

    def run_counts_by_session(self, cohort_id: str) -> dict[str, int]:
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT r.session_id AS sid, COUNT(*) AS n FROM session_animal_runs r"
                " JOIN sessions s ON s.id = r.session_id"
                " WHERE s.cohort_id = ? GROUP BY r.session_id",
                (cohort_id,),
            ).fetchall()
        return {row["sid"]: row["n"] for row in rows}

    # --- tidying (data.md §8.8) --------------------------------------------
    #
    # Both methods trust their caller about WHICH records: `sessions/tidy.py`
    # plans, and the analytics service excludes the session the runner holds.
    # What they guarantee is that each change lands whole — a merge that moved
    # the runs but left the absorbed row behind would count the day twice in a
    # different way.

    def absorb_sessions(
        self,
        keep_id: str,
        absorb_ids: list[str],
        *,
        group_runs: list[GroupRun],
        recording: dict[str, Any] | None,
        started_at: str,
        ended_at: str | None,
        status: SessionStatus,
    ) -> Session:
        """Fold `absorb_ids` into `keep_id` in one transaction.

        Their runs are re-parented, not copied: a run id is the analytics
        cache's key, so the cached summaries follow the run to its new session
        untouched. Only the database changes — the files never knew which
        session row owned them.
        """
        with self._db.lock:
            conn = self._db.conn
            try:
                for chunk in _id_chunks(absorb_ids):
                    marks = ",".join("?" * len(chunk))
                    conn.execute(
                        f"UPDATE session_animal_runs SET session_id = ?"
                        f" WHERE session_id IN ({marks})",
                        (keep_id, *chunk),
                    )
                    conn.execute(f"DELETE FROM sessions WHERE id IN ({marks})", tuple(chunk))
                conn.execute(
                    "UPDATE sessions SET group_runs = ?, recording_json = ?,"
                    " started_at = ?, ended_at = ?, status = ? WHERE id = ?",
                    (
                        json.dumps([r.to_json() for r in group_runs]),
                        json.dumps(recording) if recording is not None else None,
                        started_at,
                        ended_at,
                        status,
                        keep_id,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_session(keep_id)

    def discard_sessions(self, session_ids: list[str]) -> int:
        """Delete records the tidy found empty — whatever their status.

        Unlike `delete_sessions` this does not refuse an open status: a
        `running` row nobody holds is a crash orphan, and a `configuring` one
        from an earlier day an abandoned set-up, and both are exactly what a
        tidy clears. Refusing the one open session that matters — the one the
        runner holds — is the caller's, which is the only place that knows it.
        """
        if not session_ids:
            return 0
        removed = 0
        with self._db.lock:
            for chunk in _id_chunks(session_ids):
                marks = ",".join("?" * len(chunk))
                cursor = self._db.conn.execute(
                    f"DELETE FROM sessions WHERE id IN ({marks})", tuple(chunk)
                )
                removed += cursor.rowcount
            self._db.conn.commit()
        return removed

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
            duration_minutes=row["duration_minutes"],
            recording=json.loads(row["recording_json"]) if row["recording_json"] else None,
        )
