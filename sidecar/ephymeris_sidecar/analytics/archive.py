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
A summary reads and indexes under the lock. The rescan's walk, prune and
adoption and the tidy live here too, with their disk questions in `walk.py`.

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
from ..logbook.repository import LogbookRepository
from ..sessions import tidy as session_tidy
from ..sessions.models import Session, SessionAnimalRun
from ..sessions.paths import parse_name_date, parse_name_time, parse_session_folder
from ..sessions.tidy import session_key
from . import reader
from .repository import AdoptedRun, AnalyticsRepository
from .scoring import current_version
from .stream import false_starts
from .walk import (
    _adoptable_animals,
    _animal_from_filename,
    _earlier_ids,
    _folder_state,
    _is_gone,
    _iso_or_none,
    _normalize,
    _orphan_run_id,
    _prefer,
    _remove_empty_tree,
    _same_path,
)

log = logging.getLogger(__name__)

RELOCATE_IN_USE = "A session is set up or running. Finish it, then move the data folder."
MOVE_IN_USE = "A session is set up or running. Finish it, then move the animals."
RECOVER_WHILE_WRITING = (
    "A box is running: its live .tsv would look like an orphan. "
    "Recover once every box has finished."
)
REDERIVE_WHILE_WRITING = (
    "A box is running: a finishing run writes its own .json. "
    "Re-derive once every box has finished."
)
RESCAN_WHILE_WRITING = (
    "A box is running: a run that finishes during the walk would be found "
    "twice. Rescan once every box has finished."
)


class ArchiveBusy(Exception):
    """A scan, tidy, relocate, move, recover or re-derive already holds the archive."""


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
        sketch_lookup: Callable[[str], str | None] | None = None,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._repo = AnalyticsRepository(db)
        #: Read only for which sessions carry notes — those are never empty
        #: and never pruned (`DATA.md#the-session-log`).
        self._logbook = LogbookRepository(db)
        #: Resolve a document's `sketch` *name* to a sketch in this install's
        #: library when a rescan adopts an orphan (`DATA.md#orphan-adoption`).
        self._sketch_lookup = sketch_lookup
        #: Where a rescan's progress goes; none, and it reports nothing.
        self._broadcast = broadcast
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
        index has not read yet, or has not read since the cache's version
        moved (`DATA.md#caching`), leaves its session open.

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
        cached = self._repo.load_cached(
            [entry.id for entry in adopted], version=current_version()
        )
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
        """Which of `runs` are false starts (`ANALYTICS.md#false-starts`), with
        whatever a person has ruled.

        Judged from `summaries` when the caller has just scored the runs, and
        from the metrics cache otherwise, so the session log agrees with
        Analytics without reading a file. A run never scored has no trial
        count, and the rule leaves it counted.
        """
        if summaries is None:
            cached = self._repo.load_cached(
                [run.id for run in runs], version=current_version()
            )
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
        recorded = self._sessions.run(run_id)
        if recorded is not None:
            return recorded
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


    async def rederive(self, cohort_id: str) -> dict[str, Any]:
        """Rewrite the derived trial table of a cohort's spine runs where this
        build derives a different one (`DATA.md#re-derive`), as the
        `RederiveResult` wire shape.

        Refused while a box runs, as `recover` is: a finishing run writes
        its own `.json`. Every file it wrote, and only those, is queued for
        backup.
        """
        from ..sessions import derived  # sessions imports analytics.reader

        async with self.write(refuse_while="writing", because=REDERIVE_WHILE_WRITING) as write:
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            result = await asyncio.to_thread(derived.rederive_cohort, cohort.data_folder)
            write.changed(files=result.pop("written"))
        return {**result, "cohortId": cohort_id}

    # --- rescan ------------------------------------------------------------

    async def rescan(self, cohort_id: str, *, adopt_orphans: bool = True) -> dict[str, Any]:
        """Reconcile a cohort's records against its archive, both ways
        (`DATA.md#orphan-adoption`, `DATA.md#pruning`).

        The database-first path covers everything this app recorded. The walk
        covers what it didn't: runs finalized with no active session, a crash
        between the file write and the commit, and files restored from the
        backup mirror or copied from the other lab machine.

        And the **prune** covers the other direction, which nothing else in the
        app does: records whose files the disk no longer has. A deleted session
        leaves its rows behind forever otherwise, and the deliberate "a
        missing file keeps its last good summary" rule (`DATA.md#caching`)
        then keeps charting it —
        correct for an unplugged drive, wrong for a session the operator threw
        away. Rescan is where that gets resolved because it is the one moment
        the operator has explicitly said *the disk is the truth now*.

        Refused (`RigInUse`) while a box runs: a run finalizing mid-walk has
        its file adopted as well as its record committed
        (`DATA.md#the-cohort-archive`).
        """
        async with self.write(
            refuse_while="writing", because=RESCAN_WHILE_WRITING
        ) as write:
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            folder_exists = await asyncio.to_thread(
                lambda: Path(cohort.data_folder).expanduser().is_dir()
            )
            # Records an earlier relocate left at the old folder are re-pointed
            # *before* the prune, which would otherwise read their files as
            # deleted and drop them (`DATA.md#data-folder`).
            rehomed = (
                await asyncio.to_thread(relocate.rehome, self._db, cohort_id)
                if adopt_orphans and folder_exists
                else 0
            )
            # Prune before the walk, so `known` is built from surviving records
            # and a run whose file *moved* is re-adopted in the same pass
            # rather than pruned on one scan and re-found on the next.
            pruned, dropped = (
                await asyncio.to_thread(self._prune, cohort_id)
                if adopt_orphans and folder_exists
                else ({"runs": 0, "sessions": 0, "adopted": 0}, {})
            )
            runs = await asyncio.to_thread(self._sessions.runs_for_cohort, cohort_id)
            known = {
                _normalize(r.file_path) for r in runs if r.file_path
            }
            await self._progress(cohort_id, "walking", 0, 0)
            found = await asyncio.to_thread(reader.walk_session_files, cohort.data_folder)

            # Which of those files this cohort has already adopted, unchanged
            # since (`DATA.md#carrying-adoptions-forward`). One thread hop and
            # one stat per file, against a walk that would otherwise open and
            # parse every one of them again.
            carried, held = (
                await asyncio.to_thread(self._carry_over, found, known, cohort_id)
                if adopt_orphans
                else ({}, {})
            )

            orphans: list[dict[str, Any]] = []
            # Keyed by run identity, not path: a hand-managed archive often
            # holds a consolidated copy of every session beside the per-prefix
            # originals, and adopting both would silently double every animal
            # in every view and put two points per session on every curve.
            best: dict[str, AdoptedRun] = {}
            duplicates = 0
            for path in found:
                if _normalize(str(path)) in known:
                    continue
                identity = reader.run_identity(path)
                settled = carried.get(identity)
                if settled is not None and _same_path(settled.file_path, path):
                    if identity in best:
                        # Another copy of this run already claimed the slot this
                        # scan and was judged on merit. This one is the extra.
                        duplicates += 1
                        continue
                    # Already adopted from this exact file, and the file has not
                    # changed. Held in `best` rather than skipped outright: a
                    # *duplicate* copy must still win on merit through `_prefer`
                    # rather than by being the only candidate in the room.
                    best[identity] = settled
                    continue
                entry, adoption = await asyncio.to_thread(
                    self._describe_orphan, path, cohort, cohort_id, held.get(identity)
                )
                if adoption is None:
                    orphans.append(entry)
                    continue
                incumbent = best.get(identity)
                if incumbent is None:
                    best[identity] = adoption
                    orphans.append(entry)
                    continue
                duplicates += 1
                if _prefer(adoption, incumbent):
                    best[identity] = adoption

            # Only what this scan actually decided. A row carried over unchanged
            # is left alone rather than rewritten with identical values: every
            # commit marks the whole database dirty for backup
            # (`DATA.md#the-database-copy`),
            # so rewriting an archive's worth of rows per click is a whole-file
            # copy to a possibly-networked target per click. `is not` rather
            # than equality — a carried row that a duplicate copy beat is a
            # genuine change and must be written.
            adoptable = [
                entry
                for identity, entry in best.items()
                if carried.get(identity) is not entry
            ]
            adopted = 0
            if adopt_orphans and adoptable:
                sources = await asyncio.to_thread(self._move_sources, cohort_id)
                # INSERT OR REPLACE on the row's id, so a file whose content
                # changed since adoption refreshes its row in place rather than
                # duplicating it. Counted as written: a row another cohort
                # holds is never taken.
                adopted = await asyncio.to_thread(
                    lambda: self._repo.store_adopted(
                        adoptable,
                        earlier_ids=_earlier_ids(adoptable, held, dropped, sources),
                    )
                )
            if carried:
                log.info(
                    "analytics: rescan of cohort %s reused %d already-adopted"
                    " files and read %d",
                    cohort_id,
                    len(carried),
                    len(found) - len(carried),
                )

            await self._progress(cohort_id, "walking", len(found), len(found))
            if adopted or rehomed or any(pruned.values()):
                write.changed(cohort_ids=[cohort_id])

        return {
            "scanned": len(found),
            "adopted": adopted,
            "pruned": pruned,
            "rehomed": rehomed,
            "duplicates": duplicates,
            "orphans": orphans,
            "cohortId": cohort_id,
            "dataFolder": cohort.data_folder,
            "folderMissing": not folder_exists,
        }

    # --- pruning (DATA.md#pruning) -----------------------------------------

    def _prune(self, cohort_id: str) -> tuple[dict[str, int], dict[str, str]]:
        """Drop records for files the disk demonstrably no longer has.

        Returns the counts, and the id of each adoption it dropped by run
        identity: a run whose file only moved is adopted again by the same
        rescan, and a ruling on the dropped id follows it (`_earlier_ids`).

        One worker-thread hop for the whole pass, like the rest of this module:
        it is a stat per record and a handful of batched `DELETE`s, and the
        archive lock is already held.

        Ordering matters twice. Runs go first so that the session sweep can ask
        the honest question — *is anything still pointing at this session?* —
        rather than guessing from the folder alone, and so that a run already on
        its way out cannot claim a file on behalf of a record that is about to
        stop existing.
        """
        removed_runs: list[str] = []
        for run in self._sessions.runs_for_cohort(cohort_id):
            if _is_gone(run.file_path):
                removed_runs.append(run.id)

        run_count = self._sessions.delete_runs(removed_runs)

        # Adoptions go for either of two reasons. The file being gone is the
        # obvious one. The other is a recorded run that now owns the file: the
        # walk skips a path a run record claims, so an adoption made *before*
        # that record existed is never revisited and quietly doubles the run in
        # every panel — the one failure the whole deduplication exists to
        # prevent, arriving from the side it doesn't watch. Database-first
        # (`DATA.md#database-first`) decides it: the record wins and the adoption goes.
        claimed = {
            _normalize(run.file_path)
            for run in self._sessions.runs_for_cohort(cohort_id)
            if run.file_path
        }
        removed = [
            entry
            for entry in self._repo.adopted_for_cohort(cohort_id)
            if _is_gone(entry.file_path) or _normalize(entry.file_path) in claimed
        ]
        removed_adopted = [entry.id for entry in removed]
        dropped = {reader.run_identity(Path(entry.file_path)): entry.id for entry in removed}

        adopted_count = self._repo.delete_adopted(removed_adopted)
        # The cache is the thing that was actually still serving numbers, so it
        # is cleared for every pruned run of either kind.
        self._repo.forget_cached(removed_runs + removed_adopted)

        # A session is dropped only once nothing is left that points at it: its
        # folder is gone *and* it has no surviving runs. Both halves are needed.
        # Folder-gone alone would delete the record of a session whose runs were
        # written elsewhere (a cohort relocated with `moveExisting: false` leaves
        # exactly that shape). No-runs alone would delete every aborted session,
        # which never wrote a file in the first place and whose folder is real.
        #
        # A session the operator wrote notes on is never pruned: the notes are
        # their data, not bookkeeping, and they outlive the folder they were
        # mirrored into (`DATA.md#the-session-log`).
        surviving = self._sessions.run_counts_by_session(cohort_id)
        annotated = self._logbook.annotated_session_ids(cohort_id)
        doomed = [
            session.id
            for session in self._sessions.list_sessions(cohort_id, include_aborted=True)
            if not surviving.get(session.id)
            and session.id not in annotated
            and _is_gone(session.folder_path, kind="folder")
        ]
        # `delete_sessions` refuses an open session; count what it actually did.
        session_count = self._sessions.delete_sessions(doomed)

        if run_count or adopted_count or session_count:
            log.info(
                "analytics: pruned %d run records, %d adoptions and %d sessions"
                " for cohort %s — their files are no longer on disk",
                run_count,
                adopted_count,
                session_count,
                cohort_id,
            )
        return {
            "runs": run_count,
            "sessions": session_count,
            "adopted": adopted_count,
        }, dropped

    # --- tidying records (DATA.md#tidy-records) ----------------------------

    async def tidy(self, cohort_id: str, *, apply: bool, today: str) -> dict[str, Any]:
        """Merge a day's split records and drop empty ones — or say what would.

        `apply=False` is the preview the operator confirms; `apply=True`
        re-plans from scratch rather than trusting a plan the client holds,
        because the whole point of the lock is that nothing moved in between.
        Refused while anything holds the archive, like a second rescan: both
        move run records between the rows a summary reads. The session holding
        the rig, asked once the archive is held, is never touched.
        """
        async with self.write() as write:
            held = write.held
            result = await asyncio.to_thread(
                self._tidy, cohort_id, apply, {held} if held else set(), today
            )
            if result["applied"]:
                write.changed(cohort_ids=[cohort_id])
        return result

    def _tidy(
        self, cohort_id: str, apply: bool, protect: set[str], today: str
    ) -> dict[str, Any]:
        self._cohorts.get(cohort_id)  # CohortNotFound for an unknown id
        view = self.view(cohort_id, include_aborted=True)
        # Recovered files a record owns are its data as much as its run rows.
        counts = view.run_counts()

        planned = session_tidy.plan(
            view.recorded,
            run_counts=counts,
            folder_state=_folder_state,
            protect=protect,
            today=today,
            annotated=self._logbook.annotated_session_ids(cohort_id),
        )
        if not apply or planned.is_empty:
            return session_tidy.plan_json(
                planned, counts, cohort_id=cohort_id, applied=apply and planned.is_empty
            )

        # A merged record's count is its whole day, for the reply.
        merged_counts = dict(counts)
        # One unit of work (`DATA.md#transactions`): a merge the database
        # refuses undoes the ones before it, so a cohort is never half-tidied.
        with self._db.write() as tx:
            for merge in planned.merges:
                fields = session_tidy.merged_fields(merge)
                self._sessions.absorb_sessions(
                    merge.keep.id, [s.id for s in merge.absorb], **fields, tx=tx
                )
                merged_counts[merge.keep.id] = sum(
                    counts.get(s.id, 0) for s in (merge.keep, *merge.absorb)
                )
            self._sessions.discard_sessions([e.session.id for e in planned.empty], tx=tx)

        # Folders last, and only a folder no surviving record points at and
        # that still holds no file — re-checked now, not trusted from the plan.
        surviving = {
            _normalize(s.folder_path)
            for s in self._sessions.list_sessions(cohort_id, include_aborted=True)
            if s.folder_path
        }
        for entry in planned.empty:
            folder = entry.session.folder_path
            if entry.removes_folder and _normalize(folder) not in surviving:
                _remove_empty_tree(folder)

        log.info(
            "analytics: tidied cohort %s — %d merges, %d empty records removed",
            cohort_id,
            len(planned.merges),
            len(planned.empty),
        )
        return session_tidy.plan_json(
            planned, merged_counts, cohort_id=cohort_id, applied=True
        )

    def _move_sources(self, cohort_id: str) -> dict[str, str | None]:
        """The cohorts a move brought this one's animals from, each with its
        data folder, or None once it is deleted (`_earlier_ids`)."""
        folders = {c.id: c.data_folder for c in self._cohorts.list_cohorts()}
        return {c: folders.get(c) for c in self._repo.move_sources(cohort_id)}

    # --- carrying adoptions forward (DATA.md#carrying-adoptions-forward) --

    def _carry_over(
        self, found: list[Path], known: set[str], cohort_id: str
    ) -> tuple[dict[str, AdoptedRun], dict[str, str]]:
        """The adoptions this walk does not need to redo, by run identity —
        and the id of every adoption this cohort holds, by run identity, which
        a file the walk does read is stored under again (`_orphan_run_id`).

        Adoption used to be repeated in full on every rescan: each of an
        archive's files was opened, parsed and written back, so a cohort with a
        few hundred runs paid a few hundred reads and a full row rewrite per
        click — on the machine whose archive lives on a network share, over the
        wire. Nothing came of it. The row is keyed on run identity and the
        inputs are the same file and the same roster, so the second scan
        recomputed the first scan's answer.

        A file is carried forward when three things hold, and the third is the
        one that keeps this honest:

        1. An adopted row exists for its **run identity**.
        2. That row names **this same path** — not merely the same run. Which
           copy of a duplicated run won is a content decision (`_prefer`), so a
           second copy has to be read and judged, never assumed.
        3. The file's **mtime and size** match what the row was adopted from —
           the same freshness key `run_metrics_cache` uses (`DATA.md#caching`), and the
           reason this is a cache rather than a "do it once" flag. Edit the
           document, or let recovery rewrite it, and the next rescan reads it
           again and refreshes the row.

        A row from before v7 has no recorded stat and is therefore never fresh:
        it is re-read once, gains a stat, and is carried from then on.
        """
        index = {
            reader.run_identity(Path(entry.file_path)): entry
            for entry in self._repo.adopted_for_cohort(cohort_id)
        }
        out: dict[str, AdoptedRun] = {}
        for path in found:
            if _normalize(str(path)) in known:
                continue
            identity = reader.run_identity(path)
            entry = index.get(identity)
            if entry is None or entry.file_mtime_ns is None or entry.file_size is None:
                continue
            if not _same_path(entry.file_path, path):
                continue
            stat = reader.stat_run(path)
            if (
                stat.ok
                and stat.mtime_ns == entry.file_mtime_ns
                and stat.size == entry.file_size
            ):
                out[identity] = entry
        return out, {identity: entry.id for identity, entry in index.items()}

    def _describe_orphan(
        self, path: Path, cohort: Any, cohort_id: str, held_id: str | None = None
    ) -> tuple[dict[str, Any], AdoptedRun | None]:
        """Match a stray file to an animal by name, and never guess
        (`DATA.md#orphan-adoption`).

        The document's `rat` field is a *name*, so this is permanently broken
        by a rename — which is exactly why the database-first path is primary
        and this is the fallback. An unmatched file is kept and reported
        unattributed rather than attached to a plausible-looking animal.

        Returns the wire-facing orphan entry plus, when the file both parsed
        and matched, the `AdoptedRun` the caller may persist. Adoption fields
        come from what a name can honestly carry: the *session folder* yields
        prefix, number, and date (either date spelling); the file stem yields
        the start time; the box, stop reason, and end time stay unknown.
        """
        result = reader.read_run(path)
        session_folder = reader.session_folder_of(path)
        rat = None
        if result.ok and result.document is not None:
            value = result.document.get("rat")
            rat = value if isinstance(value, str) else None
        match = None
        source = None
        candidates = _adoptable_animals(cohort)
        if rat:
            folded = rat.casefold()
            match = next((a.id for a in candidates if a.name.casefold() == folded), None)
            if match is not None:
                source = "document"
        if match is None:
            # The document's field is not the only place this run recorded its
            # animal — the filename did too, in the same breath.
            match = _animal_from_filename(path, session_folder, candidates)
            if match is not None:
                source = "filename"
        entry = {
            "path": str(path),
            "animalId": match,
            "animalName": rat,
            "animalSource": source,
            "date": _iso_or_none(parse_name_date(path.name)),
            "status": result.status,
            "reason": result.detail,
        }
        if match is None or not result.ok or result.document is None:
            return entry, None

        parsed = parse_session_folder(session_folder.name)
        date_iso = parsed.date.isoformat() if parsed.date is not None else None
        time = parse_name_time(path.name)
        if date_iso and time:
            started_at = f"{date_iso}T{time}"
        else:
            started_at = date_iso or ""

        sketch = result.document.get("sketch")
        sketch_name = sketch if isinstance(sketch, str) and sketch else None
        sketch_path = None
        if sketch_name is not None and self._sketch_lookup is not None:
            sketch_path = self._sketch_lookup(sketch_name)

        return entry, AdoptedRun(
            # The id this cohort already holds the run under, if any, so a
            # re-read never re-keys a row (`DATA.md#orphan-adoption`).
            id=held_id or _orphan_run_id(cohort_id, path),
            cohort_id=cohort_id,
            animal_id=match,
            file_path=str(path),
            prefix_name=parsed.prefix,
            session_number=parsed.session_number,
            date=date_iso,
            started_at=started_at,
            sketch_name=sketch_name,
            sketch_path=sketch_path,
            # Free: `read_run` stats before it parses and hands both back, so
            # recording what this adoption was taken from costs nothing here and
            # is what lets the next rescan skip the file entirely
            # (`DATA.md#carrying-adoptions-forward`).
            file_mtime_ns=result.mtime_ns,
            file_size=result.size,
        )

    # --- progress ----------------------------------------------------------

    async def _progress(self, cohort_id: str, phase: str, done: int, total: int) -> None:
        from ..protocol import Evt, event

        if self._broadcast is None:
            return
        await self._broadcast(
            event(
                Evt.ANALYTICS_PROGRESS,
                {"cohortId": cohort_id, "phase": phase, "done": done, "total": total},
            )
        )


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
    # not persisted as one. `RunScorer` reads it to explain an
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
