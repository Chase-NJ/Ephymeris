"""Scoring a run, and the cache in front of it — `ANALYTICS.md#which-profile-decodes-a-run`,
`DATA.md#caching`.

`RunScorer` owns the profile ladder, the derived-metrics cache and its key. The
service asks it to score a pass of runs (`score`) or to decode one run for a
chart (`decode`), and holds no part of either.

**The key's version covers every input a cached row depends on**
(`current_version`): `SCORE_VERSION`, a fingerprint of what this code answers
for a fixed set of canary runs, and this machine's strobe vocabulary. A
change to the maths, the payload's shape, inference, the recorded config or
the parsing of an embedded profile moves the canary's answers, so the
version, so every warm row is recomputed — without anyone remembering to bump
anything. What the canary cannot reach is listed at `SCORE_VERSION`
(`DATA.md#caching`).

> **No analytics operation may slow, stall, or fail a session**
> (`DATA.md#never-at-the-expense-of-a-session`). Reads are sequential in one
> worker thread, in chunks, and a pass writes in one transaction.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field, replace
from typing import Any, Awaitable, Callable

from ..cohorts.db import Database
from ..rig import registry
from ..rig.registry import Vocabulary
from ..sessions.models import SessionAnimalRun
from ..tasks import profile as task_profile
from ..taskdef import lowering
from ..tasks.profile import TaskProfile
from . import reader, stream
from .stream import infer
from .stream import spine as spine_stream
from .repository import AnalyticsRepository, CachedRun, CacheKey

log = logging.getLogger(__name__)

#: Emit progress every N runs rather than per run — same publishing discipline
#: as `backup.status`.
PROGRESS_EVERY = 10

#: Runs handed to the worker thread per hop. Also the granularity at which the
#: event loop gets to breathe between batches, so it is kept small enough that
#: a chunk of cache misses can't stall a live `port.output` batch.
INDEX_CHUNK = 32

#: The part of the cache version a person sets (`DATA.md#caching`). The rest
#: of it is computed (`current_version`): the canary's answers move by
#: themselves whenever scoring does, for every input the canary reaches.
#:
#: **Bump this for a change the canary cannot see.** It scores documents
#: already in memory against resolutions it builds itself, so it never reaches:
#:
#: * reading a file — `reader.stat_run` / `reader.parse_run`, which decide
#:   what a file reads as, and which files are cached as `missing` or
#:   `unreadable` (with their `detail`) under their stat key;
#: * the `missing` and `unreadable` rows `RunScorer._score_one` builds;
#: * resolution's `reason` texts (`RunScorer._resolve_profile_uncached`).
#:
#: For anything else, prefer adding a canary case that shows the change
#: (`_canary_runs`): it keeps the next such change honest too.
#:
#: Version 10: a no-go metric is scored at every response port, under any
#: vocabulary. The canary's seed vocabulary cannot reach a retired
#: `WATER_POKE_NONE` or a slot with an unresolved code, and rows cached at 9
#: under such a vocabulary kept the inflated P(withhold); the canary now has
#: a case for each, and the bump re-reads those rows.
#:
#: Version 11: a spine run is scored by replay (`ANALYTICS.md#how-a-spine-run-is-scored`).
#: Every spine run cached before it is read again, as `ok`, `diverged` or `unreplayable`. This
#: is the ADR's `CODEC_VERSION`: the cache's `codec_version` column, whose
#: hand-set half this is. Adding an outcome class moves it by itself: the
#: canary hashes `OUTCOME_CLASSES`.
#:
#: **"The numbers didn't move" is not an exemption.** A cached row is served
#: verbatim, so a field added to the payload without a version change goes
#: missing from every warm row.
SCORE_VERSION = 11


@dataclass
class _Resolved:
    """A profile plus how much it can be trusted
    (`ANALYTICS.md#which-profile-decodes-a-run`)."""

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

    #: The strobe vocabulary, read once for the whole pass: inference reads
    #: this copy and the key's version hashes this copy, so the two cannot
    #: disagree about which vocabulary a row was scored under.
    vocabulary: Vocabulary
    #: The version every row this pass writes is keyed under.
    version: int = 0
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
        db: Database,
        sketch_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        #: The database itself, not only its repository: a pass's write is one
        #: unit of work (`DATA.md#transactions`).
        self._db = db
        self._repo = AnalyticsRepository(db)
        #: Resolve a document's `sketch` *name* to a sketch in this install's
        #: library, for adopted orphans whose run record never existed
        #: (`DATA.md#orphan-adoption`). The honest analog of the
        #: `sketch-current` fallback (`ANALYTICS.md#which-profile-decodes-a-run`) —
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
        vocabulary = await asyncio.to_thread(registry.vocabulary)
        version = await asyncio.to_thread(current_version, vocabulary)
        cached = await asyncio.to_thread(self._repo.load_cached, [r.id for r in runs])
        out: list[CachedRun] = []
        fresh: list[CachedRun] = []
        total = len(runs)
        pass_ = _Pass(vocabulary, version=version)

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
                    replace(entry, summary=stream.with_threshold(entry.summary, min_counted))
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
        """The pass's one unit of work (`DATA.md#transactions`): every profile
        it decoded with, then every row it recomputed — so no row names a
        `scored_profile_hash` without its `task_profiles` row, and the pass
        commits once (`DATA.md#never-at-the-expense-of-a-session`).

        The profiles are content-addressed `INSERT OR IGNORE`s, so the hundredth
        pass over the same archive adds nothing, and a unit that changed nothing
        announces nothing to the backup. They are written even on an all-hit
        pass: resolution still read today's `task.json`, and without its blob a
        profile group has no `taskName` to label itself with.
        """
        if not fresh and not profiles:
            return
        with self._db.write() as tx:
            for profile in profiles.values():
                self._repo.remember_profile(profile, tx=tx)
            self._repo.store(fresh, tx=tx)

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
                summary=stream.RunSummary(status="missing").to_json(),
                key=CacheKey("", None, None, resolved.digest, pass_.version),
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
                # Re-keyed with no stat, so the file's return is always a miss:
                # the row may be from an older version, and it is the stat
                # that keeps it from being served as a hit once there is a
                # file to read again. Keyed at this version, the readers that
                # open no file (`CohortArchive.view`) keep seeing the last
                # good summary meanwhile.
                return replace(
                    cached,
                    stale=True,
                    key=CacheKey(run.file_path, None, None, resolved.digest, pass_.version),
                )
            return CachedRun(
                run_id=run.id,
                status="missing",
                detail=stat.detail,
                profile_hash=resolved.digest,
                profile_source=resolved.source,
                params_hash=None,
                config=None,
                summary=stream.RunSummary(status="missing", detail=stat.detail).to_json(),
                key=CacheKey(run.file_path, None, None, resolved.digest, pass_.version),
            )

        key = CacheKey(
            file_path=run.file_path,
            mtime_ns=stat.mtime_ns,
            size=stat.size,
            profile_hash=resolved.digest,
            codec_version=pass_.version,
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
                summary=stream.RunSummary(
                    status="unreadable", detail=result.detail
                ).to_json(),
                key=key,
            )

        return _scored(run.id, resolved, result.document, key, min_counted, pass_)

    # --- one run, for a chart ----------------------------------------------

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
        pass_ = _Pass(registry.vocabulary(), remember=None)
        resolved = self._resolve_profile(run, pass_)
        if not result.ok or result.document is None:
            return Decoded(
                result.status, result.detail, None,
                resolved.profile, resolved.source, resolved.digest,
            )
        profile, source, digest = _settle(resolved, result.document, pass_)
        return Decoded("ok", None, result.document, profile, source, digest)

    # --- the ladder --------------------------------------------------------

    def _resolve_profile(self, run: SessionAnimalRun, pass_: _Pass) -> _Resolved:
        """Snapshot, then today's `task.json`, then nothing
        (`ANALYTICS.md#which-profile-decodes-a-run`).

        Three states, not two: the fallback itself can fail, because the
        recorded `sketch_path` may have been renamed, moved, or dropped from
        the sketch library since the run.

        The pass's memo collapses its repeated work — a whole archive is
        usually one or two sketches, and without it every run pays its own
        `task.json` read and sha256.

        **It is scoped to the pass and must stay that way.** Resolution happens
        at read time on purpose (`ANALYTICS.md#which-profile-decodes-a-run`): a
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
            # (`ANALYTICS.md#which-profile-decodes-a-run`), so
            # skipping this would leave one run of a group naming its sketch
            # and the rest naming nothing.
            run.sketch_path = sketch_path
            return resolved

        resolved = self._resolve_profile_uncached(run, pass_)
        pass_.memo[key] = (resolved, run.sketch_path)
        return resolved

    # NOTE: this resolves the *declared* rungs only. The inference rung lives
    # in `_settle`, after the file is read — it needs the codes, and
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


# --- the ladder's last rungs, and scoring ---------------------------------


def _settle(
resolved: _Resolved, document: dict[str, Any], pass_: _Pass
) -> tuple[TaskProfile | None, str, str | None]:
    """The profile a run is actually scored with — the ladder's last rungs.

    Two of the four rungs need the document and therefore live here rather
    than in `RunScorer._resolve_profile`, which deliberately runs before any
    file is opened:

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
    mtime/size, and of the code and vocabulary that read it, which the key's
    version covers (`score_version`).
    """
    if spine_stream.is_spine_run(document):
        # A spine run decodes by its own snapshot or by nothing: never today's
        # task.json and never inference, whose onset patterns its edge code
        # names only mimic. `summarize` scores it by replay
        # (`ANALYTICS.md#how-a-spine-run-is-scored`).
        embedded = task_profile.embedded_profile(document)
        if embedded is not None:
            return embedded, "snapshot", pass_.digest(embedded)
        if resolved.source == "snapshot":
            return resolved.profile, resolved.source, resolved.digest
        return None, "unavailable", None

    if (
        resolved.source == "snapshot"
        and resolved.profile is not None
        and resolved.profile.live_metrics
    ):
        return _scorable(resolved.profile, pass_), resolved.source, resolved.digest

    embedded = task_profile.embedded_profile(document)
    if embedded is not None and embedded.live_metrics:
        # Reported as a snapshot because that is what it is — the profile
        # the run was configured from, recorded at the time of the run. It
        # arrived by a different road than the database's copy; when both
        # exist they are the same bytes and the cheaper road is taken above.
        return _scorable(embedded, pass_), "snapshot", pass_.digest(embedded)

    if resolved.profile is not None and resolved.profile.live_metrics:
        return _scorable(resolved.profile, pass_), resolved.source, resolved.digest
    sketch = document.get("sketch")
    inferred = infer.infer_profile(
        stream.codes_of(document),
        sketch_name=sketch if isinstance(sketch, str) and sketch else None,
        vocabulary=pass_.vocabulary,
    )
    if inferred is None:
        return resolved.profile, resolved.source, resolved.digest
    return inferred, "inferred", pass_.digest(inferred)


def _scorable(profile: TaskProfile, pass_: _Pass) -> TaskProfile:
    """The copy of a declared profile that is scored: a no-go metric widened
    to every response port (`infer.widen_no_go`). Never the stored profile, or
    its digest and its snapshot would move."""
    return infer.widen_no_go(profile, pass_.vocabulary)


def _scored(
    run_id: str,
    resolved: _Resolved,
    document: dict[str, Any],
    key: CacheKey,
    min_counted: int,
    pass_: _Pass,
) -> CachedRun:
    """Score one read document: the cache row `score` stores, and what the
    canary fingerprints. One function for both, so the canary cannot measure
    a path the real pass doesn't take."""
    profile, source, digest = _settle(resolved, document, pass_)
    summary = stream.summarize(document, profile, min_counted=min_counted)
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
    recorded = task_profile.recorded_config(document, profile)
    return CachedRun(
        run_id=run_id,
        status=summary.status,
        detail=detail,
        profile_hash=digest,
        profile_source=source,
        params_hash=task_profile.params_hash(recorded),
        config=recorded,
        summary=payload,
        key=key,
    )


# --- the version (`DATA.md#caching`) --------------------------------------


def current_version(vocabulary: Vocabulary | None = None) -> int:
    """The version a cached row must carry to be served now
    (`DATA.md#caching`), under `vocabulary` or the one in force.

    The canary is scored once per process (`_process_canary`): code cannot
    change under a running sidecar. The vocabulary can — it is edited on the
    Strobes page — so its half is hashed on every call. Blocking the first
    time; call it from a worker thread.
    """
    return score_version(
        _process_canary(),
        vocabulary if vocabulary is not None else registry.vocabulary(),
    )


_canary_lock = threading.Lock()
_canary: str | None = None


def _process_canary() -> str:
    """`canary_fingerprint()`, scored on first use and kept for the process."""
    global _canary
    with _canary_lock:
        if _canary is None:
            _canary = canary_fingerprint()
        return _canary


def forget_canary() -> None:
    """Drop the process's canary, so the next version scores it again.

    For tests that change scoring code and then stand for a relaunch: a new
    process is exactly what this models. Nothing in the app calls it.
    """
    global _canary
    with _canary_lock:
        _canary = None


def score_version(canary: str, vocabulary: Vocabulary) -> int:
    """`SCORE_VERSION` in the high bits, and in the low 32 a hash of the
    canary's fingerprint and the vocabulary.

    An integer because that is what the cache's `codec_version` column has
    always held; `version >> 32` reads back `SCORE_VERSION`. It can never equal
    a version from before v9 (those were single digits), so every such row is
    recomputed once.
    """
    # Live and retired apart, not `code_map()`'s merge of the two: inference
    # reads live codes only, so retiring or reinstating one changes what a
    # stream infers while leaving the merged map exactly as it was.
    canon = json.dumps(
        {
            "live": {str(entry.code): entry.name for entry in vocabulary},
            "retired": {str(code): name for code, name in vocabulary.retired.items()},
            "slots": {str(slot): fields for slot, fields in vocabulary.port_slots.items()},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    mixed = hashlib.sha256(f"{canary}\n{canon}".encode("utf-8")).digest()
    return (SCORE_VERSION << 32) | int.from_bytes(mixed[:4], "big")


def canary_fingerprint() -> str:
    """What this code answers for a fixed set of runs, hashed.

    The runs cover every rung of the ladder (`ANALYTICS.md#which-profile-decodes-a-run`)
    — a database snapshot, the file's own snapshot with recorded parameters,
    a damaged one, today's `task.json`, inference with a withheld and an
    unanswered condition, a stream with no condition at all, a utility profile,
    a short run and an unclean stop — and each goes through `_scored`, the
    function a real pass scores with. Every field a cache row keeps is hashed:
    status, detail, both digests' profile, source, recorded parameters and the
    full payload, keys included. So any change to what a row would hold moves
    this, and with it the version.

    The codes come from the **shipped seed** vocabulary, by name, so this
    measures the code and not this machine's vocabulary, which `score_version`
    hashes separately. A case that raises is answered by its exception's
    name, and a canary that cannot even be built answers as one case: either
    way the version stays deterministic and analytics stays up.
    """
    seed = _seed_vocabulary()
    try:
        runs = _canary_runs(seed)
    except Exception as exc:  # noqa: BLE001 - the version must not take analytics down
        log.warning("analytics: the score canary could not be built: %r", exc)
        runs = []
        answers: dict[str, Any] = {"canary": {"error": type(exc).__name__}}
    else:
        answers = {}
    # The outcome-class names a replayed run's tallies are keyed by: adding a
    # class is a new vocabulary for the scorer (ADR 0003's "adding a class
    # bumps CODEC_VERSION"), so it moves the version by itself.
    answers["outcome-classes"] = list(lowering.OUTCOME_CLASSES)
    for name, resolved, document, vocabulary in runs:
        try:
            entry = _scored(
                name,
                resolved,
                document,
                CacheKey("", None, None, None, 0),
                stream.DEFAULT_MIN_COUNTED,
                _Pass(vocabulary, remember=None),
            )
            answers[name] = {
                "status": entry.status,
                "detail": entry.detail,
                "profileHash": entry.profile_hash,
                "source": entry.profile_source,
                "paramsHash": entry.params_hash,
                "config": entry.config,
                "summary": entry.summary,
            }
        except Exception as exc:  # noqa: BLE001 - the version must not take analytics down
            log.warning("analytics: score canary %s raised %r", name, exc)
            answers[name] = {"error": type(exc).__name__}
    canon = json.dumps(answers, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


_seed_lock = threading.Lock()
_seed: Vocabulary | None = None


def _seed_vocabulary() -> Vocabulary:
    """The shipped seed vocabulary, read once: it is package data."""
    global _seed
    with _seed_lock:
        if _seed is None:
            _seed = Vocabulary(registry.default_vocabulary_document())
        return _seed


def _canary_runs(
    seed: Vocabulary,
) -> list[tuple[str, _Resolved, dict[str, Any], Vocabulary]]:
    """The canary: (name, what resolution found, the document, the vocabulary
    it is scored under) per case. Most cases use the seed; the vocabulary is
    part of the case so one can show what scoring does under another."""
    code = seed.code_of

    def trial(onset: str, *answer: str) -> list[int]:
        return [code("LIGHTS_ON"), code("ODOR_POKE"), code(onset), code("ODOR_UNPOKE"),
                *(code(name) for name in answer)]

    session = (
        trial("ODOR_1_ON", "WATER_POKE_R", "FLUID_R", "STOP_FLUID_G_R") * 6
        + trial("ODOR_1_ON", "WATER_POKE_L", "WATER_POKE_ERROR_L") * 2
        + trial("ODOR_1_ON", "WATER_POKE_R", "WATER_UNPOKE_EARLY_R")
        + trial("ODOR_3_ON", "WATER_POKE_L", "FLUID_L", "STOP_FLUID_G_L") * 5
        + trial("ODOR_3_ON", "WATER_POKE_R", "WATER_POKE_ERROR_R") * 3
        + trial("ODOR_5_ON", "WATER_POKE_NONE") * 2
        # A no-go answered at either port: a miss at both, never excluded.
        + trial("ODOR_5_ON", "WATER_POKE_L")
        + trial("ODOR_5_ON", "WATER_POKE_R")
        + [code("LIGHTS_ON"), code("ODOR_POKE"), code("ODOR_7_ON"), code("ODOR_UNPOKE_EARLY")] * 2
        + [code("LIGHTS_ON"), code("LAZY_RAT"), code("LIGHTS_OFF")]
    )

    def document(codes: list[int], **extra: Any) -> dict[str, Any]:
        strobes = [code("START_SESSION"), *codes, code("END_SESSION")]
        return {
            "rat": "canary",
            "sketch": "Score canary",
            "stop_reason": stream.CLEAN_STOP_REASON,
            "trial_seed": 7,
            "odor_poke_hold": 300,
            "n_events": len(strobes),
            "ts_data": [[c, i * 250] for i, c in enumerate(strobes)],
            **extra,
        }

    declared: dict[str, Any] = {
        "taskName": "Score canary",
        "strobes": {str(c): n for c, n in seed.code_map().items()},
        "config": [
            {"metadataKey": "odor_poke_hold", "wireKey": "OPH", "label": "Odor poke hold",
             "type": "int", "default": 500},
        ],
        "liveMetrics": [
            {"id": "p_r_odor1", "label": "P(R | Odor 1)", "triggerCode": code("ODOR_1_ON"),
             "successCode": code("WATER_POKE_R"), "alternateCode": code("WATER_POKE_L"),
             "windowSize": 5},
            {"id": "p_l_odor3", "label": "P(L | Odor 3)", "triggerCode": code("ODOR_3_ON"),
             "successCode": code("WATER_POKE_L"), "alternateCode": code("WATER_POKE_R"),
             "windowSize": 5},
            # A no-go type misses at every port: the metric with several alternates.
            {"id": "p_withhold_5", "label": "P(withhold | Odor 5)", "triggerCode": code("ODOR_5_ON"),
             "successCode": code("WATER_POKE_NONE"),
             "alternateCodes": [code("WATER_POKE_L"), code("WATER_POKE_R")], "windowSize": 5},
        ],
    }
    # What a run recorded before that carries: the same no-go metric with ONE
    # alternate, which scoring widens on read (`infer.widen_no_go`).
    before_the_fix = task_profile.parse_profile({
        **declared,
        "liveMetrics": [
            *declared["liveMetrics"][:2],
            {"id": "p_withhold_5", "label": "P(withhold | Odor 5)",
             "triggerCode": code("ODOR_5_ON"), "successCode": code("WATER_POKE_NONE"),
             "alternateCode": code("WATER_POKE_R"), "windowSize": 5},
        ],
    })
    snapshot = task_profile.parse_profile(declared)
    utility = task_profile.parse_profile({**declared, "kind": "utility"})
    today = task_profile.parse_profile(
        {k: v for k, v in declared.items() if k != "strobes"}, seed
    )
    nothing = _Resolved(None, "unavailable", None, "the canary resolves nothing")

    def held(profile: TaskProfile, source: str) -> _Resolved:
        return _Resolved(profile, source, task_profile.profile_hash(profile))

    # Vocabularies the seed cannot show: the withhold code retired (as the
    # Strobes page can), and a port slot whose error code resolves to nothing.
    raw = registry.default_vocabulary_document()
    retired_doc = copy.deepcopy(raw)
    gone = retired_doc["codes"].pop("WATER_POKE_NONE")
    retired_doc["retired"]["WATER_POKE_NONE"] = {"code": gone["code"], "rationale": "canary"}
    damaged_doc = copy.deepcopy(raw)
    damaged_doc["port_slots"]["1"]["error_code"] = "NO_SUCH_CODE"
    retired_none = Vocabulary(retired_doc)
    damaged_slot = Vocabulary(damaged_doc)

    unclean = document(session[: len(session) // 2], stop_reason="host stopped")
    del unclean["trial_seed"]
    return [
        (name, resolved, doc, seed)
        for name, resolved, doc in [
            ("database-snapshot", held(snapshot, "snapshot"), document(session)),
            ("pre-fix-no-go-snapshot", held(before_the_fix, "snapshot"), document(session)),
            ("embedded", nothing, document(session, **{task_profile.SNAPSHOT_KEY: declared})),
            # Not an object at all, so it falls through without a parse warning:
            # this runs on every pass and every archive read.
            ("embedded-damaged", nothing,
             document(session, **{task_profile.SNAPSHOT_KEY: "torn"})),
            ("sketch-current", held(today, "sketch-current"), document(session)),
            ("inferred", nothing, document(session)),
            ("no-condition", nothing, document([code("WATER_POKE_R")] * 3)),
            ("utility", held(utility, "snapshot"), document(session)),
            ("short", held(snapshot, "snapshot"), document(session[:12])),
            ("unclean", held(snapshot, "snapshot"), unclean),
            # A spine run over the same onset-shaped stream, with no table:
            # unreplayable, and never inferred.
            ("spine-run", nothing, document(session, interp=spine_stream.rp.INTERP_VERSION, **{
                task_profile.SNAPSHOT_KEY: {
                    **{k: v for k, v in declared.items() if k != "liveMetrics"},
                    "spine": {"interp": spine_stream.rp.INTERP_VERSION},
                }})),
            # A spine run replay scores, and the same run with one output moved.
            ("spine-replayed", nothing, _spine_canary()),
            ("spine-diverged", nothing, _spine_canary(diverge=True)),
            # A spine snapshot carrying every word `tasks/behaviour.py` leaves out:
            # its scored digest is `profile_hash`'s behaviour projection, so
            # leaving any one word in, or a row unkeyed, moves this.
            ("spine-run-rows", nothing, document(session, interp=spine_stream.rp.INTERP_VERSION, **{
                task_profile.SNAPSHOT_KEY: {
                    **declared,
                    "config": [declared["config"][0] | {
                        "help": "How long the poke is held.", "unit": "ms", "group": "Holds"}],
                    "legacyNames": ["Score canary (old)"],
                    "liveMetrics": declared["liveMetrics"][:1],
                    "spine": {"interp": spine_stream.rp.INTERP_VERSION, "rows": [
                        {"id": "r1", "name": "Odor 1", "bind": {"sample": "odor_line_1"}},
                        {"id": "r3", "name": "Odor 3", "bind": {"sample": "odor_line_3"}},
                    ]},
                }})),
        ]
    ] + [
        # The same single-alternate no-go snapshot, scored under a vocabulary
        # the seed cannot show. Each must still count a poke at either port.
        ("pre-fix-no-go-retired-withhold", held(before_the_fix, "snapshot"),
         document(session), retired_none),
        ("pre-fix-no-go-damaged-slot", held(before_the_fix, "snapshot"),
         document(session), damaged_slot),
    ]


def _spine_canary(*, diverge: bool = False) -> dict[str, Any]:
    """A spine run for the canary, self-contained: a table lowered here, its own
    strobes map, and a stream the replay itself predicts from an animal's
    pokes (trial 1 held, trial 2 aborted, trial 3 held). `diverge` moves its
    first reward strobe one tick, which replay must report."""
    phases = [
        {"phase": "wait", "on": "port", "outputs": ["cue"]},
        {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
        {"phase": "delay", "ms": 500},
        {"phase": "outcome", "line": "reward", "ms": 0},
        {"phase": "iti", "ms": 3000},
    ]
    low = lowering.lower(phases, ["port"], ["cue", "sample", "reward"], session_cap=True)
    names = ["START_SESSION", "TRIAL_START", "END_SESSION", "PORT_ENTER", "PORT_EXIT",
             "CUE_ON", "CUE_OFF", "SAMPLE_ON", "SAMPLE_OFF", "REWARD_ON", "REWARD_OFF"]
    code = {name: i + 1 for i, name in enumerate(names)}
    values = {"NT": 3, "RW1": 100, "RP1": 700}
    config = [{"metadataKey": f"p_{key.lower()}", "wireKey": key, "label": key, "type": "int",
               "default": values.get(key, 0)} for key in low.params]
    durations = iter((1000, 500, 0, 3000))
    recorded = {f["metadataKey"]: values.get(f["wireKey"]) or next(durations) for f in config}
    snapshot = {
        "taskName": "Score canary spine",
        "kind": "behavior",
        "config": config,
        "liveMetrics": [],
        "strobes": {str(c): n for n, c in code.items()},
        "spine": {
            "interp": spine_stream.rp.INTERP_VERSION,
            "spine": phases,
            "rows": [{"id": "r1", "name": "Canary row"}],
            "blocks": [{"id": "b1", "rows": ["r1"], "trials": 3}],
            "inputs": [{"slot": "port", "channel": "port", "rise": "PORT_ENTER", "fall": "PORT_EXIT"}],
            "outputs": [{"slot": s, "channel": s, "on": f"{s.upper()}_ON", "off": f"{s.upper()}_OFF"}
                        for s in ("cue", "sample", "reward")],
            "params": list(low.params),
            "table": {"states": [list(s) for s in low.states], "edges": [list(e) for e in low.edges]},
            "structural": {"sessionStart": "START_SESSION", "trialStart": "TRIAL_START",
                           "sessionEnd": "END_SESSION"},
        },
    }
    pokes = [(200, "PORT_ENTER"), (5000, "PORT_ENTER"), (5300, "PORT_EXIT"), (8500, "PORT_ENTER")]
    doc: dict[str, Any] = {
        "rat": "canary", "sketch": "Score canary spine", "stop_reason": stream.CLEAN_STOP_REASON,
        "interp": spine_stream.rp.INTERP_VERSION, "trial_seed": 11, **recorded,
        task_profile.SNAPSHOT_KEY: snapshot,
        "ts_data": [[code[n], t] for t, n in pokes] + [[code["END_SESSION"], 20000]],
    }
    strobes = [list(s) for s in spine_stream.expected_stream(spine_stream.decode(doc))]
    if diverge:
        first = next(s for s in strobes if s[0] == code["REWARD_ON"])
        first[1] += 1
    doc["ts_data"] = strobes
    doc["n_events"] = len(strobes)
    return doc
