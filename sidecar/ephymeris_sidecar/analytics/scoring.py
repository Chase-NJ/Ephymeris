"""Scoring a run, and the cache in front of it — `DATA.md#which-profile-decodes-a-run`,
`DATA.md#caching`.

`RunScorer` owns the profile ladder, the derived-metrics cache and its key. The
service asks it to score a pass of runs (`score`) or to decode one run for a
chart (`decode`), and holds no part of either.

> **No analytics operation may slow, stall, or fail a session**
> (`DATA.md#never-at-the-expense-of-a-session`). Reads are sequential in one
> worker thread, in chunks, and a pass writes in one transaction.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from ..sessions.models import SessionAnimalRun
from ..tasks import profile as task_profile
from ..tasks.profile import TaskProfile
from . import derive, infer, reader
from .repository import AnalyticsRepository, CachedRun, CacheKey

log = logging.getLogger(__name__)

#: Emit progress every N runs rather than per run — same publishing discipline
#: as `backup.status`.
PROGRESS_EVERY = 10

#: Runs handed to the worker thread per hop. Also the granularity at which the
#: event loop gets to breathe between batches, so it is kept small enough that
#: a chunk of cache misses can't stall a live `port.output` batch.
INDEX_CHUNK = 32


@dataclass
class _Resolved:
    """A profile plus how much it can be trusted
    (`DATA.md#which-profile-decodes-a-run`)."""

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

#: `progress(done, total)`, awaited on the event loop between chunks.
Progress = Callable[[int, int], Awaitable[None]]


@dataclass
class _Pass:
    """What one pass over runs shares, and nothing that outlives it.

    `remember` collects the profiles the pass decoded with, by digest, for
    `score` to write in the one transaction that ends the pass. `None` makes
    the pass read-only — `decode`'s — so nothing is collected and nothing can
    be written (`DATA.md#caching`).
    """

    memo: _ProfileMemo = field(default_factory=dict)
    remember: dict[str, TaskProfile] | None = field(default_factory=dict)

    def digest(self, profile: TaskProfile) -> str:
        """The profile's content address, collected for writing if this pass
        writes. Pure: the hash is computed, not looked up."""
        digest = task_profile.profile_hash(profile)
        if self.remember is not None:
            self.remember.setdefault(digest, profile)
        return digest


@dataclass(frozen=True)
class Decoded:
    """One run read and decoded, for a chart (`DATA.md#learning-curves`).

    `document` is None exactly when the file could not be read; `status` and
    `detail` then say why. `profile`, `source` and `digest` are what `score`
    would score the same file with.
    """

    status: str  # 'ok' | 'missing' | 'unreadable'
    detail: str | None
    document: dict[str, Any] | None
    profile: TaskProfile | None
    source: str
    digest: str | None


class RunScorer:
    def __init__(
        self,
        repo: AnalyticsRepository,
        sketch_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self._repo = repo
        #: Resolve a document's `sketch` *name* to a sketch in this install's
        #: library, for adopted orphans whose run record never existed
        #: (`DATA.md#orphan-adoption`). The honest analog of the
        #: `sketch-current` fallback (`DATA.md#which-profile-decodes-a-run`) —
        #: and exactly as trustworthy, which is to say: marked as such, never
        #: as a snapshot.
        self._sketch_lookup = sketch_lookup

    # --- a pass ------------------------------------------------------------

    async def score(
        self,
        runs: list[SessionAnimalRun],
        *,
        min_counted: int,
        progress: Progress | None = None,
    ) -> list[CachedRun]:
        """Resolve, read, and score every run — cache hits skipped. One entry
        per run, in order, judged against `min_counted`.

        Reads are sequential in a worker thread, not a pool: the live `.tsv`
        write path is the priority and a pool would multiply disk contention
        against it (`DATA.md#never-at-the-expense-of-a-session`). The caller
        holds the archive lock.
        """
        cached = await asyncio.to_thread(self._repo.load_cached, [r.id for r in runs])
        out: list[CachedRun] = []
        fresh: list[CachedRun] = []
        total = len(runs)
        pass_ = _Pass()

        if progress is not None:
            await progress(0, total)
        emitted = 0
        for start in range(0, total, INDEX_CHUNK):
            chunk = runs[start : start + INDEX_CHUNK]
            entries = await asyncio.to_thread(
                self._score_chunk, chunk, cached, min_counted, pass_
            )
            for run, entry in zip(chunk, entries):
                if cached.get(run.id) is not entry:
                    fresh.append(entry)
                # Judged against THIS request's threshold, hit or miss: the
                # cache holds no threshold (`DATA.md#caching`).
                out.append(
                    replace(entry, summary=derive.with_threshold(entry.summary, min_counted))
                )
            done = start + len(chunk)
            if progress is not None and done - emitted >= PROGRESS_EVERY:
                emitted = done
                await progress(done, total)

        await asyncio.to_thread(self._write, fresh, pass_.remember or {})
        if progress is not None:
            await progress(total, total)
        log.info("analytics: scored %d runs (%d recomputed)", total, len(fresh))
        return out

    def _write(self, fresh: list[CachedRun], profiles: dict[str, TaskProfile]) -> None:
        """The pass's one transaction: every profile it decoded with, then
        every row it recomputed (`DATA.md#never-at-the-expense-of-a-session`).

        The profiles are content-addressed `INSERT OR IGNORE`s, so the hundredth
        pass over the same archive adds nothing. They are written even on an
        all-hit pass: resolution still read today's `task.json`, and without
        its blob a profile group has no `taskName` to label itself with.
        """
        for profile in profiles.values():
            self._repo.remember_profile(profile)
        if fresh:
            self._repo.store(fresh)
        else:
            self._repo.flush()

    def _score_chunk(
        self,
        runs: list[SessionAnimalRun],
        cached: dict[str, CachedRun],
        min_counted: int,
        pass_: _Pass,
    ) -> list[CachedRun]:
        """One worker-thread hop's worth of runs.

        Chunking does not add concurrency — the runs inside a chunk are still
        read one after another on one thread, and the whole pass is still
        behind the archive lock (`DATA.md#never-at-the-expense-of-a-session`).
        It only stops the loop paying a thread
        hop per run, which at archive scale costs more than the reads do once
        the cache is warm.
        """
        return [self._score_one(r, cached.get(r.id), min_counted, pass_) for r in runs]

    def _score_one(
        self,
        run: SessionAnimalRun,
        cached: CachedRun | None,
        min_counted: int,
        pass_: _Pass,
    ) -> CachedRun:
        resolved = self._resolve_profile(run, pass_)

        if not run.file_path:
            return CachedRun(
                run_id=run.id,
                status="missing",
                detail="no file was recorded for this run",
                profile_hash=resolved.digest,
                profile_source=resolved.source,
                params_hash=None,
                config=None,
                summary=derive.RunSummary(status="missing").to_json(),
                key=CacheKey("", None, None, resolved.digest, derive.CODEC_VERSION),
            )

        # Stat, not read. The cache key is answerable from the stat alone, so a
        # hit costs one syscall and opens nothing — which is the difference
        # between a warm dashboard open reading a whole archive off a network
        # share and reading none of it (`DATA.md#caching`).
        stat = reader.stat_run(run.file_path)

        if stat.status == "missing":
            # Keep the last good summary rather than dropping it — a briefly
            # unreachable share must not erase history from the charts
            # (`DATA.md#caching`).
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
                config=None,
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
                config=None,
                summary=derive.RunSummary(
                    status="unreadable", detail=result.detail
                ).to_json(),
                key=key,
            )

        profile, source, digest = self._scoring_profile(resolved, result.document, pass_)
        summary = derive.summarize(result.document, profile, min_counted=min_counted)
        payload = summary.to_json()
        detail = summary.detail
        if summary.status == "no-metrics" and not detail and resolved.reason:
            # A run that scored nothing is the one case where the operator most
            # needs to know *why* — "no metrics" alone is indistinguishable
            # from a genuinely profile-less sketch and offers nothing to fix.
            detail = resolved.reason
            payload["detail"] = detail
        # What the FILE says it ran on. Only ever read for a run this database
        # has no row for (`DATA.md#the-embedded-task-profile`) — the row's own
        # `params_hash` and `config` win where there is one — so this costs a
        # dictionary comprehension on the runs that would otherwise report no
        # parameters at all. The values ride along for the session log's
        # what-changed (`DATA.md#what-changed`).
        recorded = task_profile.recorded_config(result.document, profile)
        return CachedRun(
            run_id=run.id,
            status=summary.status,
            detail=detail,
            profile_hash=digest,
            profile_source=source,
            params_hash=task_profile.params_hash(recorded),
            config=recorded,
            summary=payload,
            key=key,
        )

    # --- one run, for a chart ----------------------------------------------

    def resolve_for_series(self, run: SessionAnimalRun) -> _Resolved:
        """Interim: `series`'s half of the ladder until it calls `decode`."""
        return self._resolve_profile(run, _Pass(remember=None))

    def scoring_profile_for_series(
        self, resolved: _Resolved, document: dict[str, Any]
    ) -> TaskProfile | None:
        """Interim: `series`'s half of the ladder until it calls `decode`."""
        profile, _, _ = self._scoring_profile(resolved, document, _Pass(remember=None))
        return profile

    def decode(self, run: SessionAnimalRun) -> Decoded:
        """Read one run and settle the profile it decodes with — the same
        ladder `score` scores with, so a chart draws the trials the summary
        counted.

        Synchronous and blocking: the caller runs it in a worker thread
        (`DATA.md#never-at-the-expense-of-a-session`). **It never writes**: the
        read-only `series` path must leave nothing behind, not even an
        uncommitted insert for the next writer's commit to carry.
        """
        result = (
            reader.read_run(run.file_path)
            if run.file_path
            else reader.ReadResult(status="missing", detail="no file")
        )
        pass_ = _Pass(remember=None)
        resolved = self._resolve_profile(run, pass_)
        if not result.ok or result.document is None:
            return Decoded(
                result.status, result.detail, None,
                resolved.profile, resolved.source, resolved.digest,
            )
        profile, source, digest = self._scoring_profile(resolved, result.document, pass_)
        return Decoded("ok", None, result.document, profile, source, digest)

    # --- the ladder --------------------------------------------------------

    def _scoring_profile(
        self,
        resolved: _Resolved,
        document: dict[str, Any],
        pass_: _Pass,
    ) -> tuple[TaskProfile | None, str, str | None]:
        """The profile a run is actually scored with — the ladder's last rungs.

        Two of the four rungs need the document and therefore live here rather
        than in `_resolve_profile`, which deliberately runs before any file is
        opened:

        1. the database snapshot, resolved already — the profile this rig
           recorded the run with;
        2. **the file's own snapshot** (`DATA.md#the-embedded-task-profile`),
           which is the same claim made by
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
        content-addressed like any other, so profile *groups* work unchanged —
        by the pass, at its end, and never by a read-only one.

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
            return embedded, "snapshot", pass_.digest(embedded)

        if resolved.profile is not None and resolved.profile.live_metrics:
            return resolved.profile, resolved.source, resolved.digest
        sketch = document.get("sketch")
        inferred = infer.infer_profile(
            derive.codes_of(document),
            sketch_name=sketch if isinstance(sketch, str) and sketch else None,
        )
        if inferred is None:
            return resolved.profile, resolved.source, resolved.digest
        return inferred, "inferred", pass_.digest(inferred)

    def _resolve_profile(self, run: SessionAnimalRun, pass_: _Pass) -> _Resolved:
        """Snapshot, then today's `task.json`, then nothing
        (`DATA.md#which-profile-decodes-a-run`).

        Three states, not two: the fallback itself can fail, because the
        recorded `sketch_path` may have been renamed, moved, or dropped from
        the sketch library since the run.

        The pass's memo collapses its repeated work — a whole archive is
        usually one or two sketches, and without it every run pays its own
        `task.json` read and sha256.

        **It is scoped to the pass and must stay that way.** Resolution happens
        at read time on purpose (`DATA.md#which-profile-decodes-a-run`): a
        newly saved task,
        or an edited `task.json`, takes effect on the very next summary. A memo that
        outlived the pass would freeze exactly what that rule exists to keep
        thawed. Promoting this to a field would look like an obvious win and
        would be a regression.
        """
        key = (
            run.profile_hash or "",
            run.sketch_path or "",
            getattr(run, "sketch_name", None) or "",
        )
        if key in pass_.memo:
            resolved, sketch_path = pass_.memo[key]
            # Replay the path the first run of this key resolved to. It is not
            # bookkeeping: `summary` reports `sketchPath` per run
            # (`DATA.md#which-profile-decodes-a-run`), so
            # skipping this would leave one run of a group naming its sketch
            # and the rest naming nothing.
            run.sketch_path = sketch_path
            return resolved

        resolved = self._resolve_profile_uncached(run, pass_)
        pass_.memo[key] = (resolved, run.sketch_path)
        return resolved

    # NOTE: this resolves the *declared* rungs only. The inference rung lives
    # in `_scoring_profile`, after the file is read — it needs the codes, and
    # resolution deliberately runs before any file is opened.
    def _resolve_profile_uncached(self, run: SessionAnimalRun, pass_: _Pass) -> _Resolved:
        if run.profile_hash:
            stored = self._repo.load_profile(run.profile_hash)
            if stored is not None:
                return _Resolved(stored, "snapshot", run.profile_hash)

        named = getattr(run, "sketch_name", None)
        if not run.sketch_path and named and self._sketch_lookup is not None:
            # Resolve against the sketch library *now* rather than trusting
            # what adoption recorded. A run adopted while its sketch was
            # missing would otherwise stay permanently
            # undecodable, needing a second rescan to un-stick — and the
            # recorded path is only ever a cache of this same lookup.
            run.sketch_path = self._sketch_lookup(named) or ""

        if not run.sketch_path:
            # An adopted orphan whose sketch name matched nothing in the
            # current sketch library has no task.json to fall back to. Name the
            # sketch it wanted: that is the one thing the operator can act on,
            # by declaring it as a saved task's `legacyNames`.
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
        # Remember the blob even though this is only a fallback decode (the
        # pass writes it at its end; a read-only pass doesn't): without it a
        # profile group has no `taskName` to label itself with, which is every
        # group in an archive that predates snapshots.
        # This does **not** promote the run to `snapshot`: how much the
        # decoding can be trusted is `source`, and it stays `sketch-current`.
        return _Resolved(current, "sketch-current", pass_.digest(current))
