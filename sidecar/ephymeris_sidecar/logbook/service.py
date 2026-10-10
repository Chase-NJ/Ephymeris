"""The session log — `DATA.md#the-session-log`.

Owns the `logbook.*` commands' logic: validating a note against its session
and cohort, deriving each note's T+ offset (`DATA.md#the-session-clock`) on
every read, assembling a cohort's log with its "what changed" entries
(`DATA.md#what-changed`), announcing changes, and keeping each session
folder's `notes.md` mirror current (`DATA.md#the-notesmd-mirror`).

The mirror is fire-and-forget after the database commit: a command reply never
waits on disk, and nothing here is ever called from the runner, so a slow or
unreachable data folder costs only a stale `notes.md`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..analytics import service as analytics_service
from ..protocol import Evt, event
from ..sessions.models import Session, SessionNotFound
from . import diff, mirror
from .models import (
    NoteInvalid,
    SessionLog,
    SessionNote,
    offset_ms,
    parse_iso,
)
from .repository import LogbookRepository, check_note, new_note_id, now_iso

log = logging.getLogger(__name__)

#: Long enough that typing a burst of notes rewrites `notes.md` once.
MIRROR_DEBOUNCE_S = 1.0


class LogbookService:
    def __init__(
        self,
        *,
        db: Any,
        cohorts: Any,
        sessions: Any,
        profiles: Any,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        enqueue_backup: Callable[[Path], None] | None = None,
    ) -> None:
        self.repo = LogbookRepository(db)
        self._cohorts = cohorts
        self._sessions = sessions
        self._profiles = profiles
        self._broadcast = broadcast
        self._enqueue_backup = enqueue_backup
        self._pending: dict[str, asyncio.TimerHandle] = {}
        self._writes: set[asyncio.Task[None]] = set()
        # One lock per session folder, held across render and replace. Folder-mates
        # debounce separately, so two writes of one notes.md can overlap: Windows
        # refuses the second replace outright, and on any OS the earlier render
        # could land last.
        self._folder_locks: dict[str, threading.Lock] = {}
        self._folder_locks_guard = threading.Lock()

    # --- reads ------------------------------------------------------------

    async def cohort(self, cohort_id: str) -> dict[str, Any]:
        """`LogbookCohort` — database only, like `sessions.list`."""
        return await asyncio.to_thread(self._cohort, cohort_id)

    def _cohort(self, cohort_id: str) -> dict[str, Any]:
        self._cohorts.get(cohort_id)  # CohortNotFound for an unknown id
        sessions = {
            s.id: s for s in self._sessions.list_sessions(cohort_id, include_aborted=True)
        }
        notes = self.repo.notes_for_cohort(cohort_id)
        now = datetime.now(timezone.utc)
        return {
            "cohortId": cohort_id,
            "logs": [entry.to_json() for entry in self.repo.logs_for_cohort(cohort_id)],
            "notes": [self._note_json(n, sessions.get(n.session_id), now) for n in notes],
            "changes": list(self._changes(cohort_id).values()),
        }

    async def open_flags(self, cohort_id: str) -> dict[str, Any]:
        def read() -> dict[str, Any]:
            self._cohorts.get(cohort_id)
            sessions = {
                s.id: s
                for s in self._sessions.list_sessions(cohort_id, include_aborted=True)
            }
            now = datetime.now(timezone.utc)
            return {
                "notes": [
                    self._note_json(n, sessions.get(n.session_id), now)
                    for n in self.repo.open_flags(cohort_id)
                ]
            }

        return await asyncio.to_thread(read)

    def _changes(self, cohort_id: str) -> dict[str, dict[str, Any]]:
        """What changed for every run, recorded and recovered, in one
        chronological history per animal (`DATA.md#what-changed`). Database
        only: a recovered run's task and parameters come from the analytics
        cache, filled the first time the index read its file."""
        sessions = {
            s.id: s for s in self._sessions.list_sessions(cohort_id, include_aborted=True)
        }
        recorded = self._sessions.runs_for_cohort(cohort_id)
        entries = self._profiles.adopted_for_cohort(cohort_id)
        adopted = analytics_service.adopted_runs(
            entries, [s for s in sessions.values() if s.status != "aborted"]
        )
        cached = self._profiles.load_cached([run.id for run in adopted])
        hashes = sorted(
            {r.profile_hash for r in recorded if r.profile_hash}
            | {c.profile_hash for c in cached.values() if c.profile_hash}
        )
        names = {
            digest: meta["taskName"]
            for digest, meta in self._profiles.profile_meta(hashes).items()
        }

        # Set aside before comparing, not after (`DATA.md#false-starts`): the
        # run after a false start must be compared with the animal's previous
        # SESSION, and dropping the false start's row afterwards would lose
        # that change rather than recover it.
        verdicts = analytics_service.false_start_verdicts(self._profiles, recorded + adopted)

        timeline: list[tuple[tuple[str, str], diff.ComparedRun]] = []
        for run in recorded:
            session = sessions.get(run.session_id)
            day = session.date if session else ""
            timeline.append(((day, run.started_at), diff.from_recorded(run, names)))
        for run, entry in zip(adopted, entries, strict=True):
            cache = cached.get(run.id)
            digest = cache.profile_hash if cache else None
            sketch = getattr(run, "sketch_name", None) or diff.task_label(run, {})
            timeline.append(
                (
                    (entry.date or "", run.started_at),
                    diff.ComparedRun(
                        id=run.id,
                        session_id=run.session_id,
                        animal_id=run.animal_id,
                        box=None,
                        task_identity=f"hash:{digest}" if digest else f"name:{sketch}",
                        task=names.get(digest, sketch) if digest else sketch,
                        config=cache.config if cache else None,
                        params_hash=cache.params_hash if cache else None,
                        recovered=True,
                    ),
                )
            )
        timeline.sort(key=lambda item: item[0])
        return diff.compare((run for _, run in timeline), verdicts)

    @staticmethod
    def _note_json(note: SessionNote, session: Session | None, now: datetime) -> dict[str, Any]:
        offset = (
            offset_ms(note.at, session.clock_started_at, session.clock_ended_at, now)
            if session is not None
            else None
        )
        return note.to_json(offset)

    # --- writes -----------------------------------------------------------

    async def add_note(self, session_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        def write() -> tuple[SessionNote, Session]:
            session = self._session_for_notes(session_id)
            stamp = now_iso()
            note = SessionNote(
                id=new_note_id(),
                session_id=session.id,
                cohort_id=session.cohort_id,
                at=_moment(fields.get("at")) or stamp,
                created_at=stamp,
                tag=str(fields.get("tag") or ""),
                body=str(fields.get("body") or ""),
                carry_forward=fields.get("carryForward") is True,
            )
            _apply_scope(note, fields.get("scope"))
            check_note(note)
            self._check_animal(note)
            return self.repo.add(note), session

        note, session = await asyncio.to_thread(write)
        await self._changed(session.cohort_id, [session.id])
        return {"note": self._note_json(note, session, datetime.now(timezone.utc))}

    async def edit_note(self, note_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        def write() -> tuple[SessionNote, Session]:
            note = self.repo.get(note_id)
            session = self._sessions.get_session(note.session_id)
            if "tag" in fields:
                note.tag = str(fields["tag"] or "")
            if "body" in fields:
                note.body = str(fields["body"] or "")
            if "carryForward" in fields:
                note.carry_forward = fields["carryForward"] is True
            if "at" in fields:
                moment = _moment(fields["at"])
                if moment is None:
                    raise NoteInvalid("That time isn't readable.")
                note.at = moment
            if "scope" in fields:
                _apply_scope(note, fields["scope"])
            check_note(note)
            self._check_animal(note)
            return self.repo.save(note), session

        note, session = await asyncio.to_thread(write)
        await self._changed(session.cohort_id, [session.id])
        return {"note": self._note_json(note, session, datetime.now(timezone.utc))}

    async def delete_note(self, note_id: str) -> dict[str, Any]:
        note = await asyncio.to_thread(self.repo.soft_delete, note_id)
        await self._changed(note.cohort_id, [note.session_id])
        return {}

    async def resolve_flag(
        self, note_id: str, resolved: bool, session_id: str | None
    ) -> dict[str, Any]:
        def write() -> tuple[SessionNote, Session | None]:
            if session_id is not None:
                self._sessions.get_session(session_id)  # SessionNotFound
            note = self.repo.set_resolved(note_id, resolved, session_id)
            try:
                return note, self._sessions.get_session(note.session_id)
            except SessionNotFound:
                return note, None

        note, session = await asyncio.to_thread(write)
        touched = [note.session_id] + ([session_id] if session_id else [])
        await self._changed(note.cohort_id, touched)
        return {"note": self._note_json(note, session, datetime.now(timezone.utc))}

    async def set_session_log(self, session_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        def write() -> tuple[SessionLog, Session]:
            session = self._session_for_notes(session_id)
            clean = {
                key: (None if fields[key] is None else str(fields[key]))
                for key in ("operator", "summary")
                if key in fields
            }
            return self.repo.upsert_log(session.id, clean), session

        entry, session = await asyncio.to_thread(write)
        await self._changed(session.cohort_id, [session.id])
        return {"log": entry.to_json()}

    # --- announcements ----------------------------------------------------

    async def refresh(self, cohort_id: str, session_ids: list[str] | None = None) -> None:
        """Something outside the log changed what it shows — a run finalized
        (the diff grew), a session ended (its clock closed), or a tidy moved
        notes between records. Re-announce and re-mirror."""
        if session_ids is None:
            session_ids = sorted(await asyncio.to_thread(self.repo.annotated_session_ids, cohort_id))
        await self._changed(cohort_id, session_ids)

    async def _changed(self, cohort_id: str, session_ids: list[str]) -> None:
        await self._broadcast(
            event(Evt.LOGBOOK_UPDATED, {"cohortId": cohort_id, "sessionIds": session_ids})
        )
        for session_id in session_ids:
            self.schedule_mirror(session_id)

    # --- the notes.md mirror (DATA.md#the-notesmd-mirror) --------------------

    def schedule_mirror(self, session_id: str) -> None:
        """Rewrite the session folder's `notes.md` about a second from now.

        Keyed by session and debounced, so a burst of edits writes once. Must be
        called on the event loop; never awaits the write.
        """
        loop = asyncio.get_running_loop()
        pending = self._pending.pop(session_id, None)
        if pending is not None:
            pending.cancel()
        self._pending[session_id] = loop.call_later(
            MIRROR_DEBOUNCE_S, self._start_mirror, session_id
        )

    def _start_mirror(self, session_id: str) -> None:
        self._pending.pop(session_id, None)
        task = asyncio.get_running_loop().create_task(self._mirror(session_id))
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def _mirror(self, session_id: str) -> None:
        try:
            written = await asyncio.to_thread(self.write_mirror, session_id)
        except Exception:  # noqa: BLE001 - a mirror must never surface as a failure
            log.exception("logbook: couldn't render notes.md for session %s", session_id)
            return
        if written is not None and self._enqueue_backup is not None:
            self._enqueue_backup(written)

    def write_mirror(self, session_id: str) -> Path | None:
        """Render and write one session folder's `notes.md`; synchronous.

        Covers every record sharing the folder — split records write into one
        folder (`DATA.md#tidy-records`), and a file per record would have
        folder-mates overwrite each other. Skipped when nobody in the folder
        has written anything and there is no earlier `notes.md` to update.
        """
        try:
            session = self._sessions.get_session(session_id)
        except SessionNotFound:
            return None
        if not session.folder_path:
            return None
        with self._folder_lock(session.folder_path):
            return self._write_folder_mirror(session)

    def _folder_lock(self, folder_path: str) -> threading.Lock:
        key = _folder_key(folder_path)
        with self._folder_locks_guard:
            return self._folder_locks.setdefault(key, threading.Lock())

    def _write_folder_mirror(self, session: Session) -> Path | None:
        folder = Path(session.folder_path).expanduser()
        mates = [
            s
            for s in self._sessions.list_sessions(session.cohort_id, include_aborted=True)
            if s.folder_path and _same_folder(s.folder_path, session.folder_path)
        ]
        ids = [s.id for s in mates]
        notes = self.repo.notes_for_sessions(ids)
        logs = self.repo.logs_for_sessions(ids)
        target = folder / mirror.FILENAME
        annotated = bool(notes) or any(not entry.is_blank for entry in logs)
        if not annotated and not target.exists():
            return None
        try:
            cohort = self._cohorts.get(session.cohort_id)
            names = {animal.id: animal.name for animal in cohort.animals}
            cohort_name = cohort.name
        except Exception:  # noqa: BLE001
            names, cohort_name = {}, ""
        changes = self._changes(session.cohort_id)
        text = mirror.render_markdown(
            cohort_name=cohort_name,
            sessions=mates,
            logs=logs,
            notes=notes,
            changes=[c for c in changes.values() if c["sessionId"] in ids],
            animal_names=names,
            now=datetime.now(timezone.utc),
        )
        return mirror.write_mirror(folder, text)

    async def drain(self) -> None:
        """Flush pending mirrors now — shutdown, and tests."""
        for session_id, handle in list(self._pending.items()):
            handle.cancel()
            self._pending.pop(session_id, None)
            self._start_mirror(session_id)
        if self._writes:
            await asyncio.gather(*list(self._writes), return_exceptions=True)

    # --- validation -------------------------------------------------------

    def _session_for_notes(self, session_id: str) -> Session:
        if session_id.startswith("adopted:"):
            # A payload-only grouping of recovered files (`DATA.md#orphan-adoption`):
            # there is no record to hang a note on, and inventing one would
            # corrupt session-number suggestion.
            raise NoteInvalid(
                "This session was recovered from files and has no record to note against."
            )
        return self._sessions.get_session(session_id)

    def _check_animal(self, note: SessionNote) -> None:
        if note.scope_kind != "animal":
            return
        cohort = self._cohorts.get(note.cohort_id)
        known = {animal.id for animal in cohort.animals}
        recorded = {
            run.animal_id for run in self._sessions.runs_for(note.session_id)
        }
        if note.animal_id not in known | recorded:
            raise NoteInvalid("That animal isn't in this cohort.")


def _apply_scope(note: SessionNote, scope: Any) -> None:
    if scope is None:
        return
    if not isinstance(scope, dict):
        raise NoteInvalid("A scope is an object.")
    kind = scope.get("kind") or "session"
    note.scope_kind = str(kind)
    note.animal_id = scope.get("animalId") if kind == "animal" else None
    box = scope.get("box")
    note.box_number = box if kind == "box" and isinstance(box, int) and not isinstance(box, bool) else None


def _moment(value: Any) -> str | None:
    """A client-supplied time, normalized to UTC ISO with milliseconds."""
    if not isinstance(value, str):
        return None
    parsed = parse_iso(value)
    if parsed is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _folder_key(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve()).casefold()
    except OSError:  # pragma: no cover
        return path.casefold()


def _same_folder(a: str, b: str) -> bool:
    return _folder_key(a) == _folder_key(b)
