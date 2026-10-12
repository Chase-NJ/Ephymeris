"""The cohort archive — `DATA.md#the-cohort-archive`.

A cohort's sessions and runs as one read: the ones this database recorded and
the ones a rescan recovered from files (`DATA.md#orphan-adoption`), each
recovered run filed under the session the rest of the app lists it under.
Analytics, the session log, `sessions.list` and tidy all take `view` rather
than assembling that merge themselves, so they cannot disagree about which
session a recovered file belongs to, when its clock ended, or which runs are
false starts.

Also the one way to write the archive (`write`). Everything that rewrites the
records or the files and folders a walk reads (a relocate, a move, a tidy, a
rescan, a recover) holds the archive lock end to end, asks the rig whether it
may run once it holds it, and is announced through `on_changed` once it has.
A summary reads and indexes under the lock.

The reads are database only: none opens a run file, so `sessions.list` and
the session log can read the archive while a summary is still reading files.
"""

from __future__ import annotations

import asyncio
import os
from collections import Counter
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from ..cohorts import relocate
from ..sessions.models import Session, SessionAnimalRun
from ..sessions.tidy import session_key
from . import false_starts, reader
from .repository import AdoptedRun, AnalyticsRepository

log = logging.getLogger(__name__)

RELOCATE_IN_USE = "A session is set up or running. Finish it, then move the data folder."
MOVE_IN_USE = "A session is set up or running. Finish it, then move the animals."
RECOVER_WHILE_WRITING = (
    "A box is running: its live .tsv would look like an orphan. "
    "Recover once every box has finished."
)
RESCAN_WHILE_WRITING = (
    "A box is running: a run that finishes during the walk would be found "
    "twice. Rescan once every box has finished."
)


class ArchiveBusy(Exception):
    """A scan, tidy, relocate, move or recover already holds the archive."""


class RigInUse(Exception):
    """An archive write refused because a session holds the rig or a box is
    running. The message says what to do instead."""


class RigQuestions(Protocol):
    """What the archive asks the session lifecycle, under its lock."""

    @property
    def held(self) -> str | None: ...

    @property
    def in_use(self) -> bool: ...

    @property
    def writing(self) -> bool: ...


@dataclass(frozen=True)
class ArchiveChange:
    """What one archive write changed, for whoever follows a write up."""

    #: Cohorts whose records or folders changed.
    cohort_ids: frozenset[str] = frozenset()
    #: Sessions whose `notes.md` must re-render beyond the cohorts' annotated
    #: ones: a move's source session whose every note moved away.
    session_ids: frozenset[str] = frozenset()
    #: Files written, to queue for backup.
    files_to_back_up: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.cohort_ids or self.session_ids or self.files_to_back_up)


class ArchiveWrite:
    """The body of one `CohortArchive.write`: the rig as it stands under the
    lock, and what the write changed."""

    def __init__(self, rig: RigQuestions) -> None:
        self._rig = rig
        self._cohorts: set[str] = set()
        self._sessions: set[str] = set()
        self._files: list[str] = []

    @property
    def held(self) -> str | None:
        """The session holding the rig, asked now."""
        return self._rig.held

    @property
    def in_use(self) -> bool:
        """A session held or a box running, asked now."""
        return self._rig.in_use

    def changed(
        self,
        *,
        cohort_ids: Iterable[str] = (),
        session_ids: Iterable[str] = (),
        files: Iterable[str | Path] = (),
    ) -> None:
        self._cohorts.update(cohort_ids)
        self._sessions.update(session_ids)
        self._files.extend(str(f) for f in files)

    def change(self) -> ArchiveChange:
        return ArchiveChange(
            frozenset(self._cohorts), frozenset(self._sessions), tuple(self._files)
        )


@dataclass
class ArchiveView:
    """One cohort's archive as of one read. Build it with `CohortArchive.view`.

    `recovered` holds a session only for a group of recovered files no
    recorded session owns; an owned group's runs are filed under its owner.
    """

    cohort_id: str
    recorded: list[Session]
    recovered: list[Session]
    recorded_runs: list[SessionAnimalRun]
    recovered_runs: list[SessionAnimalRun]
    #: The rows behind `recovered_runs`, for the clock ends.
    _adopted: list[AdoptedRun] = field(repr=False)
    #: Synthetic session id → the recorded session that owns it.
    _owners: dict[str, str] = field(repr=False)
    #: Run id → the summary each recovered run's clock end is read from.
    _summaries: dict[str, dict[str, Any] | None] = field(repr=False)

    @property
    def sessions(self) -> list[Session]:
        """Recorded and recovered, chronologically. A string sort is right
        here: every date is ISO, legacy `MM_DD_YY` folder dates having been
        converted at adoption by `parse_session_folder`."""
        return sorted(
            [*self.recorded, *self.recovered], key=lambda s: (s.date, s.started_at, s.id)
        )

    @property
    def runs(self) -> list[SessionAnimalRun]:
        return [*self.recorded_runs, *self.recovered_runs]

    def run_counts(self) -> dict[str, int]:
        """Runs per session id. A recorded session counts the recovered files
        it owns too (`DATA.md#tidy-records`)."""
        return dict(Counter(run.session_id for run in self.runs))

    def close_clocks(self, summaries: Mapping[str, dict[str, Any] | None]) -> None:
        """Re-close the recovered sessions' clocks with fresher summaries, as
        a summary has just indexed. A run not among them keeps the cached
        one, so a filtered summary cannot move a session's end."""
        self._summaries.update(summaries)
        ends = _stream_ends(self._adopted, self._owners, self._summaries)
        for session in self.recovered:
            session.ended_at = ends.get(session.id)


class CohortArchive:
    def __init__(
        self,
        *,
        db: Any,
        cohorts: Any,
        sessions: Any,
        rig: RigQuestions,
        on_changed: Callable[[ArchiveChange], Awaitable[None]],
    ) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._repo = AnalyticsRepository(db)
        self._lock = asyncio.Lock()
        #: Asked under the lock by every write (`write`).
        self._rig = rig
        #: Hears every write that changed something, once it is done.
        self._on_changed = on_changed

    # --- reads ------------------------------------------------------------

    def view(self, cohort_id: str, *, include_aborted: bool = False) -> ArchiveView:
        """The cohort's sessions and runs, recorded and recovered.

        `include_aborted` adds aborted records to `recorded`. An aborted record
        never owns recovered files whichever way it is set (it wrote none).
        Recovered sessions' clocks close from the metrics cache: a file the
        index has not read yet leaves its session open.

        A recovered run whose file a run record also names is left out: the
        record wins (`DATA.md#database-first`). A rescan walking while a box
        finalized adopts the file its record then claims, and the next
        rescan's prune is what deletes the adoption.
        """
        recorded = self._sessions.list_sessions(cohort_id, include_aborted=include_aborted)
        recorded_runs = self._sessions.runs_for_cohort(cohort_id)
        claimed = {_path_key(run.file_path) for run in recorded_runs if run.file_path}
        adopted = [
            entry
            for entry in self._repo.adopted_for_cohort(cohort_id)
            if _path_key(entry.file_path) not in claimed
        ]
        owners = _adoption_owners(adopted, recorded)
        cached = self._repo.load_cached([entry.id for entry in adopted])
        summaries: dict[str, dict[str, Any] | None] = {
            run_id: entry.summary for run_id, entry in cached.items()
        }
        recovered = _synthetic_sessions(
            adopted, cohort_id, owners, _stream_ends(adopted, owners, summaries)
        )
        return ArchiveView(
            cohort_id=cohort_id,
            recorded=recorded,
            recovered=recovered,
            recorded_runs=recorded_runs,
            recovered_runs=[_adopted_to_run(entry, owners) for entry in adopted],
            _adopted=adopted,
            _owners=owners,
            _summaries=summaries,
        )

    def verdicts(
        self,
        runs: list[SessionAnimalRun],
        summaries: Mapping[str, dict[str, Any] | None] | None = None,
    ) -> dict[str, false_starts.Verdict]:
        """Which of `runs` are false starts (`DATA.md#false-starts`), with
        whatever a person has ruled.

        Judged from `summaries` when the caller has just scored the runs, and
        from the metrics cache otherwise, so the session log agrees with
        Analytics without reading a file. A run never scored has no trial
        count, and the rule leaves it counted.
        """
        if summaries is None:
            cached = self._repo.load_cached([run.id for run in runs])
            summaries = {run_id: entry.summary for run_id, entry in cached.items()}
        return false_starts.classify(
            (
                false_starts.RunFacts(
                    run_id=run.id,
                    session_id=run.session_id,
                    animal_id=run.animal_id,
                    order=false_starts.order_key(run.file_path, run.started_at),
                    trials=false_starts.trials_of(summaries.get(run.id)),
                )
                for run in runs
            ),
            self._repo.false_start_overrides(),
        )

    def run(self, run_id: str) -> SessionAnimalRun | None:
        """One run, recorded or recovered, by id. A recovered run is filed
        under its synthetic session here, whoever owns it."""
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM session_animal_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is not None:
            from ..sessions.repository import _hydrate_run

            return _hydrate_run(row)
        entry = self._repo.adopted_by_id(run_id)
        return _adopted_to_run(entry) if entry is not None else None

    def folders(self, cohort_id: str) -> list[str]:
        """Every session folder the archive knows: each record's, aborted
        ones included, and each recovered file's, owned or not."""
        recorded = [
            s.folder_path
            for s in self._sessions.list_sessions(cohort_id, include_aborted=True)
            if s.folder_path
        ]
        recovered = {
            str(reader.session_folder_of(Path(entry.file_path)))
            for entry in self._repo.adopted_for_cohort(cohort_id)
        }
        return [*recorded, *sorted(recovered)]

    # --- the lock ---------------------------------------------------------

    @asynccontextmanager
    async def exclusive(self, *, wait: bool = False) -> AsyncIterator[None]:
        """Hold the archive. `server.py` runs every command as its own task,
        so two can arrive together.

        Only a summary waits (`wait=True`). Everything else is refused with
        `ArchiveBusy` while the archive is held, so a double-click cannot queue
        a second walk or a second move behind the first. A writer takes it
        through `write`.
        """
        if not wait and self._lock.locked():
            raise ArchiveBusy(
                "a scan, tidy, recover or move of this archive is running — "
                "try again when it finishes"
            )
        async with self._lock:
            yield

    # --- writes ------------------------------------------------------------

    @asynccontextmanager
    async def write(
        self,
        *,
        refuse_while: Literal["in_use", "writing"] | None = None,
        because: str = "",
    ) -> AsyncIterator[ArchiveWrite]:
        """Hold the archive for one write (`DATA.md#the-cohort-archive`).

        `ArchiveBusy` while anything holds it. Once held, `RigInUse(because)`
        while the rig is `refuse_while`: `in_use` (a session held or a box
        running) or `writing` (a box running). Asked under the lock, so a
        session that starts while a caller decides cannot slip past it.

        The body says what it changed through the `ArchiveWrite` it is handed;
        `on_changed` hears it once the lock is released, even when the body
        then failed, since what it changed stays changed. A failing
        `on_changed` is logged, never raised: the write itself is done.
        """
        write = ArchiveWrite(self._rig)
        try:
            async with self.exclusive():
                if refuse_while is not None and getattr(self._rig, refuse_while):
                    raise RigInUse(because)
                yield write
        finally:
            change = write.change()
            if change:
                try:
                    await self._on_changed(change)
                except Exception:  # noqa: BLE001 - the write is done; its follow-up is not it
                    log.exception("couldn't announce an archive write: %s", change)

    async def relocate(self, cohort_id: str, destination: str, move_existing: bool) -> Path:
        """Change a cohort's data folder, its records' paths following its
        files (`DATA.md#data-folder`). Under the lock, or a rescan reading the
        records mid-move would prune every run whose file had just left.
        Moving the contents is refused while the rig is in use: a session
        writing into the folder would be writing into one that moves."""
        async with self.write(
            refuse_while="in_use" if move_existing else None, because=RELOCATE_IN_USE
        ) as write:
            final = await asyncio.to_thread(
                relocate.relocate_cohort, self._db, cohort_id, destination, move_existing
            )
            write.changed(cohort_ids=[cohort_id])
        return final

    async def move_animals(self, request: Any, *, apply: bool) -> dict[str, Any]:
        """Preview or carry out a move (`DATA.md#moving-animals-between-cohorts`),
        as the plan's wire shape. Under the lock, since a move rewrites the
        records and the folders a walk reads.

        A rig in use is one of the plan's refusals, asked under the lock: a
        preview lists it beside the others, and an apply raises `MoveRefused`
        with the plan.
        """
        from ..cohorts import move_apply  # cohorts.move imports analytics.reader

        async with self.write() as write:
            busy = MOVE_IN_USE if write.in_use else None
            if not apply:
                plan = await asyncio.to_thread(move_apply.preview, self._db, request, busy=busy)
                return plan.to_json(applied=False)
            plan = await asyncio.to_thread(move_apply.apply, self._db, request, busy=busy)
            result = plan.to_json(applied=True)
            write.changed(
                cohort_ids=[request.source_id, request.dest_id],
                session_ids=[s["sessionId"] for s in result["sessions"]],
                files=[f.dst for f in plan.files],
            )
        return result

    async def recover(self, cohort_id: str) -> dict[str, Any]:
        """Rebuild `.json`/`.mat` from a cohort's orphaned `.tsv` files
        (`DATA.md#crash-recovery`), as the `RecoverResult` wire shape.

        Under the lock, since it writes into folders a relocate or a move
        could be carrying off. Refused while a box runs: a live run's `.tsv`
        has no `.json` yet and is not an orphan. One session runs at a time
        app-wide, so any running box means hands off every archive.
        """
        from ..sessions import recovery  # recovery imports analytics.reader

        async with self.write(refuse_while="writing", because=RECOVER_WHILE_WRITING) as write:
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            result = await asyncio.to_thread(recovery.recover_cohort, cohort.data_folder)
            write.changed(files=await asyncio.to_thread(_recovered_files, result["entries"]))
        return {**result, "cohortId": cohort_id}


def _recovered_files(entries: list[dict[str, Any]]) -> list[Path]:
    """The files a recovery wrote: each recovered entry's `.json`, and its
    `.mat` when that best-effort write landed."""
    files: list[Path] = []
    for entry in entries:
        if entry["status"] != "recovered":
            continue
        files.append(Path(entry["jsonPath"]))
        mat = reader.sibling_mat(Path(entry["tsvPath"]))
        if mat.is_file():
            files.append(mat)
    return files


# --- recovered sessions (DATA.md#orphan-adoption) ------------------------------


def _path_key(path: str) -> str:
    """A stored path in the one spelling two records of one file share. From
    the string alone: the view reads the database, never the disk."""
    return os.path.normcase(os.path.normpath(os.path.expanduser(path))).casefold()


def _synthetic_session_id(entry: AdoptedRun) -> str:
    """One id per (prefix, number, date) group — stable across rescans, so a
    frontend session selection survives a refresh."""
    return f"adopted:{entry.prefix_name}_{entry.session_number}_{entry.date or 'undated'}"


def _adoption_owners(adopted: list[AdoptedRun], recorded: list[Session]) -> dict[str, str]:
    """Which recorded session each synthetic session actually is
    (`DATA.md#tidy-records`).

    An orphan is adopted under a synthetic session named from its folder —
    `adopted:<prefix>_<number>_<date>`. When this database also RECORDED a
    session with that prefix, number and date, the two are one session: the
    same folder, the files a crash left without a run record. Listing them
    separately showed a day that went wrong as two days' worth of sessions.

    The earliest recorded match wins, the one a tidy would keep. Aborted
    records are never owners: they wrote nothing.
    """
    owner_of: dict[tuple[str, str, str], str] = {}
    for session in sorted(recorded, key=lambda s: (s.date, s.started_at, s.id)):
        if session.id.startswith("adopted:") or session.status == "aborted":
            continue
        owner_of.setdefault(
            session_key(session.prefix_name, session.session_number, session.date),
            session.id,
        )
    owners: dict[str, str] = {}
    for entry in adopted:
        synthetic = _synthetic_session_id(entry)
        if synthetic in owners:
            continue
        owner = owner_of.get(
            session_key(entry.prefix_name, entry.session_number, entry.date or "")
        )
        if owner is not None:
            owners[synthetic] = owner
    return owners


def _adopted_to_run(
    entry: AdoptedRun, owners: dict[str, str] | None = None
) -> SessionAnimalRun:
    """An adopted orphan in `SessionAnimalRun` clothing, so the indexing,
    caching, and profile ladder treat it exactly like a recorded run. The box
    number is honestly unknown — a filename doesn't carry one."""
    run = SessionAnimalRun(
        id=entry.id,
        session_id=(owners or {}).get(
            _synthetic_session_id(entry), _synthetic_session_id(entry)
        ),
        animal_id=entry.animal_id,
        box_number=None,  # type: ignore[arg-type]
        sketch_path=entry.sketch_path or "",
        file_path=entry.file_path,
        started_at=entry.started_at,
    )
    # The name the document asked for, kept alongside rather than added to the
    # model: `SessionAnimalRun` is a persisted row shape and an adopted run is
    # not persisted as one. `_resolve_profile` reads it to explain an
    # unresolvable sketch instead of silently scoring nothing.
    run.sketch_name = entry.sketch_name  # type: ignore[attr-defined]
    return run


def _synthetic_sessions(
    adopted: list[AdoptedRun],
    cohort_id: str,
    owners: dict[str, str],
    ends: dict[str, str],
) -> list[Session]:
    """Payload-only session entries grouped from adopted runs' folder names.

    Never database rows — a fabricated `sessions` row would corrupt
    session-number suggestion and the same-day reuse warning (`DATA.md#database-first`).

    A group `owners` maps to a recorded session gets no entry of its own
    (`DATA.md#tidy-records`). `ends` (`_stream_ends`) closes each session's
    clock; a session with no entry stays open, which the Log prints as
    "not recorded".
    """
    groups: dict[str, list[AdoptedRun]] = {}
    for entry in adopted:
        groups.setdefault(_synthetic_session_id(entry), []).append(entry)

    sessions: list[Session] = []
    for session_id, entries in groups.items():
        if session_id in owners:
            continue
        first = min(entries, key=lambda e: e.started_at)
        sessions.append(
            Session(
                id=session_id,
                cohort_id=cohort_id,
                prefix_id="",
                prefix_name=first.prefix_name,
                session_number=first.session_number,
                date=first.date or "",
                started_at=first.started_at,
                ended_at=ends.get(session_id),
                status="completed",
                folder_path=str(reader.session_folder_of(Path(first.file_path))),
            )
        )
    return sessions


def _stream_end(started_at: str, summary: dict[str, Any] | None) -> datetime | None:
    """When a recovered run's recorded stream ended: its start plus the
    stream's span (`durationMs`), the same derivation the session table draws
    as `~`. Nothing records when a recovered run stopped; its file records how
    long it ran. `None` for a start without a time of day (a file named with
    no `HHMMSS`) or a file the index has not read."""
    duration = (summary or {}).get("durationMs")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        return None
    if "T" not in started_at:
        return None
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return start + timedelta(milliseconds=float(duration))


def _stream_ends(
    adopted: Iterable[AdoptedRun],
    owners: dict[str, str],
    summaries: Mapping[str, dict[str, Any] | None],
) -> dict[str, str]:
    """Each synthetic session's clock end (`DATA.md#the-session-clock`): the
    latest of its runs' stream ends, in the same spelling as their starts.
    A session whose files have all gone unread has no entry. A group a
    recorded session owns is skipped — that session has its own clock."""
    latest: dict[str, datetime] = {}
    for entry in adopted:
        session_id = _synthetic_session_id(entry)
        if session_id in owners:
            continue
        end = _stream_end(entry.started_at, summaries.get(entry.id))
        if end is not None and (session_id not in latest or end > latest[session_id]):
            latest[session_id] = end
    return {sid: end.isoformat(timespec="milliseconds") for sid, end in latest.items()}
