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
from . import derive, reader
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
                    "profileHash": entry.profile_hash,
                    "paramsHash": run.params_hash,
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
            metrics = derive.series(
                result.document, resolved.profile, mode=mode, metric_ids=metric_ids
            )
            # The joint walk rides along with the per-metric series rather than
            # taking a command of its own: the file is already open and already
            # decoded here, and the one panel that wants it is on the same
            # screen as the ones that want the series. It is empty for any
            # profile that doesn't declare exactly two conditions.
            trail = derive.strategy_trail(result.document, resolved.profile)
            out.append(
                {
                    "runId": run_id,
                    "mode": mode,
                    "metrics": [m.to_json() for m in metrics],
                    "trail": [p.to_json() for p in trail],
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
        """Walk the archive for files no run record points at (§8.1).

        The database-first path covers everything this app recorded. This
        covers what it didn't: runs finalized with no active session, a crash
        between the file write and the commit, and files restored from the
        backup mirror or copied from the other lab machine.
        """
        if self._lock.locked():
            raise AnalyticsBusy("an analytics scan is already running")

        async with self._lock:
            cohort = await asyncio.to_thread(self._cohorts.get, cohort_id)
            folder_exists = await asyncio.to_thread(
                lambda: Path(cohort.data_folder).expanduser().is_dir()
            )
            runs = await asyncio.to_thread(self._sessions.runs_for_cohort, cohort_id)
            known = {
                _normalize(r.file_path) for r in runs if r.file_path
            }
            await self._progress(cohort_id, "walking", 0, 0)
            found = await asyncio.to_thread(reader.walk_session_files, cohort.data_folder)

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
                entry, adoption = await asyncio.to_thread(
                    self._describe_orphan, path, cohort, cohort_id
                )
                if adoption is None:
                    orphans.append(entry)
                    continue
                identity = reader.run_identity(path)
                incumbent = best.get(identity)
                if incumbent is None:
                    best[identity] = adoption
                    orphans.append(entry)
                    continue
                duplicates += 1
                if _prefer(adoption, incumbent):
                    best[identity] = adoption

            adoptable = list(best.values())
            adopted = 0
            if adopt_orphans and adoptable:
                # INSERT OR REPLACE on the deterministic id: a re-run refreshes
                # (a renamed sketch resolves again, a re-rostered animal
                # re-matches) rather than duplicating.
                await asyncio.to_thread(self._repo.store_adopted, adoptable)
                adopted = len(adoptable)

            await self._progress(cohort_id, "walking", len(found), len(found))

        return {
            "scanned": len(found),
            "adopted": adopted,
            "duplicates": duplicates,
            "orphans": orphans,
            "cohortId": cohort_id,
            "dataFolder": cohort.data_folder,
            "folderMissing": not folder_exists,
        }

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
                summary=derive.RunSummary(
                    status="unreadable", detail=result.detail
                ).to_json(),
                key=key,
            )

        summary = derive.summarize(result.document, resolved.profile, min_counted=threshold)
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
            profile_hash=resolved.digest,
            profile_source=resolved.source,
            summary=payload,
            key=key,
        )

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
            reason = (
                f"this run names the sketch “{named}”, which doesn't match any "
                "sketch in the Arduino Directory, so there's no task.json to "
                "score it with"
                if named
                else "no sketch was recorded for this run"
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


def _normalize(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve()).casefold()
    except OSError:  # pragma: no cover
        return path.casefold()


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
