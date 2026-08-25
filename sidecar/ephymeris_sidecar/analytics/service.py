"""Analytics orchestration — `data.md` §8, §9.

What the four commands actually call. Owns the indexing lock, the profile
resolution ladder, the cache, and the explicit archive walk.

> **No analytics operation may slow, stall, or fail a session** (§8.4). Six
> boxes may be `fsync`ing per strobe while this runs. So: one indexing job at
> a time behind a lock, reads sequential in a single worker thread rather than
> a pool, and one transaction per pass.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..sessions.models import Session, SessionAnimalRun
from ..sessions.paths import parse_name_date, parse_name_time, parse_session_folder
from ..tasks import profile as task_profile
from ..tasks.profile import TaskProfile
from . import derive, infer, reader
from .repository import AdoptedRun, AnalyticsRepository, CachedRun, CacheKey

log = logging.getLogger(__name__)

#: Emit progress every N files rather than per file — same publishing
#: discipline as `backup.status`.
PROGRESS_EVERY = 10

#: Cap on one `analytics.series` request, so a "select all" click can't ask for
#: a multi-megabyte frame.
MAX_SERIES_RUNS = 24

#: Runs handed to the worker thread per hop. Also the granularity at which the
#: event loop gets to breathe between batches, so it is kept small enough that
#: a chunk of cache misses can't stall a live `port.output` batch.
INDEX_CHUNK = 32

#: `analytics.recentSessions` default when the caller names no limit.
DEFAULT_RECENT_LIMIT = 6


class AnalyticsBusy(Exception):
    """An indexing job is already running for this cohort."""


@dataclass
class _Resolved:
    """A profile plus how much it can be trusted (§8.2)."""

    profile: TaskProfile | None
    source: str  # 'snapshot' | 'sketch-current' | 'unavailable'
    digest: str | None
    #: Why there is no profile, when there isn't one. Without this an
    #: unresolvable sketch name is indistinguishable from a genuinely
    #: profile-less sketch, and the operator has nothing to act on.
    reason: str | None = None


#: One indexing pass's resolved profiles, keyed on what a run asks for
#: (snapshot hash, recorded sketch path, sketch name) and holding what that
#: question resolved to, plus the sketch path it landed on.
_ProfileMemo = dict[tuple[str, str, str], tuple[_Resolved, str]]


class AnalyticsService:
    def __init__(
        self,
        db: Any,
        cohorts: Any,
        sessions: Any,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        min_counted: int = derive.DEFAULT_MIN_COUNTED,
        sketch_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._broadcast = broadcast
        self._repo = AnalyticsRepository(db)
        self._min_counted = min_counted
        #: Resolve a document's `sketch` *name* to a current Arduino Directory
        #: path, for adopted orphans whose run record never existed (§8.1). The
        #: honest analog of the §8.2 `sketch-current` fallback — and exactly as
        #: trustworthy, which is to say: marked as such, never as a snapshot.
        self._sketch_lookup = sketch_lookup
        # One job at a time: `server.py` runs every command as its own task, so
        # two summary calls really can arrive together.
        self._lock = asyncio.Lock()

    # --- summary -----------------------------------------------------------

    async def summary(
        self,
        cohort_id: str,
        *,
        session_ids: list[str] | None = None,
        animal_ids: list[str] | None = None,
        min_counted: int | None = None,
    ) -> dict[str, Any]:
        """The whole cohort table — every panel's data in one call (§9)."""
        threshold = min_counted if min_counted is not None else self._min_counted
        cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
        sessions = await asyncio.to_thread(self._sessions.list_sessions, cohort_id)

        # Adopted orphans (§8.1) ride alongside recorded runs: payload-only
        # synthetic sessions grouped from folder names, never database rows.
        adopted = await asyncio.to_thread(self._repo.adopted_for_cohort, cohort_id)
        synthetic, _ = _synthetic_sessions(adopted, cohort_id)
        sessions = _merge_sessions(sessions, synthetic)
        if session_ids is not None:
            wanted = set(session_ids)
            sessions = [s for s in sessions if s.id in wanted]

        runs = await asyncio.to_thread(self._sessions.runs_for_cohort, cohort_id)
        runs = runs + [_adopted_to_run(a) for a in adopted]
        session_index = {s.id: index for index, s in enumerate(sessions)}
        runs = [r for r in runs if r.session_id in session_index]
        if animal_ids is not None:
            wanted_animals = set(animal_ids)
            runs = [r for r in runs if r.animal_id in wanted_animals]

        async with self._lock:
            summaries = await self._index(runs, threshold, cohort_id)

        counts = {"runs": len(runs), "decoded": 0, "noProfile": 0, "missing": 0, "unreadable": 0}
        warnings: list[dict[str, Any]] = []
        payload_runs: list[dict[str, Any]] = []
        hashes: list[str] = []

        for run, entry in zip(runs, summaries):
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
            payload_runs.append(
                {
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
                    # run this machine never recorded (§4.4). Comparability is
                    # the pair, and an adopted run used to be able to offer only
                    # half of it.
                    "paramsHash": run.params_hash or entry.params_hash,
                    "profileSource": entry.profile_source,
                    "stale": entry.stale,
                    **entry.summary,
                }
            )

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
            "animals": [
                {
                    "id": a.id,
                    "name": a.name,
                    "groupId": a.group_id,
                    "boxNumber": a.box_number,
                    "cage": a.cage,
                }
                for a in cohort.animals
            ],
            "groups": [{"id": g.id, "name": g.name, "order": g.order} for g in cohort.groups],
            "runs": payload_runs,
            "profileGroups": groups,
            "counts": counts,
            "warnings": warnings,
            "minCountedTrials": threshold,
        }

    # --- series ------------------------------------------------------------

    async def series(
        self,
        run_ids: list[str],
        *,
        mode: str = "rolling",
        metric_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Within-session trajectories for the named runs (§5).

        Not cached: a full archive of series is megabytes of floats inside a
        database that gets copied wholesale to the backup target, for data
        nobody views more than a handful of runs at a time (§8.3).
        """
        if len(run_ids) > MAX_SERIES_RUNS:
            raise ValueError(
                f"at most {MAX_SERIES_RUNS} runs per request; got {len(run_ids)}"
            )
        out: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for run_id in run_ids:
            run = await asyncio.to_thread(self._run_by_id, run_id)
            if run is None:
                # Adopted orphans have no session_animal_runs row by design.
                entry = await asyncio.to_thread(self._repo.adopted_by_id, run_id)
                if entry is not None:
                    run = _adopted_to_run(entry)
            if run is None or not run.file_path:
                warnings.append({"code": "missing", "runId": run_id, "message": "no file"})
                continue
            result = await asyncio.to_thread(reader.read_run, run.file_path)
            if not result.ok or result.document is None:
                warnings.append(
                    {"code": result.status, "runId": run_id, "message": result.detail or ""}
                )
                continue
            resolved = await asyncio.to_thread(self._resolve_profile, run)
            # The same ladder `_index_one` scores with, ending on the same
            # inference rung — a run charted from an inferred profile must draw
            # the same trials the summary counted, or the two panels disagree.
            profile, _, _ = self._scoring_profile(resolved, result.document, persist=False)
            metrics = derive.series(
                result.document, profile, mode=mode, metric_ids=metric_ids
            )
            # The joint walk rides along with the per-metric series rather than
            # taking a command of its own: the file is already open and already
            # decoded here, and the one panel that wants it is on the same
            # screen as the ones that want the series. It is empty for any
            # profile that doesn't declare exactly two conditions.
            trail = derive.strategy_trail(result.document, profile)
            # The per-trial tape rides along for the same reason the trail
            # does: the file is already open and decoded, and the panel that
            # wants it is on the same screen as the ones that want the series.
            trials = derive.trials_of(result.document, profile)
            out.append(
                {
                    "runId": run_id,
                    "mode": mode,
                    "metrics": [m.to_json() for m in metrics],
                    "trail": [p.to_json() for p in trail],
                    "trials": [t.to_json() for t in trials],
                }
            )
        return {"series": out, "warnings": warnings}

    # --- recent sessions ----------------------------------------------------

    async def recent_sessions(self, limit: int | None = None) -> dict[str, Any]:
        """The N most recent session folders across every active cohort (§9).

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
            recorded = {
                _normalize(s.folder_path)
                for s in self._sessions.list_sessions(cohort.id, include_aborted=True)
                if s.folder_path
            }
            # Adopted folders are indexed too. Adoption deliberately writes no
            # `sessions` row (§8.1), so without this a folder adopted via
            # rescan reported `recorded: false` forever — and the Dashboard
            # badge told the user to run the rescan they had already run. The
            # synthetic sessions carry the same folder the walk yields
            # (`reader.session_folder_of`), so the two sides agree by
            # construction. One indexed read per cohort (`idx_adopted_cohort`)
            # keeps this Dashboard-cheap.
            synthetic, _ = _synthetic_sessions(
                self._repo.adopted_for_cohort(cohort.id), cohort.id
            )
            recorded |= {
                _normalize(s.folder_path) for s in synthetic if s.folder_path
            }
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
        """Reconcile a cohort's records against its archive, both ways (§8.1, §8.6).

        The database-first path covers everything this app recorded. The walk
        covers what it didn't: runs finalized with no active session, a crash
        between the file write and the commit, and files restored from the
        backup mirror or copied from the other lab machine.

        And the **prune** covers the other direction, which nothing else in the
        app does: records whose files the disk no longer has. A deleted session
        leaves its rows behind forever otherwise, and §8.3's deliberate "a
        missing file keeps its last good summary" rule then keeps charting it —
        correct for an unplugged drive, wrong for a session the operator threw
        away. Rescan is where that gets resolved because it is the one moment
        the operator has explicitly said *the disk is the truth now*.
        """
        if self._lock.locked():
            raise AnalyticsBusy("an analytics scan is already running")

        async with self._lock:
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            folder_exists = await asyncio.to_thread(
                lambda: Path(cohort.data_folder).expanduser().is_dir()
            )
            # Prune before the walk, so `known` is built from surviving records
            # and a run whose file *moved* is re-adopted in the same pass
            # rather than pruned on one scan and re-found on the next.
            pruned = (
                await asyncio.to_thread(self._prune, cohort_id)
                if adopt_orphans and folder_exists
                else {"runs": 0, "sessions": 0, "adopted": 0}
            )
            runs = await asyncio.to_thread(self._sessions.runs_for_cohort, cohort_id)
            known = {
                _normalize(r.file_path) for r in runs if r.file_path
            }
            await self._progress(cohort_id, "walking", 0, 0)
            found = await asyncio.to_thread(reader.walk_session_files, cohort.data_folder)

            # Which of those files this cohort has already adopted, unchanged
            # since (§8.7). One thread hop and one stat per file, against a walk
            # that would otherwise open and parse every one of them again.
            carried = (
                await asyncio.to_thread(self._carry_over, found, known, cohort_id)
                if adopt_orphans
                else {}
            )

            orphans: list[dict[str, Any]] = []
            # Keyed by run identity, not path: a hand-managed archive often
            # holds a consolidated copy of every session beside the per-prefix
            # originals, and adopting both would silently double every animal
            # in the heatmap and put two points per session on every curve.
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
                    self._describe_orphan, path, cohort, cohort_id
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
            # commit marks the whole database dirty for backup (§7.3), so
            # rewriting an archive's worth of rows per click is a whole-file
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
                # INSERT OR REPLACE on the deterministic id, so a file whose
                # content changed since adoption refreshes its row in place
                # rather than duplicating it.
                await asyncio.to_thread(self._repo.store_adopted, adoptable)
                adopted = len(adoptable)
            if carried:
                log.info(
                    "analytics: rescan of cohort %s reused %d already-adopted"
                    " files and read %d",
                    cohort_id,
                    len(carried),
                    len(found) - len(carried),
                )

            await self._progress(cohort_id, "walking", len(found), len(found))

        return {
            "scanned": len(found),
            "adopted": adopted,
            "pruned": pruned,
            "duplicates": duplicates,
            "orphans": orphans,
            "cohortId": cohort_id,
            "dataFolder": cohort.data_folder,
            "folderMissing": not folder_exists,
        }

    # --- pruning (§8.6) ----------------------------------------------------

    def _prune(self, cohort_id: str) -> dict[str, int]:
        """Drop records for files the disk demonstrably no longer has.

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
        # (§8.1) decides it: the record wins and the adoption goes.
        claimed = {
            _normalize(run.file_path)
            for run in self._sessions.runs_for_cohort(cohort_id)
            if run.file_path
        }
        removed_adopted = [
            entry.id
            for entry in self._repo.adopted_for_cohort(cohort_id)
            if _is_gone(entry.file_path) or _normalize(entry.file_path) in claimed
        ]

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
        surviving = self._sessions.run_counts_by_session(cohort_id)
        doomed = [
            session.id
            for session in self._sessions.list_sessions(cohort_id, include_aborted=True)
            if not surviving.get(session.id)
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
        }

    # --- carrying adoptions forward (§8.7) ---------------------------------

    def _carry_over(
        self, found: list[Path], known: set[str], cohort_id: str
    ) -> dict[str, AdoptedRun]:
        """The adoptions this walk does not need to redo, by run identity.

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
           the same freshness key `run_metrics_cache` uses (§8.4), and the
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
        return out

    def _describe_orphan(
        self, path: Path, cohort: Any, cohort_id: str
    ) -> tuple[dict[str, Any], AdoptedRun | None]:
        """Match a stray file to an animal by name, and never guess (§8.1).

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
        if rat:
            folded = rat.casefold()
            match = next(
                (a.id for a in cohort.animals if a.name.casefold() == folded), None
            )
            if match is not None:
                source = "document"
        if match is None:
            # The document's field is not the only place this run recorded its
            # animal — the filename did too, in the same breath.
            match = _animal_from_filename(path, session_folder, cohort.animals)
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
            id=_orphan_run_id(path),
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
            # is what lets the next rescan skip the file entirely (§8.7).
            file_mtime_ns=result.mtime_ns,
            file_size=result.size,
        )

    # --- indexing ----------------------------------------------------------

    async def _index(
        self, runs: list[SessionAnimalRun], threshold: int, cohort_id: str
    ) -> list[CachedRun]:
        """Resolve, read, and score every run — cache hits skipped.

        Reads are sequential in a worker thread, not a pool: the live `.tsv`
        write path is the priority and a pool would multiply disk contention
        against it (§8.4).
        """
        cached = await asyncio.to_thread(self._repo.load_cached, [r.id for r in runs])
        out: list[CachedRun] = []
        fresh: list[CachedRun] = []
        total = len(runs)
        memo: _ProfileMemo = {}

        await self._progress(cohort_id, "reading", 0, total)
        emitted = 0
        for start in range(0, total, INDEX_CHUNK):
            chunk = runs[start : start + INDEX_CHUNK]
            entries = await asyncio.to_thread(
                self._index_chunk, chunk, cached, threshold, memo
            )
            for run, entry in zip(chunk, entries):
                out.append(entry)
                if cached.get(run.id) is not entry:
                    fresh.append(entry)
            done = start + len(chunk)
            if done - emitted >= PROGRESS_EVERY:
                emitted = done
                await self._progress(cohort_id, "reading", done, total)

        if fresh:
            await asyncio.to_thread(self._repo.store, fresh)
        else:
            # An all-cache-hit pass still resolved profiles, which may have
            # remembered blobs that nothing else is going to commit.
            await asyncio.to_thread(self._repo.flush)
        await self._progress(cohort_id, "reading", total, total)
        log.info(
            "analytics: indexed %d runs for cohort %s (%d recomputed)",
            total,
            cohort_id,
            len(fresh),
        )
        return out

    def _index_chunk(
        self,
        runs: list[SessionAnimalRun],
        cached: dict[str, CachedRun],
        threshold: int,
        memo: _ProfileMemo,
    ) -> list[CachedRun]:
        """One worker-thread hop's worth of runs.

        Chunking does not add concurrency — the runs inside a chunk are still
        read one after another on one thread, and the whole pass is still
        behind the service lock (§8.4). It only stops the loop paying a thread
        hop per run, which at archive scale costs more than the reads do once
        the cache is warm.
        """
        return [self._index_one(r, cached.get(r.id), threshold, memo) for r in runs]

    def _index_one(
        self,
        run: SessionAnimalRun,
        cached: CachedRun | None,
        threshold: int,
        memo: _ProfileMemo | None = None,
    ) -> CachedRun:
        resolved = self._resolve_profile(run, memo)

        if not run.file_path:
            return CachedRun(
                run_id=run.id,
                status="missing",
                detail="no file was recorded for this run",
                profile_hash=resolved.digest,
                profile_source=resolved.source,
                params_hash=None,
                summary=derive.RunSummary(status="missing").to_json(),
                key=CacheKey("", None, None, resolved.digest, derive.CODEC_VERSION),
            )

        # Stat, not read. The cache key is answerable from the stat alone, so a
        # hit costs one syscall and opens nothing — which is the difference
        # between a warm dashboard open reading a whole archive off a network
        # share and reading none of it (§8.3).
        stat = reader.stat_run(run.file_path)

        if stat.status == "missing":
            # Keep the last good summary rather than dropping it — a briefly
            # unreachable share must not erase history from the heatmap (§8.3).
            # This stays *before* the key comparison: a vanished file has no
            # stat to build a key from.
            if cached is not None and cached.status == "ok":
                return CachedRun(**{**cached.__dict__, "stale": True})
            return CachedRun(
                run_id=run.id,
                status="missing",
                detail=stat.detail,
                profile_hash=resolved.digest,
                profile_source=resolved.source,
                params_hash=None,
                summary=derive.RunSummary(status="missing", detail=stat.detail).to_json(),
                key=CacheKey(run.file_path, None, None, resolved.digest, derive.CODEC_VERSION),
            )

        key = CacheKey(
            file_path=run.file_path,
            mtime_ns=stat.mtime_ns,
            size=stat.size,
            profile_hash=resolved.digest,
            codec_version=derive.CODEC_VERSION,
        )
        if cached is not None and cached.key == key:
            return cached

        result = (
            reader.parse_run(run.file_path, stat)
            if stat.ok
            else reader.ReadResult(status=stat.status, detail=stat.detail)
        )

        if result.status == "unreadable" or result.document is None:
            # Cache the negative result too, so a corrupt file isn't re-parsed
            # on every dashboard open.
            return CachedRun(
                run_id=run.id,
                status="unreadable",
                detail=result.detail,
                profile_hash=resolved.digest,
                profile_source=resolved.source,
                params_hash=None,
                summary=derive.RunSummary(
                    status="unreadable", detail=result.detail
                ).to_json(),
                key=key,
            )

        profile, source, digest = self._scoring_profile(resolved, result.document)
        summary = derive.summarize(result.document, profile, min_counted=threshold)
        payload = summary.to_json()
        detail = summary.detail
        if summary.status == "no-metrics" and not detail and resolved.reason:
            # A run that scored nothing is the one case where the operator most
            # needs to know *why* — "no metrics" alone is indistinguishable
            # from a genuinely profile-less sketch and offers nothing to fix.
            detail = resolved.reason
            payload["detail"] = detail
        return CachedRun(
            run_id=run.id,
            status=summary.status,
            detail=detail,
            profile_hash=digest,
            profile_source=source,
            # What the FILE says it ran on. Only ever read for a run this
            # database has no row for (§4.4) — the row's own `params_hash` wins
            # where there is one — so this costs a dictionary comprehension on
            # the runs that would otherwise report no parameters at all.
            params_hash=task_profile.params_hash(
                task_profile.recorded_config(result.document, profile)
            ),
            summary=payload,
            key=key,
        )

    def _scoring_profile(
        self,
        resolved: _Resolved,
        document: dict[str, Any],
        *,
        persist: bool = True,
    ) -> tuple[TaskProfile | None, str, str | None]:
        """The profile a run is actually scored with — the ladder's last rungs.

        Two of the four rungs need the document and therefore live here rather
        than in `_resolve_profile`, which deliberately runs before any file is
        opened:

        1. the database snapshot, resolved already — the profile this rig
           recorded the run with;
        2. **the file's own snapshot** (§4.4), which is the same claim made by
           the file instead of by this machine's database, and is what lets a
           session recorded on another rig decode exactly as it does at home;
        3. today's `task.json` at the recorded sketch path — resolved already,
           and only as trustworthy as that sounds;
        4. the profile **inferred from the stream itself** (`infer.py`), which
           every run of this firmware lineage supports because the strobe
           registry is append-only.

        **The file's snapshot outranks the live `task.json`, and that ordering
        is the point.** Both are "a declaration for this sketch"; only one of
        them is the declaration this run actually used. Ranking them the other
        way would mean a rig that happens to have a same-named task scores a
        visiting file against its own edit of it — silently, and with a
        `profileHash` that says the two runs are comparable.

        Both the embedded and the inferred profile are remembered
        content-addressed like any other, so profile *groups* work unchanged.
        `persist=False` for the read-only `series` path, which must not leave
        an uncommitted insert behind the summary pass's batching.

        The cache key deliberately keeps the *resolution* digest (None when
        nothing resolved), not the digest reached here: both of these rungs are
        functions of the file's content, which the key already covers via
        mtime/size, and of `CODEC_VERSION`, which gates the definition of
        scoring itself.
        """
        if (
            resolved.source == "snapshot"
            and resolved.profile is not None
            and resolved.profile.live_metrics
        ):
            return resolved.profile, resolved.source, resolved.digest

        embedded = task_profile.embedded_profile(document)
        if embedded is not None and embedded.live_metrics:
            # Reported as a snapshot because that is what it is — the profile
            # the run was configured from, recorded at the time of the run. It
            # arrived by a different road than the database's copy; when both
            # exist they are the same bytes and the cheaper road is taken above.
            digest = self._repo.remember_profile(embedded) if persist else None
            return embedded, "snapshot", digest

        if resolved.profile is not None and resolved.profile.live_metrics:
            return resolved.profile, resolved.source, resolved.digest
        sketch = document.get("sketch")
        inferred = infer.infer_profile(
            derive.codes_of(document),
            sketch_name=sketch if isinstance(sketch, str) and sketch else None,
        )
        if inferred is None:
            return resolved.profile, resolved.source, resolved.digest
        digest = self._repo.remember_profile(inferred) if persist else None
        return inferred, "inferred", digest

    def adopted_session_entries(
        self, cohort_id: str
    ) -> tuple[list[Session], dict[str, int]]:
        """Synthetic session entries for a cohort's adopted orphans, plus a
        per-session run count. Reads the database only — `sessions.list`
        merges these and must never touch the filesystem (§9)."""
        adopted = self._repo.adopted_for_cohort(cohort_id)
        return _synthetic_sessions(adopted, cohort_id)

    def _resolve_profile(
        self,
        run: SessionAnimalRun,
        memo: _ProfileMemo | None = None,
    ) -> _Resolved:
        """Snapshot, then today's `task.json`, then nothing (§8.2).

        Three states, not two: the fallback itself can fail, because the
        recorded `sketch_path` may have been renamed, moved, or the Arduino
        Directory re-pointed since the run.

        `memo` collapses the repeated work of one indexing pass — a whole
        archive is usually one or two sketches, and without it every run pays
        its own `task.json` read, sha256, and `INSERT OR IGNORE`.

        **It is scoped to the pass and must stay that way.** Resolution happens
        at read time on purpose (§8.1): a corrected Arduino Directory, or an
        edited `task.json`, takes effect on the very next summary. A memo that
        outlived the pass would freeze exactly what that rule exists to keep
        thawed. Promoting this to a field would look like an obvious win and
        would be a regression.
        """
        key = (
            run.profile_hash or "",
            run.sketch_path or "",
            getattr(run, "sketch_name", None) or "",
        )
        if memo is not None and key in memo:
            resolved, sketch_path = memo[key]
            # Replay the path the first run of this key resolved to. It is not
            # bookkeeping: `summary` reports `sketchPath` per run (§9), so
            # skipping this would leave one run of a group naming its sketch
            # and the rest naming nothing.
            run.sketch_path = sketch_path
            return resolved

        resolved = self._resolve_profile_uncached(run)
        if memo is not None:
            memo[key] = (resolved, run.sketch_path)
        return resolved

    # NOTE: this resolves the *declared* rungs only. The inference rung lives
    # in `_scoring_profile`, after the file is read — it needs the codes, and
    # resolution deliberately runs before any file is opened.
    def _resolve_profile_uncached(self, run: SessionAnimalRun) -> _Resolved:
        if run.profile_hash:
            stored = self._repo.load_profile(run.profile_hash)
            if stored is not None:
                return _Resolved(stored, "snapshot", run.profile_hash)

        named = getattr(run, "sketch_name", None)
        if not run.sketch_path and named and self._sketch_lookup is not None:
            # Resolve against the Arduino Directory *now* rather than trusting
            # what adoption recorded. A run adopted while the directory was
            # unset or unreachable would otherwise stay permanently
            # undecodable, needing a second rescan to un-stick — and the
            # recorded path is only ever a cache of this same lookup.
            run.sketch_path = self._sketch_lookup(named) or ""

        if not run.sketch_path:
            # An adopted orphan whose sketch name matched nothing in the
            # current Arduino Directory has no task.json to fall back to. Name
            # the sketch it wanted: that is the one thing the operator can act
            # on, by renaming a folder or re-pointing the directory.
            # Only surfaced when inference ALSO found nothing in the stream —
            # a run this reason reaches carries no recognisable condition at
            # all, so the sketch name is still the one actionable fact.
            reason = (
                f"this run names the sketch “{named}”, which doesn't match any "
                "sketch in the bundled library, and its stream presents no "
                "recognisable condition to infer from"
                if named
                else "no sketch was recorded for this run, and its stream "
                "presents no recognisable condition to infer from"
            )
            return _Resolved(None, "unavailable", None, reason)

        try:
            current = task_profile.load_profile(run.sketch_path)
        except task_profile.TaskProfileError as exc:
            log.debug("run %s: task.json is malformed: %s", run.id, exc)
            return _Resolved(
                None, "unavailable", None, f"the sketch's task.json is malformed: {exc}"
            )

        if current is None:
            # No task.json at all: either a genuinely profile-less sketch or a
            # path that no longer resolves. Both decode to "no metrics", and
            # the distinction isn't recoverable from here.
            return _Resolved(
                None,
                "unavailable",
                None,
                "no task.json was found beside this run's sketch",
            )
        # Store the blob even though this is only a fallback decode. Content-
        # addressed and commit-free, so it costs nothing after the first run —
        # and without it a profile group has no `taskName` to label itself
        # with, which is every group in an archive that predates snapshots.
        # This does **not** promote the run to `snapshot`: how much the
        # decoding can be trusted is `source`, and it stays `sketch-current`.
        digest = self._repo.remember_profile(current)
        return _Resolved(current, "sketch-current", digest)

    def _run_by_id(self, run_id: str) -> SessionAnimalRun | None:
        with self._db.lock:
            row = self._db.conn.execute(
                "SELECT * FROM session_animal_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        from ..sessions.repository import _hydrate_run

        return _hydrate_run(row)

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
    """Comparability sets. Two runs share axes only if they share a hash (§4.3)."""
    counts: dict[str, int] = {}
    metrics: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        digest = run.get("profileHash")
        if not digest:
            continue
        counts[digest] = counts.get(digest, 0) + 1
        if digest not in metrics:
            declared = [
                {"id": m["id"], "label": m["label"], "windowSize": m["windowSize"]}
                for m in run.get("metrics", [])
            ]
            # Offer the pooled figure alongside the declared ones, first, when
            # there is more than one condition to pool. It is the only single
            # number that can distinguish learning from a side bias.
            overall = run.get("overall")
            if overall and len(declared) > 1:
                declared.insert(
                    0,
                    {"id": overall["id"], "label": overall["label"], "windowSize": 0},
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
    """Warn where one comparability set holds differently-tuned runs (§8.2).

    A profile hash covers the profile *declaration*, which is identical across
    every run of a sketch. Once the timings became operator-set (§6.9), that
    stopped being enough to call two runs comparable: a rat run at a 10 ms poke
    hold and one run at 500 ms share a hash and would be plotted on one axis as
    though the task had not changed underneath them.

    A warning rather than a split. Splitting would fragment a cohort's history
    the first time anyone nudged a timeout, and most parameter edits genuinely
    don't invalidate a comparison -- but the reader is the one who can judge
    that, and silence denies them the chance.

    Runs with no recorded parameters (pre-§6.9) are ignored rather than counted
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
    unplugged erase a cohort's history, which is the exact failure §8.3's
    keep-the-last-good-summary rule exists to prevent — so it must not be
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
      (`data.md` §12). Pruning it would throw away the `animal_id`,
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
    that name in this install's library, and the run scores by inference (§8.2)
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


# --- adopted orphans (§8.1) -------------------------------------------------


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


def _animal_from_filename(
    path: Path, session_folder: Path, animals: list[Any]
) -> str | None:
    """The animal a file *names*, when the document it holds got it wrong.

    Real archives carry typos. One file in this lab's Squeekstreet archive
    records `rat: "HmM103"` while its filename says `HM103_…` — and without a
    second opinion that run vanishes from HM103's history, which reads like the
    animal didn't run that day rather than like a mistyped field. A hole that
    looks like data is the worst of the available failures.

    This is not the guessing §8.1 rules out. The filename and the `rat` field
    are two independent recordings of the same fact by the same program at the
    same moment, and the stem has to be *exactly* what `data.md` §2
    prescribes — `<animal>_<the session folder this file is actually sitting
    in>_<HHMMSS>` — checked against the folder on disk rather than assumed. A
    file that doesn't follow the convention contributes nothing. The token that
    survives all that must still match a roster name exactly, case-folded, the
    same test the document's field had to pass.
    """
    stem = path.stem
    marker = f"_{session_folder.name}_"
    cut = stem.find(marker)
    if cut <= 0:
        return None
    tail = stem[cut + len(marker) :]
    if len(tail) != 6 or not tail.isdigit():
        return None
    folded = stem[:cut].casefold()
    return next((a.id for a in animals if a.name.casefold() == folded), None)


def _orphan_run_id(path: Path) -> str:
    """Deterministic synthetic run id, so re-running the rescan is idempotent.

    Keyed on the **run identity** (the file stem), not the path. A duplicated
    run has two paths, and which copy `_prefer` picks can legitimately change
    between scans — when the Arduino Directory comes back, say, and one copy
    suddenly resolves a profile. A path-keyed id would then mint a *second*
    row for a run that already had one, leaving both in place: precisely the
    double-counting the deduplication exists to prevent. Keyed on identity,
    the same run always lands on the same row and `INSERT OR REPLACE` updates
    it in place.
    """
    digest = hashlib.sha1(reader.run_identity(path).encode("utf-8")).hexdigest()
    return f"adopted:{digest[:16]}"


def _synthetic_session_id(entry: AdoptedRun) -> str:
    """One id per (prefix, number, date) group — stable across rescans, so a
    frontend session selection survives a refresh."""
    return f"adopted:{entry.prefix_name}_{entry.session_number}_{entry.date or 'undated'}"


def _adopted_to_run(entry: AdoptedRun) -> SessionAnimalRun:
    """An adopted orphan in `SessionAnimalRun` clothing, so the indexing,
    caching, and profile ladder treat it exactly like a recorded run. The box
    number is honestly unknown — a filename doesn't carry one."""
    run = SessionAnimalRun(
        id=entry.id,
        session_id=_synthetic_session_id(entry),
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
    adopted: list[AdoptedRun], cohort_id: str
) -> tuple[list[Session], dict[str, int]]:
    """Payload-only session entries grouped from adopted runs' folder names.

    Never database rows — a fabricated `sessions` row would corrupt
    session-number suggestion and the same-day reuse warning (§8.1).
    """
    groups: dict[str, list[AdoptedRun]] = {}
    for entry in adopted:
        groups.setdefault(_synthetic_session_id(entry), []).append(entry)

    sessions: list[Session] = []
    counts: dict[str, int] = {}
    for session_id, entries in groups.items():
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
                status="completed",
                folder_path=str(reader.session_folder_of(Path(first.file_path))),
            )
        )
        counts[session_id] = len(entries)
    return sessions, counts


def _merge_sessions(recorded: list[Session], synthetic: list[Session]) -> list[Session]:
    """Chronological merge for the shared session axis. String sort is correct
    here because every date is ISO — legacy `MM_DD_YY` spellings were already
    converted at adoption time by `parse_session_folder`."""
    return sorted([*recorded, *synthetic], key=lambda s: (s.date, s.started_at, s.id))
