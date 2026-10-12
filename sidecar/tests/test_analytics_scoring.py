"""Scoring and the version of everything the cache depends on —
`DATA.md#caching`, `DATA.md#never-at-the-expense-of-a-session`.

`test_analytics_service.py` covers the ladder and the cache from the
summary's side. This file holds what Architecture Review II candidate 5 found
missing there: a warm row must answer to *every* input that produced it, not
just to `derive`'s maths (B8); `analytics.series` scores off the event loop
(B9); and a read-only `series` leaves nothing behind in the database.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService, derive, infer, scoring
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.rig.registry import Vocabulary
from ephymeris_sidecar.tasks import profile as task_profile
from tests.conftest import rewrite_keeping_stat
from tests.test_analytics_service import GRGL, HIT_1, HIT_3, MISS_1, Rig


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    r = Rig(db, tmp_path)
    r.write_sketch()
    return r


def _profile_rows(db: Database) -> int:
    with db.lock:
        return db.conn.execute("SELECT COUNT(*) FROM task_profiles").fetchone()[0]


# --- persist=False ----------------------------------------------------------


async def test_a_read_only_series_writes_no_task_profile(rig: Rig) -> None:
    """`series` is read-only (`DATA.md#caching`): it must not leave a
    `task_profiles` insert behind, committed or not.

    A run with no snapshot decodes from today's `task.json` (`sketch-current`),
    and resolving that rung remembers the blob. The summary pass commits it
    with its cache rows; `series` has no such commit, so the insert would sit
    in an open transaction for whichever writer commits next.
    """
    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5, snapshot=False)
    before = _profile_rows(rig.db)

    payload = await rig.service.series([run_id])

    assert payload["series"][0]["metrics"], "the run decoded from today's task.json"
    assert _profile_rows(rig.db) == before
    assert not rig.db.conn.in_transaction


async def test_a_pass_commits_its_profiles_and_rows_once(rig: Rig) -> None:
    """One unit of work per pass (`DATA.md#transactions`): the profiles a pass
    scored with and the rows it recomputed commit together, and the backup
    hears one commit per pass, not one per run (`DATA.md#the-database-copy`).
    A warm pass that changed nothing announces nothing."""
    session = rig.add_session("1", "2026-07-22")
    for animal in ("a1", "a2"):
        rig.add_run(session, animal, HIT_1 * 15 + MISS_1 * 5, snapshot=False)
    announced: list[None] = []
    rig.db.on_commit(lambda: announced.append(None))

    await rig.service.summary(rig.cohort.id)
    assert len(announced) == 1
    assert _profile_rows(rig.db) == 1, "the task.json the runs decoded with"
    assert not rig.db.conn.in_transaction

    await rig.service.summary(rig.cohort.id)
    assert len(announced) == 1, "an all-hit pass changed nothing"
    assert not rig.db.conn.in_transaction


# --- B9: series off the event loop ------------------------------------------


async def test_series_scores_off_the_event_loop(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STRUCTURAL (the ground rules' allowed exception for B9): asserts where
    the work runs, not how long it takes.

    `analytics.series` decodes and scores up to `MAX_SERIES_RUNS` runs, and
    none of it may run on the event loop that flushes six boxes' `port.output`
    (`DATA.md#never-at-the-expense-of-a-session`). Every step after the file
    read — the scoring rungs of the profile ladder, the series, the strategy
    trail and the per-trial tape — must run in a worker thread
    (`asyncio.to_thread`).
    """
    loop_thread = threading.get_ident()
    seen: dict[str, list[int]] = {}

    def spy(owner: object, name: str) -> None:
        real = getattr(owner, name)

        def wrapper(*args, **kwargs):
            seen.setdefault(name, []).append(threading.get_ident())
            return real(*args, **kwargs)

        monkeypatch.setattr(owner, name, wrapper)

    # The scoring rungs: a run with no snapshot asks the file for its own.
    spy(task_profile, "embedded_profile")
    spy(derive, "series")
    spy(derive, "strategy_trail")
    spy(derive, "trials_of")

    session = rig.add_session("1", "2026-07-22")
    run_id = rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5, snapshot=False)

    payload = await rig.service.series([run_id])

    assert payload["series"][0]["metrics"]
    assert set(seen) == {"embedded_profile", "series", "strategy_trail", "trials_of"}, (
        "each step was reached, so the check below is not vacuous"
    )
    on_loop = sorted(name for name, threads in seen.items() if loop_thread in threads)
    assert on_loop == [], f"ran on the event loop: {on_loop}"


# --- the threshold is not part of the cached answer --------------------------


async def test_a_cached_summary_answers_to_the_requested_threshold(rig: Rig) -> None:
    """`minCountedTrials` is a per-request argument (`analytics.summary`), and
    every metric's `lowConfidence` is `counted < min_counted`. The cache key
    holds no threshold, so a warm row answered a second request with the first
    request's verdict.
    """
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5)

    lenient = await rig.service.summary(rig.cohort.id, min_counted=5)
    assert lenient["runs"][0]["metrics"][0]["lowConfidence"] is False

    strict = await rig.service.summary(rig.cohort.id, min_counted=500)
    assert strict["minCountedTrials"] == 500
    assert strict["runs"][0]["metrics"][0]["lowConfidence"] is True
    assert strict["runs"][0]["overall"]["lowConfidence"] is True


# --- B8: every input a cached row depends on --------------------------------
#
# A cached row is served verbatim (`DATA.md#caching`), so a row must stop
# answering when anything that produced it changes — not only `derive`'s
# maths. Each test below warms the cache, changes one input the way a release
# would, and asks again through a NEW service on the same database: what an
# upgraded app sees on its first launch.

TUNED = {
    **GRGL,
    "config": [
        {"metadataKey": "odor_poke_hold", "wireKey": "OPH", "label": "Odor poke hold",
         "type": "int", "default": 500},
    ],
}


def _relaunched(rig: Rig) -> AnalyticsService:
    """The same database under a new process — what an upgrade looks like."""

    async def broadcast(message: dict) -> None:
        pass

    return AnalyticsService(
        db=rig.db,
        cohorts=rig.cohorts,
        sessions=rig.sessions,
        broadcast=broadcast,
        archive=rig.archive,
    )


def _carry_profile(path: Path, profile: dict, **params: object) -> None:
    """Give a run's file its own embedded snapshot and parameter values, as
    `sessions/writer.py` finalizes one (`DATA.md#the-embedded-task-profile`)."""
    document = json.loads(path.read_text(encoding="utf-8"))
    document[task_profile.SNAPSHOT_KEY] = profile
    document.update(params)
    path.write_text(json.dumps(document), encoding="utf-8")


async def test_a_relaunch_with_nothing_changed_keeps_every_warm_row(rig: Rig) -> None:
    """The other half of the tests below, and passes on base: a version that
    moved on every launch would re-read the whole archive at every app start,
    which is the cost the persisted cache exists to avoid (`DATA.md#caching`).
    Every rung is covered: a database snapshot, the file's own, today's
    `task.json`, and inference."""
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", (HIT_1 + HIT_3) * 12)  # database snapshot
    rig.add_run(session, "a2", (HIT_1 + HIT_3) * 12, snapshot=False)  # task.json
    other = rig.add_session("2", "2026-07-23")
    rig.add_run(other, "a1", (HIT_1 + HIT_3) * 12, snapshot=False)
    _carry_profile(Path(rig.sessions.runs_for(other)[0].file_path), TUNED, odor_poke_hold=10)
    inferred = rig.add_session("3", "2026-07-24")
    blind = rig.add_run(inferred, "a2", (HIT_1 + HIT_3) * 12, snapshot=False)
    with rig.db.lock:  # recorded with no sketch at all: nothing to resolve
        rig.db.conn.execute(
            "UPDATE session_animal_runs SET sketch_path = '' WHERE id = ?", (blind,)
        )
        rig.db.conn.commit()
    first = await rig.service.summary(rig.cohort.id)
    assert sorted(r["profileSource"] for r in first["runs"]) == [
        "inferred", "sketch-current", "snapshot", "snapshot",
    ]

    for run in rig.sessions.runs_for_cohort(rig.cohort.id):
        path = Path(run.file_path)
        rewrite_keeping_stat(path, b"x" * path.stat().st_size)

    assert await _relaunched(rig).summary(rig.cohort.id) == first


async def test_a_change_to_inference_reaches_a_warm_row(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B8. `infer.py`'s window shapes every inferred run's payload, and the
    key held only `derive.CODEC_VERSION` (v7 was bumped for inference alone)."""
    (rig.sketch / "task.json").unlink()  # nothing declared: the run is inferred
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", (HIT_1 + HIT_3) * 12, snapshot=False)

    warm = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert warm["profileSource"] == "inferred"
    assert warm["metrics"][0]["windowSize"] == infer.INFERRED_WINDOW

    monkeypatch.setattr(infer, "INFERRED_WINDOW", infer.INFERRED_WINDOW + 5)
    run = (await _relaunched(rig).summary(rig.cohort.id))["runs"][0]

    assert run["metrics"][0]["windowSize"] == infer.INFERRED_WINDOW, (
        "a warm row answered for the old inference"
    )


async def test_a_change_to_embedded_profile_parsing_reaches_a_warm_row(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B8. Which profile a file carries is decided by parsing it
    (`tasks/profile.py` `embedded_profile`), and the key's `profile_hash` is
    the *resolution* digest: NULL for a run scored from its own snapshot."""
    (rig.sketch / "task.json").unlink()
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", (HIT_1 + HIT_3) * 12, snapshot=False)
    _carry_profile(Path(rig.sessions.runs_for(session)[0].file_path), GRGL)

    warm = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert warm["profileSource"] == "snapshot"

    # A release that stops reading this snapshot (say, a stricter parser).
    monkeypatch.setattr(task_profile, "embedded_profile", lambda document: None)
    run = (await _relaunched(rig).summary(rig.cohort.id))["runs"][0]

    assert run["profileSource"] == "inferred", "a warm row answered for the old parser"


async def test_a_change_to_the_recorded_config_reaches_a_warm_row(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B8. A run's file-recorded parameters (`recorded_config`, hashed to
    `paramsHash`) are cached beside its summary and feed the comparability
    pair and the session log's what-changed (`DATA.md#what-changed`)."""
    (rig.sketch / "task.json").unlink()
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", (HIT_1 + HIT_3) * 12, snapshot=False)
    _carry_profile(
        Path(rig.sessions.runs_for(session)[0].file_path), TUNED, odor_poke_hold=10
    )

    warm = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert warm["paramsHash"] == task_profile.params_hash({"odor_poke_hold": 10})

    # A release that changes which of the file's fields count as parameters.
    monkeypatch.setattr(task_profile, "recorded_config", lambda document, profile: None)
    run = (await _relaunched(rig).summary(rig.cohort.id))["runs"][0]

    assert run["paramsHash"] is None, "a warm row answered for the old recorded config"


# --- the one pin (`DATA.md#caching`) ---------------------------------------

#: What today's scoring answers for the canary runs (`scoring.canary_fingerprint`).
CANARY = "76e5b25d07bdb550887afc0366191714251c0304d6cb9425e41f574728dcf353"


def test_the_score_version_pins_every_input() -> None:
    """THE PIN. The cache version is `SCORE_VERSION` plus a hash of what the
    scoring code answers for a fixed set of canary runs and of this machine's
    vocabulary (`scoring.score_version`). So it moves BY ITSELF whenever any
    input to a cached row changes what the row would hold — and a warm cache
    can no longer serve an answer older than the code asking.

    This literal is the tripwire, not the mechanism. It fails when scoring's
    answers change, to say what that costs: every machine re-reads its whole
    archive once on upgrade. If that is intended, update CANARY; nothing needs
    bumping. If the canary DIDN'T move for a change that alters a cached row,
    the canary is blind to it: add a case to `scoring._canary_runs` that shows
    it (or, failing that, bump `SCORE_VERSION`).
    """
    assert scoring.SCORE_VERSION == 9
    assert scoring.canary_fingerprint() == CANARY, (
        "scoring's answers changed: every cache re-reads once (DATA.md#caching)"
    )
    version = scoring.current_version()
    assert version >> 32 == scoring.SCORE_VERSION
    assert version != 8, "every row cached before v9 is recomputed"


def _set(owner: object, name: str, value: object):
    return lambda mp: mp.setattr(owner, name, value)


@pytest.mark.parametrize(
    "change",
    [
        _set(infer, "INFERRED_WINDOW", infer.INFERRED_WINDOW + 1),
        _set(derive, "wilson_interval", lambda hits, n, z=1.0: (0.0, 1.0)),
        _set(derive, "OVERALL_ID", "__pooled__"),
        _set(task_profile, "embedded_profile", lambda document: None),
        _set(task_profile, "recorded_config", lambda document, profile: None),
        _set(task_profile, "params_hash", lambda config: "same-for-all"),
        _set(
            derive.RunSummary, "to_json",
            (lambda real: lambda self: {**real(self), "added": True})(derive.RunSummary.to_json),
        ),
    ],
    ids=[
        "inference window", "derive maths", "payload value", "embedded-profile parsing",
        "recorded config", "params hash", "payload shape",
    ],
)
def test_the_canary_sees_every_input(monkeypatch: pytest.MonkeyPatch, change) -> None:
    """Why the pin is worth anything: each input B8 named, changed, moves the
    canary. A change the canary can't see would leave the version where it
    was, which is the bug this replaces."""
    before = scoring.canary_fingerprint()
    change(monkeypatch)
    assert scoring.canary_fingerprint() != before


def test_the_version_moves_with_the_vocabulary() -> None:
    document = registry.default_vocabulary_document()
    seed = Vocabulary(document)
    document["codes"]["ODOR_99_ON"] = {**document["codes"]["ODOR_1_ON"], "code": _free_code(document)}
    grown = Vocabulary(document)
    assert scoring.score_version(CANARY, seed) != scoring.score_version(CANARY, grown)


def test_the_canary_is_the_same_in_every_process() -> None:
    """The version is persisted, so it must not depend on anything a process
    picks at random: a hash seed changing set order would move it on every
    launch and re-read the archive at each app start."""
    script = "from ephymeris_sidecar.analytics import scoring; print(scoring.canary_fingerprint())"
    answers = {
        subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "4242")
    }
    assert answers == {CANARY}


async def test_a_reader_that_opens_no_file_ignores_another_versions_row(
    db: Database, tmp_path: Path
) -> None:
    """The archive view closes a recovered session's clock from the cache
    (`DATA.md#the-cohort-archive`), and the session log and false starts read
    it the same way, without opening a file. A row from another version is
    what a summary would recompute, so those readers must not serve it either:
    until a summary rescores the run, its session stays open rather than
    closing on the old answer."""
    from tests.test_analytics_adoption import LegacyRig

    legacy = LegacyRig(db, tmp_path / "legacy")
    legacy.add_legacy_run("remy1", HIT_1 * 15 + MISS_1 * 5)
    await legacy.service.rescan(legacy.cohort.id)
    await legacy.service.summary(legacy.cohort.id)
    [session] = legacy.archive.view(legacy.cohort.id).recovered
    assert session.ended_at is not None, "closed from the current row"

    [entry] = legacy.repo.load_cached([r.id for r in legacy.archive.view(legacy.cohort.id).runs]).values()
    legacy.repo.store([
        replace(
            entry,
            key=replace(entry.key, codec_version=8),
            summary={**entry.summary, "durationMs": entry.summary["durationMs"] + 3_600_000},
        )
    ])

    [session] = legacy.archive.view(legacy.cohort.id).recovered
    assert session.ended_at is None, "a v8 row closed the session clock"
    assert legacy.repo.load_cached([entry.run_id], version=scoring.current_version()) == {}


@pytest.fixture
def machine_vocabulary():
    """The seed installed as this machine's own vocabulary document, editable
    by the test, and put back afterwards (`TASKS.md#strobe-vocabulary`)."""
    document = registry.default_vocabulary_document()
    registry.set_vocabulary_source(lambda: copy.deepcopy(document))
    try:
        yield document
    finally:
        registry.set_vocabulary_source(None)


def _free_code(document: dict) -> int:
    used = {
        entry["code"]
        for entries in (document["codes"], document["retired"])
        for entry in entries.values()
        if isinstance(entry, dict) and "code" in entry
    }
    low = max(high for _, high in document["reserved"]) + 1
    return next(c for c in range(low, document["code_max"] + 1) if c not in used)


async def test_a_vocabulary_edit_reaches_a_warm_row(
    rig: Rig, machine_vocabulary: dict
) -> None:
    """B8. Inference reads this machine's strobe vocabulary
    (`analytics/infer.py`), which is edited on the Strobes page and is in no
    part of the key. A file copied from another rig can carry a code this
    machine only learns later; once it does, the run's conditions change."""
    unknown = _free_code(machine_vocabulary)
    (rig.sketch / "task.json").unlink()
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(
        session, "a1", (HIT_1 + HIT_3) * 12 + [unknown, HIT_1[1]] * 12, snapshot=False
    )

    warm = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert warm["profileSource"] == "inferred"
    assert len(warm["metrics"]) == 2, "the unknown code is no condition yet"

    onset = next(
        name for name in (f"ODOR_{n}_ON" for n in range(1, 100))
        if name not in machine_vocabulary["codes"]
    )
    machine_vocabulary["codes"][onset] = {
        **machine_vocabulary["codes"]["ODOR_1_ON"], "code": unknown,
    }
    registry.set_vocabulary_source(lambda: copy.deepcopy(machine_vocabulary))

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert len(run["metrics"]) == 3, "a warm row answered for the old vocabulary"
