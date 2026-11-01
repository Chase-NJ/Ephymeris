"""A spine run in Analytics: scored by replay, flagged when it diverges, never inferred.

A spine run's stream is channel edges and structural codes. Its edge code names
(`ODOR_LINE_1_ON`, `FLUID_2_ON`) look like the trial runner's onset codes to
stream inference, which would score it into confident nonsense. So a spine run,
recognised by what its own file says (the snapshot's `spine` key, or a header
`interp` that is not the trial runner's) and never by a task name, is scored
only by replaying it (`ANALYTICS.md#how-a-spine-run-is-scored`): `ok` with its
trial table and metrics, `diverged` when its outputs are not what replay
predicts, or `unreplayable` when replay cannot run it at all.

The recorded runs here are built by the replay itself from an animal's input
edges, so they are what a board running the tracer must have sent;
`test_spine_run.py` holds the same reading to a run through the real session
path on the host shim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import scoring
from ephymeris_sidecar.analytics.stream import replay
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.rig import registry
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
    """Three trials of the tracer, one aborted, as code names alone (no clock)."""
    code = registry.vocabulary().code_of
    trial = [code("TRIAL_START"), code("TRIAL_LIGHT_ON"), code("ODOR_PORT_ENTER"), code("ODOR_LINE_1_ON")]
    paid = [code("TRIAL_LIGHT_OFF"), code("ODOR_LINE_1_OFF"), code("FLUID_2_ON"), code("FLUID_2_OFF")]
    aborted = [code("ODOR_PORT_EXIT"), code("TRIAL_LIGHT_OFF"), code("ODOR_LINE_1_OFF")]
    return [code("START_SESSION"), *trial, *paid, *trial, *aborted, *trial, *paid, code("END_SESSION")]


def spine_snapshot() -> dict:
    return generate.build_profile(TaskDefinition.from_json(fixture.tracer())).to_json()


#: An animal on the tracer: trial 1 holds, trial 2 lets go during the odor,
#: trial 3 holds. (tick, code name)
ANIMAL = [(200, "ODOR_PORT_ENTER"), (5000, "ODOR_PORT_ENTER"), (5300, "ODOR_PORT_EXIT"),
          (8500, "ODOR_PORT_ENTER")]


def recorded_document(*, trials: int = 3, seed: int = 99, animal=ANIMAL, end_at: int = 20000) -> dict:
    """A tracer run's document, every strobe what its board must have sent."""
    snapshot = spine_snapshot()
    code = {name: int(c) for c, name in snapshot["strobes"].items()}
    config = {f["metadataKey"]: f["default"] for f in snapshot["config"]}
    config["block_trials"] = trials
    document = {
        "rat": "remy1", "sketch": "Spine Tracer", "stop_reason": "BF_END_SESSION received",
        "interp": replay.INTERP_VERSION, "trial_seed": seed, "channel_set_hash": "abc123",
        task_profile.SNAPSHOT_KEY: snapshot, **config,
        "ts_data": [[code[n], t] for t, n in animal] + [[code["END_SESSION"], end_at]],
    }
    predicted = spine_stream.expected_stream(spine_stream.decode(document))
    document["ts_data"] = [list(s) for s in predicted]
    document["n_events"] = len(predicted)
    return document


def write_document(rig: Rig, document: dict) -> str:
    session = rig.add_session("1", "2026-10-30")
    run_id = rig.add_run(session, "a1", tracer_stream(), snapshot=False)
    path = Path(rig.sessions.runs_for(session)[0].file_path)
    path.write_text(json.dumps(document), encoding="utf-8")
    return run_id


def write_spine_run(rig: Rig, *, snapshot: bool = True, interp: int | None = replay.INTERP_VERSION) -> str:
    """A run of the tracer's codes with no clock replay could predict."""
    session = rig.add_session("1", "2026-10-30")
    run_id = rig.add_run(session, "a1", tracer_stream(), snapshot=False)
    path = Path(rig.sessions.runs_for(session)[0].file_path)
    document = json.loads(path.read_text(encoding="utf-8"))
    if snapshot:
        document[task_profile.SNAPSHOT_KEY] = spine_snapshot()
    if interp is not None:
        document["interp"] = interp
    path.write_text(json.dumps(document), encoding="utf-8")
    return run_id


def diverged_flag(rig: Rig, run_id: str):
    with rig.db.read() as unit:
        return unit.execute("SELECT diverged FROM session_animal_runs WHERE id = ?", (run_id,)).fetchone()[0]


async def test_a_recorded_spine_run_shows_its_trial_table_and_metrics(rig: Rig) -> None:
    run_id = write_document(rig, recorded_document())
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "ok", run["detail"]
    assert run["profileSource"] == "snapshot", "decoded by its own snapshot, not today's task.json"
    assert run["profileHash"] == task_profile.profile_hash(task_profile.parse_profile(spine_snapshot()))

    [metric] = run["metrics"]
    assert metric["label"] == "P(correct | Odor 1)"
    assert (metric["hits"], metric["counted"], metric["triggered"], metric["excluded"]) == (2, 2, 3, 1), \
        "two held trials correct, the abort excluded"
    assert run["overall"]["counted"] == 2
    assert run["outcomes"] is None and run["engagement"] is None, "never the legacy scorer's tallies"

    tallies = run["replay"]
    assert tallies["interp"] == replay.INTERP_VERSION and tallies["trials"] == 3
    assert tallies["unclassified"] == 1
    assert [(c["outcomeClass"], c["n"], c["of"]) for c in tallies["classes"]] == [("correct", 2, 3)]
    assert tallies["rewarded"]["n"] == 2 and tallies["rewarded"]["of"] == 3
    assert [r["rowId"] for r in tallies["rows"]] == ["r1"]
    assert run["divergence"] is None
    assert diverged_flag(rig, run_id) == 0

    [series] = (await rig.service.series([run_id]))["series"]
    table = series["trialTable"]
    assert table["phases"] == ["wait", "present", "delay", "outcome", "iti"]
    first, aborted = table["trials"][0], table["trials"][1]
    assert (first["row"], first["rowName"], first["block"]) == ("r1", "Odor 1", "b1")
    assert first["outcome"] == "correct" and first["rewarded"] and first["rewardLine"] == "fluid_2"
    assert first["rewardMs"] == 100 and first["phaseEntries"][:2] == [0, 200]
    assert first["inputCounts"] == [{"phase": 0, "channel": "odor_port", "count": 1}]
    assert aborted["outcome"] is None and not aborted["rewarded"]
    assert len(table["trials"]) == 3 and all(t["complete"] for t in table["trials"])


async def test_a_run_with_an_edited_output_strobe_is_diverged_and_not_scored(rig: Rig) -> None:
    document = recorded_document()
    fluid_on = next(int(c) for c, n in document[task_profile.SNAPSHOT_KEY]["strobes"].items()
                    if n == "FLUID_2_ON")
    k = next(i for i, (c, _) in enumerate(document["ts_data"]) if c == fluid_on)
    document["ts_data"][k][1] += 1
    run_id = write_document(rig, document)

    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "diverged"
    assert run["metrics"] == [] and run["overall"] is None and run["replay"] is None
    assert run["divergence"]["index"] == k
    at = document["ts_data"][k][1]
    assert run["divergence"]["expected"] == f"FLUID_2_ON@{at - 1}"
    assert run["divergence"]["recorded"] == f"FLUID_2_ON@{at}"
    assert "diverged" in run["detail"] and f"FLUID_2_ON@{at - 1}" in run["detail"]
    assert diverged_flag(rig, run_id) == 1
    [series] = (await rig.service.series([run_id]))["series"]
    assert series["trialTable"] is None, "a diverged run has no trial table"


@pytest.mark.parametrize("snapshot", [True, False])
async def test_a_run_from_an_unknown_interp_is_reported_and_never_replayed(rig: Rig, monkeypatch, snapshot) -> None:
    def never(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("an unknown INTERP was replayed")

    monkeypatch.setattr(replay, "replay", never)
    unknown = max(replay.INTERP_VERSIONS) + 1
    run_id = write_spine_run(rig, snapshot=snapshot, interp=unknown)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "unreplayable"
    assert run["metrics"] == [] and run["outcomes"] is None, "never inferred"
    if snapshot:
        assert f"INTERP {unknown}" in run["detail"]
    assert diverged_flag(rig, run_id) is None, "not replayed, so neither diverged nor not"


async def test_a_spine_run_with_no_table_is_unreplayable_and_never_inferred(rig: Rig) -> None:
    """`interp: 2` with no surviving snapshot: a table ran it, so it is never
    inferred, and there is no table to replay."""
    write_spine_run(rig, snapshot=False)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "unreplayable"
    assert run["metrics"] == []


async def test_a_legacy_run_is_scored_as_before(rig: Rig) -> None:
    """`interp: 1` is the trial runner: a legacy run, scored by its profile."""
    write_spine_run(rig, snapshot=False, interp=1)
    run = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert run["status"] == "ok" and run["replay"] is None and run["divergence"] is None
    assert run["metrics"], "scored by the legacy ladder"


def test_a_run_is_replayed_once_for_its_check_and_its_table(monkeypatch) -> None:
    document = recorded_document()
    calls = []
    real = replay.replay

    def counted(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(replay, "replay", counted)
    result = spine_stream.replayed(document)
    assert result.divergence is None and len(result.trials) == 3
    assert len(calls) == 1


def test_a_pick_state_in_no_phase_keeps_the_phase_map(monkeypatch) -> None:
    """#101's `table.phases` gives a pick state no phase (null): the map is
    still read, never dropped for the null."""
    document = recorded_document()
    spine = document[task_profile.SNAPSHOT_KEY]["spine"]
    phases = [0, 1, 2, 3, 3, 3, 4]
    phases[0] = None  # as a pick state would be, standing in for state 0
    spine["table"]["phases"] = phases
    first = spine_stream.replayed(document).trials[0]
    assert first.phase_entries == (None, 200, 1200, 1700, 1801)


def test_the_canary_holds_spine_runs() -> None:
    names = [name for name, *_ in scoring._canary_runs(scoring._seed_vocabulary())]
    assert {"spine-run", "spine-replayed", "spine-diverged"} <= set(names)


def test_adding_an_outcome_class_moves_the_score_version(monkeypatch) -> None:
    before = scoring.canary_fingerprint()
    from ephymeris_sidecar.taskdef import lowering

    monkeypatch.setattr(lowering, "OUTCOME_CLASSES", (*lowering.OUTCOME_CLASSES, "new_class"))
    assert scoring.canary_fingerprint() != before


# --- the generated go/no-go and 2AFC tasks, replayed and scored -----------------


def simulated_document(definition: dict, animal, *, trials: int = 10, seed: int = 99,
                       ticks: int = 200_000) -> dict:
    """A run of a generated spine task, its animal reacting tick by tick.

    `animal(phase, row, ms_in_phase)` gives the level of each input bit. Only
    the edges the state in force watches are strobed, as the board does; every
    other strobe is what replay predicts, so the file is what a board running
    this table with this animal must have sent.
    """
    snapshot = generate.build_profile(TaskDefinition.from_json(definition)).to_json()
    spine = snapshot["spine"]
    code = {name: int(c) for c, name in snapshot["strobes"].items()}
    config = {f["metadataKey"]: f["default"] for f in snapshot["config"]} | {"block_trials": trials}
    document = {
        "rat": "remy1", "sketch": definition["name"], "stop_reason": "BF_END_SESSION received",
        "interp": spine["interp"], "trial_seed": seed, task_profile.SNAPSHOT_KEY: snapshot, **config,
        "ts_data": [],
    }
    record = spine_stream.decode(document)
    phases, rows = spine["table"]["phases"], spine["table"]["rows"]
    rise = [i["rise"] for i in spine["inputs"]]
    fall = [i["fall"] for i in spine["inputs"]]
    core, _ = replay.begin(record.table, record.params, seed, 0, record.interp)
    levels, entered, started, strobes, end = 0, 0, 1, [], None
    for now in range(1, ticks):
        phase = phases[core.state]
        want = animal(phase, rows[core.state], now - entered)
        rose, fell = want & ~levels, levels & ~want
        levels = want
        watch = record.table.states[core.state].watch
        strobes += [[code[rise[b]], now] for b in range(len(rise)) if (rose & watch) >> b & 1]
        strobes += [[code[fall[b]], now] for b in range(len(fall)) if (fell & watch) >> b & 1]
        before = phase
        core, a = replay.step(core, replay.Edges(rose, fell), now)
        if a.flags & replay.ACT_TRIAL_START:
            started += 1
            if started > trials:
                end = now
                break
        if phases[core.state] != before:
            entered = now
    document["ts_data"] = strobes + [[code["END_SESSION"], end]]
    document["ts_data"] = [list(s) for s in spine_stream.expected_stream(spine_stream.decode(document))]
    document["n_events"] = len(document["ts_data"])
    return document


PORT, RESP = 0b01, 0b10


def go_no_go_animal(phase, row, ms):  # noqa: ANN001
    """Pokes at every wait; licks 300 ms into a go window, never into a no-go one."""
    if phase == 0:
        return PORT
    if phase == 2 and row == 0 and ms >= 300:
        return RESP
    return 0


async def test_a_perfect_go_no_go_session_scores_one_overall_and_per_row() -> None:
    from ephymeris_sidecar.analytics import stream

    document = simulated_document(fixture.go_no_go(), go_no_go_animal)
    summary = stream.summarize(document, None)
    assert summary.status == "ok", summary.detail
    assert [(m.label, m.p_session) for m in summary.metrics] == [
        ("P(correct | Go)", 1.0), ("P(correct | No-go)", 1.0)]
    assert summary.overall.p_session == 1.0 and summary.replay.trials == 10
    table = spine_stream.trial_table(document)
    go = [t for t in table["trials"] if t["row"] == "go"]
    no_go = [t for t in table["trials"] if t["row"] == "no_go"]
    assert go and no_go, "the pick drew both rows"
    assert {t["outcome"] for t in go} == {"correct"} and {t["outcome"] for t in no_go} == {"withheld"}
    assert all(t["response"] == "right_well" and t["latencyMs"] == 300 for t in go)
    assert all(t["response"] is None for t in no_go), "a withhold has no response"
    assert all(t["phaseEntries"][0] is not None for t in table["trials"]), "the pick's null phase is skipped"


def two_afc_animal(phase, row, ms):  # noqa: ANN001
    """Holds the port through the odor, then 300 ms into the window goes to the
    row's correct well (odor 1 right, odor 2 left) and holds it."""
    left, right = 0b010, 0b100
    if phase in (0, 1):
        return 0b001
    if phase == 2 and ms >= 300:
        return right if row == 0 else left
    return 0


async def test_a_2afc_session_replays_to_its_responses_and_rewards() -> None:
    from ephymeris_sidecar.analytics import stream

    document = simulated_document(fixture.two_afc(), two_afc_animal)
    summary = stream.summarize(document, None)
    assert summary.status == "ok", summary.detail
    assert summary.overall.p_session == 1.0 and summary.replay.rewarded.n == 10
    table = spine_stream.trial_table(document)
    assert table["phases"] == ["wait", "present", "response", "outcome", "iti"]
    for t in table["trials"]:
        right = t["row"] == "odor_1"
        assert t["outcome"] == "correct" and t["rewarded"]
        assert t["response"] == ("right_well" if right else "left_well") and t["latencyMs"] == 300
        assert t["rewardLine"] == ("fluid_2" if right else "fluid_1")
        assert t["rewardMs"] == 100 and t["rowName"] == ("Odor 1" if right else "Odor 2")
