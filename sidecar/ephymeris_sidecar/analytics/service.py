"""Analytics orchestration — `DATA.md#reading-the-archive`,
`DATA.md#analytics-views`.

What the four commands actually call. Owns the explicit archive walk; asks
`scoring.RunScorer` for every score, decoded run and cache row.

> **No analytics operation may slow, stall, or fail a session**
> (`DATA.md#never-at-the-expense-of-a-session`). Six
> boxes may be `fsync`ing per strobe while this runs. So: one indexing job at
> a time behind a lock, reads sequential in a single worker thread rather than
> a pool, and one transaction per pass.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..cohorts import relocate
from ..logbook.repository import LogbookRepository
from ..sessions import tidy as session_tidy
from ..sessions.models import SessionAnimalRun
from ..sessions.paths import parse_name_date, parse_name_time, parse_session_folder
from . import derive, false_starts, reader
from .archive import RESCAN_WHILE_WRITING, CohortArchive
from .repository import AdoptedRun, AnalyticsRepository, CachedRun
from .scoring import RunScorer

log = logging.getLogger(__name__)

#: Cap on one `analytics.series` request, so a "select all" click can't ask for
#: a multi-megabyte frame.
MAX_SERIES_RUNS = 24

#: `analytics.recentSessions` default when the caller names no limit.
DEFAULT_RECENT_LIMIT = 6


class AnalyticsService:
    def __init__(
        self,
        db: Any,
        cohorts: Any,
        sessions: Any,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        archive: CohortArchive,
        min_counted: int = derive.DEFAULT_MIN_COUNTED,
        sketch_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._broadcast = broadcast
        self._repo = AnalyticsRepository(db)
        #: Read only for which sessions carry notes — those are never empty
        #: and never pruned (`DATA.md#the-session-log`).
        self._logbook = LogbookRepository(db)
        self._min_counted = min_counted
        #: Resolve a document's `sketch` *name* to a sketch in this install's
        #: library: once when a rescan adopts an orphan, and again by the
        #: scorer each time it reads one (`DATA.md#orphan-adoption`).
        self._sketch_lookup = sketch_lookup
        #: Every score, decoded run and cache row (`DATA.md#caching`).
        self._scorer = RunScorer(self._repo, sketch_lookup)
        #: What every pass reads, and whose lock it runs under: one job at a
        #: time (`DATA.md#the-cohort-archive`).
        self._archive = archive

    # --- summary -----------------------------------------------------------

    async def summary(
        self,
        cohort_id: str,
        *,
        session_ids: list[str] | None = None,
        animal_ids: list[str] | None = None,
        min_counted: int | None = None,
    ) -> dict[str, Any]:
        """The whole cohort table — every panel's data in one call
        (`DATA.md#analytics-views`)."""
        threshold = min_counted if min_counted is not None else self._min_counted
        # The records are read under the lock, not just indexed under it. A
        # relocate, a move or a tidy holds it while it rewrites them, so a read
        # taken before waiting would index what they just changed: the old data
        # folder reported missing and every moved run with it.
        async with self._archive.exclusive(wait=True):
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            view = await asyncio.to_thread(self._archive.view, cohort_id)
            sessions = view.sessions
            if session_ids is not None:
                wanted = set(session_ids)
                sessions = [s for s in sessions if s.id in wanted]

            session_index = {s.id: index for index, s in enumerate(sessions)}
            runs = [r for r in view.runs if r.session_id in session_index]
            if animal_ids is not None:
                wanted_animals = set(animal_ids)
                runs = [r for r in runs if r.animal_id in wanted_animals]

            summaries = await self._scorer.score(
                runs,
                min_counted=threshold,
                progress=lambda done, total: self._progress(
                    cohort_id, "reading", done, total
                ),
            )

        scored = {run.id: entry.summary for run, entry in zip(runs, summaries)}
        # A recovered session's clock closes from its files — each run's start
        # plus its stream's span (`DATA.md#the-session-clock`) — known only once
        # the index has read them, which it just did.
        view.close_clocks(scored)

        # False starts (`DATA.md#false-starts`): judged over the same runs the
        # index just scored, with whatever a person has ruled. Set aside, not
        # dropped — they ride in their own list, so no metric below can count
        # one by forgetting to filter it.
        verdicts = await asyncio.to_thread(self._archive.verdicts, runs, scored)

        counts = {
            "runs": 0, "decoded": 0, "noProfile": 0, "missing": 0, "unreadable": 0,
            "falseStarts": 0,
        }
        warnings: list[dict[str, Any]] = []
        payload_runs: list[dict[str, Any]] = []
        set_aside: list[dict[str, Any]] = []
        hashes: list[str] = []

        for run, entry in zip(runs, summaries):
            verdict = verdicts[run.id]
            if verdict.false_start:
                counts["falseStarts"] += 1
                set_aside.append(self._run_payload(run, entry, verdict))
                continue
            counts["runs"] += 1
            status = entry.status
            if status == "ok":
                counts["decoded"] += 1
            elif status == "no-metrics":
                counts["noProfile"] += 1
            elif status in counts:
                counts[status] += 1
            if status in ("missing", "unreadable"):
                warnings.append(
                    {"code": status, "runId": run.id, "message": entry.detail or status}
                )
            if entry.profile_hash and entry.profile_hash not in hashes:
                hashes.append(entry.profile_hash)
            payload_runs.append(self._run_payload(run, entry, verdict))

        # A cohort pointing at a folder that isn't there returns a perfectly
        # well-formed empty result, which reads as "this cohort has no data"
        # when it means "I can't see where its data is". A removable drive or a
        # machine that letters its volumes differently makes that routine, so
        # say it rather than letting the operator infer it.
        if not await asyncio.to_thread(
            lambda: Path(cohort.data_folder).expanduser().is_dir()
        ):
            warnings.insert(
                0,
                {
                    "code": "data-folder-missing",
                    "runId": "",
                    # Just the fact and the path. The advice is the caller's to
                    # phrase — a CLI and a dashboard would word it differently,
                    # and duplicating it here makes the rendered line stutter.
                    "message": cohort.data_folder,
                },
            )

        meta = await asyncio.to_thread(self._repo.profile_meta, hashes)
        groups = _profile_groups(payload_runs, meta)
        warnings.extend(_parameter_mismatches(payload_runs, meta))

        return {
            "cohortId": cohort_id,
            "dataFolder": cohort.data_folder,
            "sessions": [s.to_list_item(index + 1) for index, s in enumerate(sessions)],
            "animals": _summary_animals(cohort, payload_runs),
            "groups": [{"id": g.id, "name": g.name, "order": g.order} for g in cohort.groups],
            "runs": payload_runs,
            "falseStarts": set_aside,
            "profileGroups": groups,
            "counts": counts,
            "warnings": warnings,
            "minCountedTrials": threshold,
        }

    @staticmethod
    def _run_payload(
        run: SessionAnimalRun, entry: CachedRun, verdict: false_starts.Verdict
    ) -> dict[str, Any]:
        return {
            "runId": run.id,
            "sessionId": run.session_id,
            "animalId": run.animal_id,
            "boxNumber": run.box_number,
            "startedAt": run.started_at,
            "endedAt": run.ended_at,
            "sketchPath": run.sketch_path,
            "sketchName": _program_name(run),
            "profileHash": entry.profile_hash,
            # The row's own record wins; the file's copy answers for a
            # run this machine never recorded
            # (`DATA.md#the-embedded-task-profile`). Comparability is
            # the pair, and an adopted run used to be able to offer only
            # half of it.
            "paramsHash": run.params_hash or entry.params_hash,
            "profileSource": entry.profile_source,
            "stale": entry.stale,
            **verdict.to_json(),
            **entry.summary,
        }

    # --- false starts (DATA.md#false-starts) -------------------------------

    def set_false_start(self, cohort_id: str, run_id: str, value: bool | None) -> None:
        """Rule on one run of this cohort; None hands it back to the rule.

        Refuses a run the cohort does not hold, so a stale page cannot write
        an override nothing will ever read.
        """
        if run_id not in {run.id for run in self._archive.view(cohort_id).runs}:
            raise KeyError(run_id)
        self._repo.set_false_start(run_id, value)

    # --- series ------------------------------------------------------------

    async def series(
        self,
        run_ids: list[str],
        *,
        mode: str = "rolling",
        metric_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Within-session trajectories for the named runs
        (`DATA.md#learning-curves`).

        Not cached: a full archive of series is megabytes of floats inside a
        database that gets copied wholesale to the backup target, for data
        nobody views more than a handful of runs at a time (`DATA.md#caching`).
        """
        if len(run_ids) > MAX_SERIES_RUNS:
            raise ValueError(
                f"at most {MAX_SERIES_RUNS} runs per request; got {len(run_ids)}"
            )
        out: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for run_id in run_ids:
            # One hop per run, and all of the run's work inside it: decoding
            # and scoring up to `MAX_SERIES_RUNS` files is not work for the
            # loop that flushes six boxes' output
            # (`DATA.md#never-at-the-expense-of-a-session`). Sequential, like
            # the summary's reads.
            charted, warning = await asyncio.to_thread(
                self._chart, run_id, mode, metric_ids
            )
            if warning is not None:
                warnings.append(warning)
            else:
                out.append(charted)
        return {"series": out, "warnings": warnings}

    def _chart(
        self, run_id: str, mode: str, metric_ids: list[str] | None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """One run's series, trail and trial tape, or the warning instead.
        Blocking; `series` runs it in a worker thread."""
        run = self._archive.run(run_id)
        if run is None or not run.file_path:
            return None, {"code": "missing", "runId": run_id, "message": "no file"}
        # The same ladder `score` scores with, ending on the same inference
        # rung — a run charted from an inferred profile must draw the same
        # trials the summary counted, or the two panels disagree.
        decoded = self._scorer.decode(run)
        if decoded.document is None:
            return None, {
                "code": decoded.status, "runId": run_id, "message": decoded.detail or "",
            }
        document, profile = decoded.document, decoded.profile
        metrics = derive.series(document, profile, mode=mode, metric_ids=metric_ids)
        # The joint walk rides along with the per-metric series rather than
        # taking a command of its own: the file is already open and already
        # decoded here, and the one panel that wants it is on the same
        # screen as the ones that want the series. It is empty for any
        # profile that doesn't declare exactly two conditions.
        trail = derive.strategy_trail(document, profile)
        # The per-trial tape rides along for the same reason the trail
        # does: the file is already open and decoded, and the panel that
        # wants it is on the same screen as the ones that want the series.
        trials = derive.trials_of(document, profile)
        return {
            "runId": run_id,
            "mode": mode,
            "metrics": [m.to_json() for m in metrics],
            "trail": [p.to_json() for p in trail],
            "trials": [t.to_json() for t in trials],
        }, None

    # --- recent sessions ----------------------------------------------------

    async def recent_sessions(self, limit: int | None = None) -> dict[str, Any]:
        """The N most recent session folders across every active cohort
        (`PROTOCOL.md#cmd-analytics.recentsessions`).

        Folder names only — `reader.walk_session_dirs` never opens a file — so
        this is cheap enough for the Dashboard, where the rescan deliberately
        is not. The point of walking disk rather than the database is the
        `recorded: false` rows: a session another Ephymeris machine wrote into
        the shared archive is real history, but it has no session row here
        until a rescan adopts it, and `sessions.list` would never see it.
        """
        cap = limit if limit is not None and limit > 0 else DEFAULT_RECENT_LIMIT
        cohorts = await asyncio.to_thread(self._cohorts.list_cohorts)
        active = [c for c in cohorts if not c.archived]
        entries = await asyncio.to_thread(self._recent_on_disk, active)
        # Folder names carry a date but no time, so recency is by date with the
        # folder path as a stable (not meaningful) tie-break.
        entries.sort(key=lambda e: (e["date"], e["folderPath"]), reverse=True)
        return {"sessions": entries[:cap]}

    def _recent_on_disk(self, cohorts: list[Any]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for cohort in cohorts:
            # Adopted folders count as recorded too. Adoption deliberately
            # writes no `sessions` row (`DATA.md#database-first`), so without
            # them a folder adopted via rescan reported `recorded: false`
            # forever — and the Dashboard badge told the user to run the rescan
            # they had already run. The archive names a recovered file's folder
            # as the walk yields it (`reader.session_folder_of`), so the two
            # sides agree by construction.
            recorded = {_normalize(folder) for folder in self._archive.folders(cohort.id)}
            for session_dir in reader.walk_session_dirs(cohort.data_folder):
                parsed = parse_session_folder(session_dir.name)
                if parsed.date is None:
                    # A name with no date can't be placed on a recency list;
                    # honest omission beats inventing an order.
                    continue
                found.append(
                    {
                        "cohortId": cohort.id,
                        "cohortName": cohort.name,
                        "prefixName": parsed.prefix,
                        "sessionNumber": parsed.session_number,
                        "date": parsed.date.isoformat(),
                        "folderPath": str(session_dir),
                        "recorded": _normalize(str(session_dir)) in recorded,
                    }
                )
        return found

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
        async with self._archive.write(
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
                # INSERT OR REPLACE on the row's id, so a file whose content
                # changed since adoption refreshes its row in place rather than
                # duplicating it. Counted as written: a row another cohort
                # holds is never taken.
                adopted = await asyncio.to_thread(
                    lambda: self._repo.store_adopted(
                        adoptable, earlier_ids=_earlier_ids(adoptable, held, dropped)
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
        service lock is already held.

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
        async with self._archive.write() as write:
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
        view = self._archive.view(cohort_id, include_aborted=True)
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
        for merge in planned.merges:
            fields = session_tidy.merged_fields(merge)
            self._sessions.absorb_sessions(
                merge.keep.id, [s.id for s in merge.absorb], **fields
            )
            merged_counts[merge.keep.id] = sum(
                counts.get(s.id, 0) for s in (merge.keep, *merge.absorb)
            )
        self._sessions.discard_sessions([e.session.id for e in planned.empty])

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

        await self._broadcast(
            event(
                Evt.ANALYTICS_PROGRESS,
                {"cohortId": cohort_id, "phase": phase, "done": done, "total": total},
            )
        )


def _profile_groups(
    runs: list[dict[str, Any]], meta: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Comparability sets. Two runs share axes only if they share a hash
    (`DATA.md#which-profile-decodes-a-run`)."""
    counts: dict[str, int] = {}
    metrics: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        digest = run.get("profileHash")
        if not digest:
            continue
        counts[digest] = counts.get(digest, 0) + 1
        if digest not in metrics:
            declared = [
                {
                    "id": m["id"],
                    "label": m["label"],
                    "windowSize": m["windowSize"],
                    # Carried up from the run so a panel can work out its axes
                    # from the GROUP, before opening any of its runs.
                    "answerSide": m.get("answerSide"),
                }
                for m in run.get("metrics", [])
            ]
            # Offer the pooled figure alongside the declared ones, first, when
            # there is more than one condition to pool. It is the only single
            # number that can distinguish learning from a side bias.
            overall = run.get("overall")
            if overall and len(declared) > 1:
                declared.insert(
                    0,
                    {
                        "id": overall["id"],
                        "label": overall["label"],
                        "windowSize": 0,
                        # Pooled across every condition, so answered at no one
                        # side and never an axis.
                        "answerSide": None,
                    },
                )
            metrics[digest] = declared
    return [
        {
            "hash": digest,
            "taskName": meta.get(digest, {}).get("taskName"),
            "kind": meta.get(digest, {}).get("kind"),
            "metrics": metrics.get(digest, []),
            "runCount": count,
        }
        for digest, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _parameter_mismatches(
    runs: list[dict[str, Any]], meta: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Warn where one comparability set holds differently-tuned runs
    (`DATA.md#which-profile-decodes-a-run`).

    A profile hash covers the profile *declaration*, which is identical across
    every run of a sketch. Once the timings became operator-set
    (`TASKS.md#three-layer-merge`), that
    stopped being enough to call two runs comparable: a rat run at a 10 ms poke
    hold and one run at 500 ms share a hash and would be plotted on one axis as
    though the task had not changed underneath them.

    A warning rather than a split. Splitting would fragment a cohort's history
    the first time anyone nudged a timeout, and most parameter edits genuinely
    don't invalidate a comparison -- but the reader is the one who can judge
    that, and silence denies them the chance.

    Runs with no recorded parameters are ignored rather than counted
    as a distinct set: they ran on firmware constants, so an unknown is not
    evidence of a difference.
    """
    seen: dict[str, set[str]] = {}
    for run in runs:
        digest = run.get("profileHash")
        params = run.get("paramsHash")
        if digest and params:
            seen.setdefault(digest, set()).add(params)
    return [
        {
            "code": "parameter-mismatch",
            "runId": "",
            "message": (
                f"{meta.get(digest, {}).get('taskName') or digest}: "
                f"{len(variants)} different parameter sets across these runs"
            ),
        }
        for digest, variants in seen.items()
        if len(variants) > 1
    ]


def _is_gone(path: str | None, *, kind: str = "run-file") -> bool:
    """Is this path **reachable and absent** — as opposed to just unreachable?

    This is the whole safety of the prune, and the distinction is not
    cosmetic. `exists() is False` answers two completely different questions
    with one word: *the operator deleted this* and *this volume isn't mounted
    right now*. Acting on the second would let one rescan with a drive
    unplugged erase a cohort's history, which is the exact failure the
    keep-the-last-good-summary rule (`DATA.md#caching`) exists to prevent — so
    it must not be
    reintroduced by the mechanism that finally clears genuinely dead records.

    So absence only counts when the storage is demonstrably there: some
    ancestor of the path must be readable. A deleted tree always leaves one
    (the drive root at worst); an unmounted volume leaves none, not even
    `E:\\` or `//server/share`.

    Three further refusals, each an honest "can't tell" rather than a guess:

    * **No recorded path** — nothing to observe. Reported as `missing` by the
      summary already, with its own distinct reason.
    * **A path that can't be `stat`ed for any reason other than not being
      there** — a permission error is not a deletion.
    * **A `.json` whose write-ahead `.tsv` is still on disk** — that run's data
      is intact and `sessions.recover` will rebuild the document from it
      (`DATA.md#crash-recovery`). Pruning it would throw away the `animal_id`,
      `profile_hash` and `config_json` that make the recovered file worth more
      than the orphan adoption could ever reconstruct from a filename.
    """
    if not path:
        return False
    target = Path(path).expanduser()
    try:
        target.stat()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    else:
        # Something is there. Whether it is the *kind* of thing expected is a
        # different question and not this one's business: a session folder
        # replaced by a file is a broken archive, not a deletion.
        return False

    if kind == "run-file":
        try:
            if reader.sibling_tsv(target).is_file():
                return False
        except OSError:  # pragma: no cover - unreadable mount
            return False

    return _storage_is_reachable(target)


def _storage_is_reachable(target: Path) -> bool:
    """Can we see *any* of the path's ancestry? Bottom-up, so a deleted leaf
    costs one stat and an unmounted volume costs the depth of the path."""
    for ancestor in target.parents:
        try:
            if ancestor.is_dir():
                return True
        except OSError:  # pragma: no cover - unreadable mount
            return False
    return False


def _same_path(recorded: str, found: Path) -> bool:
    return _normalize(recorded) == _normalize(str(found))


def _folder_state(path: str) -> bool | None:
    """True if the folder holds any file, False if it demonstrably holds none
    (or is gone), None if it cannot be seen — never read as empty
    (`DATA.md#tidy-records`)."""
    if not path:
        return None
    target = Path(path).expanduser()
    try:
        if target.is_dir():
            return any(child.is_file() for child in target.rglob("*"))
    except OSError:
        return None
    return False if _is_gone(path, kind="folder") else None


def _remove_empty_tree(path: str) -> None:
    """Remove a session folder that contains no file — directories only.

    Bottom-up `rmdir`, which the OS refuses for anything non-empty, so a file
    that appeared since the plan (or a check that was wrong) stops it cold
    rather than being deleted. Never `rmtree`: the app deletes its own
    records, never the user's data (`DATA.md#archive-and-delete`).
    """
    import os

    root = Path(path).expanduser()
    if not root.is_dir():
        return
    try:
        for current, _dirs, files in os.walk(root, topdown=False):
            if files:
                return
            os.rmdir(current)
    except OSError as exc:
        log.info("tidy: left folder %s in place (%s)", path, exc)


def _normalize(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve()).casefold()
    except OSError:  # pragma: no cover
        return path.casefold()


def _program_name(run: SessionAnimalRun) -> str:
    """What this run says it ran, as opposed to what this machine can find.

    `sketch_path` answers a different question — *where a `task.json` was
    resolved* — and it is legitimately empty for a file recorded on another
    rig: the archive walk adopts the file, the name lookup finds no sketch by
    that name in this install's library, and the run scores by inference
    (`DATA.md#which-profile-decodes-a-run`)
    with nothing left to name it. Read off the path alone, every such run
    displays as "unknown", which reads as *the record is silent* when in fact
    the file says exactly what it ran.

    The name the document recorded therefore wins, and the path is only the
    fallback for a run whose record predates carrying one. Split on both
    separators deliberately: a path written on Windows is read on macOS and
    vice versa, and `PurePath` on one platform does not split the other's.
    """
    recorded = getattr(run, "sketch_name", None)
    if recorded:
        return recorded
    return (run.sketch_path or "").replace("\\", "/").rstrip("/").rpartition("/")[2]


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


# --- adopted orphans (DATA.md#orphan-adoption) -----------------------------


def _prefer(candidate: AdoptedRun, incumbent: AdoptedRun) -> bool:
    """Which copy of the same run to keep.

    Richer wins: a copy whose document names its sketch can be decoded, and one
    that doesn't cannot. The real Remy archive has exactly this asymmetry — 30
    runs where only the consolidated copy carries `sketch` — so "first one
    found" would have thrown away the only usable version. Ties break on path
    so a rescan is deterministic rather than dependent on walk order.

    Judged only on what the *document* says, never on whether that sketch
    currently resolves to a directory entry: resolution depends on settings
    that change between scans, so letting it decide would make the winner —
    and with it the run's recorded file path — flip back and forth for reasons
    that have nothing to do with the data.
    """
    if bool(candidate.sketch_name) != bool(incumbent.sketch_name):
        return bool(candidate.sketch_name)
    return candidate.file_path < incumbent.file_path


def _summary_animals(cohort: Any, payload_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The roster, then every former member whose runs are in this summary
    (`DATA.md#former-members`).

    Appended rather than interleaved: colours are assigned by position, and an
    animal taken off the roster must not shift the colour of every animal after
    it. A former member with no run here is left out — the rail would offer a
    row with nothing behind it.
    """
    animals = [
        {
            "id": a.id,
            "name": a.name,
            "groupId": a.group_id,
            "boxNumber": a.box_number,
            "cage": a.cage,
            "former": False,
        }
        for a in cohort.animals
    ]
    ran = {run["animalId"] for run in payload_runs}
    for former in cohort.former_animals:
        if former.id not in ran:
            continue
        animals.append(
            {
                "id": former.id,
                # A note-only id has no files to name it; the short id at least
                # tells two such animals apart.
                "name": former.name or f"Unknown animal {former.id[:6]}",
                "groupId": "",
                "boxNumber": None,
                "cage": former.cage,
                "former": True,
            }
        )
    return animals


def _adoptable_animals(cohort: Any) -> list[Any]:
    """Who a stray file may be matched to: the roster, then the cohort's
    stored former members (`DATA.md#former-members`).

    A file written while an animal was on the roster is still that animal's
    after it comes off. But never a former member whose name an active animal
    now holds — the file is a name, and that name means the animal on the
    roster. Ids derived from files alone (`source == "files"`) are never
    candidates: their name is itself a reading of the files.
    """
    active = {a.name.casefold() for a in cohort.animals}
    former = [
        f
        for f in getattr(cohort, "former_animals", [])
        if f.source == "removed" and f.name and f.name.casefold() not in active
    ]
    return [*cohort.animals, *former]


def _animal_from_filename(
    path: Path, session_folder: Path, animals: list[Any]
) -> str | None:
    """The animal a file *names*, when the document it holds got it wrong.

    Real archives carry typos. One file in this lab's Squeekstreet archive
    records `rat: "HmM103"` while its filename says `HM103_…` — and without a
    second opinion that run vanishes from HM103's history, which reads like the
    animal didn't run that day rather than like a mistyped field. A hole that
    looks like data is the worst of the available failures.

    This is not the guessing `DATA.md#orphan-adoption` rules out. The
    filename and the `rat` field
    are two independent recordings of the same fact by the same program at the
    same moment, and the stem has to be *exactly* what `DATA.md#names`
    prescribes — `<animal>_<the session folder this file is actually sitting
    in>_<HHMMSS>` — checked against the folder on disk rather than assumed. A
    file that doesn't follow the convention contributes nothing. The token that
    survives all that must still match a roster name exactly, case-folded, the
    same test the document's field had to pass.
    """
    token = reader.animal_token(path, session_folder)
    if token is None:
        return None
    folded = token.casefold()
    return next((a.id for a in animals if a.name.casefold() == folded), None)


def _orphan_run_id(cohort_id: str, path: Path) -> str:
    """The id a new adoption is stored under (`DATA.md#orphan-adoption`).

    Keyed on the **cohort and the run identity** (the file stem), never the
    path. A duplicated run has two paths, and which copy `_prefer` picks can
    legitimately change between scans — when a sketch reappears in the
    library, say, and one copy suddenly resolves a profile. A path-keyed id
    would then mint a *second* row for a run that already had one, leaving
    both in place: precisely the double-counting the deduplication exists to
    prevent. And two cohorts whose folders overlap find the *same* path, so
    only the cohort in the key keeps their rows apart.

    Only for a run the cohort does not hold yet. A held row keeps the id it
    was stored under, whatever this returns for it now: a person's ruling
    (`run_flags`) and the cached scores are keyed by that id.
    """
    key = f"{cohort_id}\0{reader.run_identity(path)}"
    return f"adopted:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def _stem_only_run_id(path: Path) -> str:
    """The stem-only id: the run identity alone, with no cohort.

    A row held under its stem-only id keeps it (`_orphan_run_id`), so it is
    the key of any ruling a person made on that run. When such a row is pruned
    and its run adopted afresh, the ruling moves to the new id (`_earlier_ids`,
    `DATA.md#false-starts`).
    """
    digest = hashlib.sha1(reader.run_identity(path).encode("utf-8")).hexdigest()
    return f"adopted:{digest[:16]}"


def _earlier_ids(
    adoptable: list[AdoptedRun], held: dict[str, str], dropped: dict[str, str]
) -> dict[str, list[str]]:
    """The ids a ruling on each freshly adopted run may still sit on
    (`DATA.md#false-starts`), for `store_adopted` to move it from.

    Only for a run the cohort did not hold: a row read again keeps its own id
    and its own ruling, and never takes one another cohort's pruned row left.
    First the id of a row this rescan's prune just dropped for the same run,
    which a move kept from the cohort that first adopted it; then the
    stem-only id.
    """
    out: dict[str, list[str]] = {}
    for entry in adoptable:
        identity = reader.run_identity(Path(entry.file_path))
        if held.get(identity) is not None:
            continue
        candidates = [dropped[identity]] if identity in dropped else []
        out[entry.id] = [*candidates, _stem_only_run_id(Path(entry.file_path))]
    return out
