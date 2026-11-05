"""Analytics orchestration — `DATA.md#reading-the-archive`,
`DATA.md#analytics-views`.

What the read commands call: the summary, series and recent sessions. Asks
`scoring.RunScorer` for every score, decoded run and cache row. The archive
walk, rescan and tidy, is `CohortArchive`'s (`DATA.md#the-cohort-archive`).

> **No analytics operation may slow, stall, or fail a session**
> (`DATA.md#never-at-the-expense-of-a-session`). Six
> boxes may be `fsync`ing per strobe while this runs. So: one indexing job at
> a time behind a lock, reads sequential in a single worker thread rather than
> a pool, and one transaction per pass.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..sessions.models import SessionAnimalRun
from ..sessions.paths import parse_session_folder
from . import reader, stream
from .stream import false_starts

from .archive import CohortArchive
from .repository import AnalyticsRepository, CachedRun
from .scoring import RunScorer
from .walk import _normalize

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
        min_counted: int = stream.DEFAULT_MIN_COUNTED,
        sketch_lookup: Callable[[str], str | None] | None = None,
    ) -> None:
        self._db = db
        self._cohorts = cohorts
        self._sessions = sessions
        self._broadcast = broadcast
        self._repo = AnalyticsRepository(db)
        self._min_counted = min_counted
        #: Every score, decoded run and cache row (`DATA.md#caching`). The
        #: scorer resolves a document's `sketch` *name* through `sketch_lookup`
        #: each time it reads a recovered run (`DATA.md#orphan-adoption`).
        self._scorer = RunScorer(db, sketch_lookup)
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

        # False starts (`ANALYTICS.md#false-starts`): judged over the same runs the
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

    # --- false starts (ANALYTICS.md#false-starts) -------------------------------

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
        metrics = stream.series(document, profile, mode=mode, metric_ids=metric_ids)
        # The joint walk rides along with the per-metric series rather than
        # taking a command of its own: the file is already open and already
        # decoded here, and the one panel that wants it is on the same
        # screen as the ones that want the series. It is empty for any
        # profile that doesn't declare exactly two conditions.
        trail = stream.strategy_trail(document, profile)
        # The per-trial tape rides along for the same reason the trail
        # does: the file is already open and decoded, and the panel that
        # wants it is on the same screen as the ones that want the series.
        trials = stream.trials_of(document, profile)
        return {
            "runId": run_id,
            "mode": mode,
            "metrics": [m.to_json() for m in metrics],
            "trail": [p.to_json() for p in trail],
            "trials": [t.to_json() for t in trials],
            # The run's trial table: a spine run's from its replay, a legacy
            # run's from the legacy decoder
            # (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`). Here, not
            # in the summary: per-trial data is never cached (`DATA.md#caching`).
            "trialTable": stream.trial_table_of(document, profile),
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
    (`ANALYTICS.md#which-profile-decodes-a-run`)."""
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
    (`ANALYTICS.md#which-profile-decodes-a-run`).

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


def _program_name(run: SessionAnimalRun) -> str:
    """What this run says it ran, as opposed to what this machine can find.

    `sketch_path` answers a different question — *where a `task.json` was
    resolved* — and it is legitimately empty for a file recorded on another
    rig: the archive walk adopts the file, the name lookup finds no sketch by
    that name in this install's library, and the run scores by inference
    (`ANALYTICS.md#which-profile-decodes-a-run`)
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
