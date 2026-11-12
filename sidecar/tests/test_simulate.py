"""Simulate before flashing (`TASKS.md#simulating-a-spine-task`).

A spine task runs through replay against a simulated animal and is scored as
Analytics scores a recorded run, so these tests read what Simulate serves: the
document it builds, then `summarize` and the trial table over it.
"""

from __future__ import annotations

import copy
from collections import Counter

import pytest

from ephymeris_sidecar.analytics import simulation, stream
from ephymeris_sidecar.analytics.stream import simulate as sim
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.taskdef import generate, lowering, seeds
from ephymeris_sidecar.taskdef.model import TaskDefinition
from tests.fixtures import spine as fixture
from tests.live_sidecar import Refused
from tests.test_spine_editor import FULL_TRIAL, built
from tests.wire import dispatch, running_app


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


CORRECT = sim.Animal("correct")
RANDOM = sim.Animal("random")
SILENT = sim.Animal("silent")


def snapshot(definition: dict) -> dict:
    return generate.build_profile(TaskDefinition.from_json(definition)).to_json()


def run(definition: dict, animal: sim.Animal, seed: int = 7, **kwargs) -> sim.Simulated:
    return sim.simulate(snapshot(definition), animal, seed, **kwargs)


def trials(result: sim.Simulated) -> list[dict]:
    table = spine_stream.trial_table(result.document)
    assert table is not None, "a simulated run always replays"
    return table["trials"]


def report(definition: dict, animal: sim.Animal, seed: int = 7, **kwargs) -> dict:
    return simulation.payload(TaskDefinition.from_json(definition), animal, seed, **kwargs)


# --- the acceptance criteria --------------------------------------------------


def test_an_always_correct_animal_shows_the_reversal_s_switch_trial():
    # Block a ends at 8 correct of the last 10: an animal that is never wrong
    # gets there on trial 8, so block b starts on trial 9 and runs its 4.
    out = report(fixture.reversal(), CORRECT)
    assert out["switches"] == [{"index": 0, "block": "a"}, {"index": 8, "block": "b"}]
    assert out["endedBy"] == "blocks"
    assert len(out["trialTable"]["trials"]) == 12
    assert {t["outcome"] for t in out["trialTable"]["trials"]} == {"correct"}


def test_a_no_go_row_no_block_draws_is_absent_from_the_simulated_table():
    definition = fixture.go_no_go(blocks=[{"id": "b1", "rows": ["go"], "trials": 20}])
    out = report(definition, CORRECT)
    assert out["absent"] == [{"rowId": "no_go", "name": "No-go", "blocks": []}]
    assert {t["row"] for t in out["trialTable"]["trials"]} == {"go"}


def test_a_no_go_row_weighted_zero_is_absent_and_names_its_block():
    definition = fixture.go_no_go(blocks=[{"id": "b1", "rows": ["go", "no_go"], "select": "weighted",
                                           "weights": [1, 0], "trials": 20}])
    out = report(definition, CORRECT)
    assert out["absent"] == [{"rowId": "no_go", "name": "No-go", "blocks": ["b1"]}]


def test_every_drawn_row_is_present():
    assert report(fixture.go_no_go(), CORRECT)["absent"] == []


# --- the animals ----------------------------------------------------------------


@pytest.mark.parametrize("definition", [fixture.two_afc(), fixture.go_no_go()], ids=["2afc", "go_no_go"])
def test_an_always_correct_animal_scores_one(definition):
    summary = stream.summarize(run(definition, CORRECT).document, None)
    assert summary.status == "ok", summary.detail
    assert summary.overall.p_session == 1.0
    assert all(m.p_session == 1.0 for m in summary.metrics)


def test_an_always_correct_animal_withholds_on_a_no_go_row():
    rows = trials(run(fixture.go_no_go(), CORRECT))
    assert {t["outcome"] for t in rows if t["row"] == "no_go"} == {"withheld"}
    assert {t["outcome"] for t in rows if t["row"] == "go"} == {"correct"}
    assert all(t["response"] is None for t in rows if t["row"] == "no_go")


def test_a_random_animal_answers_every_way_a_window_offers():
    rows = trials(run(fixture.two_afc(blocks=[{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": 200}]),
                      RANDOM))
    assert {t["outcome"] for t in rows} == {"correct", "wrong_response", "omission"}


def test_a_biased_animal_mostly_answers_its_side():
    definition = fixture.two_afc(blocks=[{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": 200}])
    rows = trials(run(definition, sim.Animal("biased", response="right", permille=900)))
    answered = Counter(t["response"] for t in rows if t["response"] is not None)
    assert answered["right_well"] > 0.8 * sum(answered.values())


def test_a_biased_animal_names_a_response_the_spine_has():
    with pytest.raises(ValueError, match="response"):
        run(fixture.two_afc(), sim.Animal("biased", response="nowhere"))


def test_an_unknown_animal_is_refused():
    with pytest.raises(ValueError, match="animal"):
        run(fixture.two_afc(), sim.Animal("clever"))


def test_an_animal_that_never_responds_only_aborts_or_omits():
    rows = trials(run(fixture.held_trial(), SILENT))
    assert rows, "the Wait's timeout still ends each trial"
    assert {t["outcome"] for t in rows} <= set(lowering.EXCLUDED_CLASSES) | {"omission"}
    assert all(t["response"] is None and not t["rewarded"] for t in rows)


def test_a_session_nothing_ends_stops_at_the_time_limit():
    # 2AFC's Wait has no timeout: an animal that never pokes holds the first trial open.
    result = run(fixture.two_afc(), SILENT, limit_ms=60_000)
    assert result.ended_by == "timeLimit"
    assert not any(t["complete"] for t in trials(result))
    assert stream.summarize(result.document, None).status == "ok"


def test_a_time_limit_ends_at_the_first_trial_start_after_it():
    definition = fixture.two_afc(blocks=[{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": 900}])
    result = run(definition, CORRECT, limit_ms=60_000)
    assert result.ended_by == "timeLimit"
    rows = trials(result)
    assert rows[-1]["atMs"] < 60_000 and all(t["complete"] for t in rows)


def test_a_fixed_ratio_is_pressed_n_times_a_trial():
    rows = trials(run(fixture.fixed_ratio(5), CORRECT))
    assert rows and all(t["outcome"] == "correct" for t in rows)
    assert all(c["count"] == 5 for t in rows for c in t["inputCounts"] if c["phase"] == 0)


def test_a_variable_ratio_s_drawn_n_reaches_the_json_and_mat_copy():
    """End to end (#164): the N each VR trial drew comes through `spine.replayed`
    into the trial table and the derived copy, and a completed trial's N is its
    presses; a silent animal's cut-off trial still has its N."""
    from ephymeris_sidecar.sessions import derived

    rows = trials(run(fixture.variable_ratio(1, 9), CORRECT))
    complete = [t for t in rows if t["complete"]]
    assert len({t["counterN"] for t in complete}) > 1, "a VR draws more than one N"
    for t in complete:
        assert 1 <= t["counterN"] <= 9
        assert t["counterN"] == sum(c["count"] for c in t["inputCounts"] if c["phase"] == 0)

    silent = run(fixture.variable_ratio(1, 9), SILENT, limit_ms=2000)
    block = derived.derive(silent.document)
    assert block is not None and block["trials"]
    assert all(1 <= t["counter_n"] <= 9 for t in block["trials"])
    assert all(t["input_counts"] == [] for t in block["trials"])


def test_a_progressive_ratio_breaks_and_ends_the_session():
    # Presses 200-600 ms apart cannot finish the larger ratios inside 2 s.
    result = run(fixture.progressive_ratio(limit_ms=2000), CORRECT)
    assert result.ended_by == "lastTrial"
    outcomes = [t["outcome"] for t in trials(result)]
    assert outcomes[-1] == "omission" and outcomes[0] == "correct"


# --- seeds and the replay check -------------------------------------------------


def test_the_same_seed_simulates_the_same_session():
    a, b = run(fixture.two_afc(), RANDOM, seed=11), run(fixture.two_afc(), RANDOM, seed=11)
    assert a.document == b.document


def test_another_seed_simulates_another_session():
    definition = fixture.two_afc(blocks=[{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": 60}])
    a, b = trials(run(definition, RANDOM, seed=11)), trials(run(definition, RANDOM, seed=12))
    assert [t["outcome"] for t in a] != [t["outcome"] for t in b]


def test_the_seed_is_the_run_s_trial_seed():
    assert run(fixture.two_afc(), CORRECT, seed=4242).document["trial_seed"] == 4242


@pytest.mark.parametrize("seed_id", [s["id"] for s in seeds.SEEDS])
@pytest.mark.parametrize("animal", [CORRECT, RANDOM, sim.Animal("biased", permille=700), SILENT],
                         ids=["correct", "random", "biased", "silent"])
def test_every_simulated_seed_task_replays_clean(seed_id, animal):
    # The outputs are the checksum: a simulated run that diverged would be a
    # simulator bug, so every animal on every seed must replay to its own stream.
    definition = built(seed_id)
    if animal.kind == "biased":
        windows = [p for p in definition["spine"] if p["phase"] == "response"]
        if not windows:
            pytest.skip("no response window to be biased in")
        animal = sim.Animal("biased", response=windows[0]["responses"][0], permille=700)
    result = run(definition, animal, limit_ms=10 * 60_000)
    summary = stream.summarize(result.document, None)
    assert summary.status == "ok", summary.detail


@pytest.mark.parametrize("seed_id", list(FULL_TRIAL))
def test_a_target_seed_scores_the_correct_animal_perfect_and_the_silent_one_never(seed_id):
    # The poke's Wait times out, so an animal that never responds still runs
    # trials, each an omission or an abort, and never a scored one.
    definition = built(seed_id)
    correct = report(definition, CORRECT, limit_ms=10 * 60_000)
    assert {m["id"]: m["pSession"] for m in correct["metrics"]} == {
        f"replay:{row['id']}:correct": 1.0 for row in definition["rows"]}
    silent = report(definition, SILENT, limit_ms=10 * 60_000)
    outcomes = {t["outcome"] for t in silent["trialTable"]["trials"]}
    assert outcomes and outcomes <= {"omission", "abort_before_stimulus", "abort_during_sampling"}
    assert all(m["counted"] == 0 for m in silent["metrics"])


def test_simulate_leaves_the_snapshot_it_was_given_alone():
    shot = snapshot(fixture.two_afc())
    before = copy.deepcopy(shot)
    sim.simulate(shot, CORRECT, 3)
    assert shot == before


# --- the wire -------------------------------------------------------------------


async def test_tasks_simulate_serves_the_report_and_its_seed(tmp_path):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        given = await dispatch(app, "tasks.simulate", definition=fixture.reversal(),
                               animal={"kind": "correct"}, seed=5)
        drawn = await dispatch(app, "tasks.simulate", definition=fixture.reversal(),
                               animal={"kind": "random"})
    assert given["seed"] == 5 and given["endedBy"] == "blocks"
    assert given["switches"][1] == {"index": 8, "block": "b"}
    assert given["status"] == "ok" and given["trialTable"]["kind"] == "replay"
    assert given["overall"]["pSession"] == 1.0
    assert given["limitMs"] == simulation.DEFAULT_LIMIT_MS
    assert isinstance(drawn["seed"], int) and drawn["seed"] > 0


async def test_tasks_simulate_refuses_a_definition_with_problems(tmp_path):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        with pytest.raises(Refused) as refused:
            await dispatch(app, "tasks.simulate", definition=seeds.SEEDS[0]["definition"],
                           animal={"kind": "correct"})
    assert refused.value.code == "TASK_INVALID"
    assert "problem" in refused.value.message


async def test_tasks_simulate_refuses_a_trial_table_task(tmp_path):
    async with running_app(tmp_path / "app") as app:
        with pytest.raises(Refused) as refused:
            await dispatch(app, "tasks.simulate", definition={"id": "plain", "name": "Plain"},
                           animal={"kind": "correct"})
    assert refused.value.code == "TASK_INVALID"
