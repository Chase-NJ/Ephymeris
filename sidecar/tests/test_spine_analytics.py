"""A spine run in Analytics: not scored yet, said plainly, never inferred.

A spine run's stream is channel edges and structural codes. Its edge code
names (`ODOR_LINE_1_ON`, `FLUID_2_ON`) look like the trial runner's onset codes
to stream inference, which would score it into confident nonsense: trials,
aborts and a "P(right well | fluid 2)". Until replay scores it (ADR 0003), a
spine run is reported as `replay-pending`, recognised by what its own file says
(the snapshot's `spine` key, or the header's `interp`), never by a task name.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.analytics.stream import replay
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture
from tests.test_analytics_service import Rig


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    scoring.forget_canary()
    yield
    scoring.forget_canary()
    fixture.uninstall()


@pytest.fixture
def rig(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        r = Rig(database, tmp_path)
        # The worst case: today's task.json for the recorded sketch DOES score,
        # so a run that fell through the ladder would be scored against it.
        r.write_sketch()
        yield r
    finally:
        database.close()


def tracer_stream() -> list[int]:
    """Three trials of the tracer, one aborted, as its board strobes them."""
    code = registry.vocabulary().code_of
    trial = [code("TRIAL_START"), code("TRIAL_LIGHT_ON"), code("ODOR_PORT_ENTER"), code("ODOR_LINE_1_ON")]
    paid = [code("TRIAL_LIGHT_OFF"), code("ODOR_LINE_1_OFF"), code("FLUID_2_ON"), code("FLUID_2_OFF")]
    aborted = [code("ODOR_PORT_EXIT"), code("TRIAL_LIGHT_OFF"), code("ODOR_LINE_1_OFF")]
    return [code("START_SESSION"), *trial, *paid, *trial, *aborted, *trial, *paid, code("END_SESSION")]


def spine_snapshot() -> dict:
    return generate.build_profile(TaskDefinition.from_json(fixture.tracer())).to_json()


def write_spine_run(rig: Rig, *, snapshot: bool = True, interp: int | None = replay.INTERP_VERSION) -> None:
    session = rig.add_session("1", "2026-10-30")
    rig.add_run(session, "a1", tracer_stream(), snapshot=False)
    path = Path(rig.sessions.runs_for(session)[0].file_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if snapshot:
        document[task_profile.SNAPSHOT_KEY] = spine_snapshot()
    if interp is not None:
        document["interp"] = interp
    path.write_text(json.dumps(document), encoding="utf-8")


async def test_a_spine_run_is_reported_as_awaiting_replay_and_never_inferred(rig: Rig) -> None:
    write_spine_run(rig)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "replay-pending"
    assert "replay" in run["detail"] and "spine" in run["detail"]
    assert run["metrics"] == [] and run["outcomes"] is None and run["engagement"] is None
    assert run["profileSource"] == "snapshot", "decoded by its own snapshot, not today's task.json"
    assert run["profileHash"] == task_profile.profile_hash(task_profile.parse_profile(spine_snapshot()))


async def test_the_header_alone_marks_a_spine_run(rig: Rig) -> None:
    """A spine run whose snapshot did not survive is still one: `interp: 2`
    says a table ran it, so it is never inferred."""
    write_spine_run(rig, snapshot=False)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "replay-pending"
    assert run["metrics"] == []


async def test_a_legacy_run_is_scored_as_before(rig: Rig) -> None:
    """`interp: 1` is the trial runner: a legacy run, scored by its profile."""
    write_spine_run(rig, snapshot=False, interp=1)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] != "replay-pending"


def test_the_canary_holds_a_spine_run() -> None:
    names = [name for name, *_ in scoring._canary_runs(scoring._seed_vocabulary())]
    assert "spine-run" in names
