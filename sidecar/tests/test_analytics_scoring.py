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
import threading
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService, derive, infer
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.rig import registry
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
