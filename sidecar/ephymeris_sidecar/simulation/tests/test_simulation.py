"""The task simulator: the real firmware on the host, an animal in the box.

A compiler is what runs these: without one the firmware cannot be built for
this computer, and the tests that need it are skipped. The ones that hold the
simulator's headers to the firmware run everywhere.
"""

from __future__ import annotations

import os
import re
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from ephymeris_sidecar import simulation
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.simulation import Animal, AnimalError, SimulationError, build
from ephymeris_sidecar.simulation.result import document_of, telemetry_of
from ephymeris_sidecar.simulation.session import (
    ENDED_BY_LIMIT,
    ENDED_BY_TRIALS,
    simulate,
    table_of,
)
from ephymeris_sidecar.analytics import stream
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef.model import TaskDefinition
from tests.fixtures import task_definitions as presets
from tests.live_sidecar import LiveSidecar, Refused, live_sidecar

FIRMWARE = Path(__file__).resolve().parents[4] / "firmware"
HARNESS = build.HARNESS

compiled = pytest.mark.skipif(build.compiler() is None, reason="no host C++ compiler")


@pytest.fixture(autouse=True)
def _shipped_wiring():
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


def a_task(preset: str = "grgl_2odor", **params) -> TaskDefinition:
    task = presets.instantiate(preset, "probe")
    return replace(task, params={**task.params, "num_trials": 40, **params})


def names_of(run) -> list[str]:
    vocab = registry.vocabulary()
    return [vocab.name_of(code) for code, _ in run.strobes]


def trial_types(run) -> list[str]:
    return [name for name in names_of(run) if name.startswith("TRIAL_TYPE_")]



def test_the_simulator_names_every_code_the_firmware_emits_by_name():
    emitted = set()
    for source in (FIRMWARE / "libraries" / "BehaviorBox" / "BehaviorBox.h",
                   FIRMWARE / "Olfactory Behavior" / "GRGL" / "GRGL.ino"):
        emitted |= set(re.findall(r"\bBF_([A-Z0-9_]+[A-Z0-9])\b", source.read_text(encoding="utf-8")))
    pins = (HARNESS / "TaskPins.h").read_text(encoding="utf-8")
    listed = set(re.findall(r"X\(([A-Z0-9_]+)\)", pins))
    defined = set(re.findall(r"#define BF_([A-Z0-9_]+) \(bbsim_code\[BBSIM_\1\]\)", pins))
    assert emitted <= listed
    assert listed == defined
    assert listed <= registry.vocabulary().names()


def test_the_simulator_s_key_lists_are_as_long_as_its_counts():
    pins = (HARNESS / "TaskPins.h").read_text(encoding="utf-8")
    stages = int(re.search(r"#define NUM_STAGES (\d+)", pins).group(1))
    types = int(re.search(r"#define BOX_MAX_TRIAL_TYPES (\d+)", pins).group(1))
    assert sorted(map(int, re.findall(r"P_STAGE\((\d+)\)", pins))) == list(range(stages))
    for key, field in (("PW", "poolWeights"), ("RW", "rewardTimes")):
        slots = re.findall(rf'P_INT\("{key}(\d+)", {field}\[(\d+)\]\)', pins)
        assert [(int(n), int(i)) for n, i in slots] == [(i + 1, i) for i in range(types)]


def test_the_table_is_the_generated_one_row_for_row():
    task = a_task("grgl_4odor") if presets.get("grgl_4odor") else a_task()
    lines, conditions = table_of(task)
    rows = [line.split() for line in lines if line.startswith("ROW")]
    generated = generate.task_trials_h(task)
    assert len(rows) == generated.count("TrialType(")
    vocab = registry.vocabulary()
    for slot, row in enumerate(rows):
        assert int(row[9]) == vocab.code_of(generate.type_name(slot))
    assert set(conditions) == {int(row[2]) for row in rows}



def test_an_animal_fills_what_is_left_out_and_refuses_what_it_cannot_be():
    assert Animal.from_json({}) == Animal()
    assert Animal.from_json(Animal(side_bias=-0.5, fallback="winStay").to_json()).fallback == "winStay"
    for wrong in ({"followsOdor": 1.5}, {"sideBias": 2}, {"fallback": "coin"}, {"wings": 2},
                  {"holdMs": 5}, {"initiates": "often"}):
        with pytest.raises(AnimalError):
            Animal.from_json(wrong)



@compiled
@pytest.mark.parametrize("preset", [p["id"] for p in presets.PRESETS])
def test_every_preset_runs_to_its_trial_cap_and_scores_as_a_recorded_run(preset):
    task = a_task(preset)
    run = simulate(task, Animal(), 4242)
    names = names_of(run)
    assert run.ended_by == ENDED_BY_TRIALS
    assert (run.interp, run.stream) == (1, 2)
    assert names[0] == "START_SESSION" and names[-1] == "END_SESSION"
    assert names.count("END_TRIAL") - names.count("INVALID_TRIAL") == 40

    document = document_of(run)
    assert stream.grammar2.is_grammar2_run(document, run.profile)
    summary = stream.summarize(document, run.profile)
    assert summary.status == "ok" and summary.clean
    assert summary.seed == 4242


@compiled
def test_one_seed_repeats_a_session_exactly():
    task = a_task()
    assert simulate(task, Animal(), 7).strobes == simulate(task, Animal(), 7).strobes
    assert simulate(task, Animal(), 7).strobes != simulate(task, Animal(), 8).strobes


@compiled
def test_a_pool_task_deals_the_same_order_whatever_the_animal_does():
    pool = next(p["id"] for p in presets.PRESETS if presets.instantiate(p["id"], "x").selection_mode == "pool")
    task = a_task(pool)
    trained = simulate(task, Animal(leaves_early=0, initiates=1, answers=1), 99)
    guessing = simulate(task, Animal(follows_odor=0, follows_odor_end=0, leaves_early=0,
                                     initiates=1, answers=1), 99)
    assert trial_types(trained) == trial_types(guessing)
    assert trained.strobes != guessing.strobes


@compiled
def test_an_animal_that_never_pokes_is_stopped_at_the_time_limit_with_nothing_earned():
    run = simulate(a_task(), Animal(initiates=0), 3, limit_ms=5 * 60_000)
    names = Counter(names_of(run))
    assert run.ended_by == ENDED_BY_LIMIT
    assert names["LAZY_RAT"] == names["TRIAL_START"] > 0
    assert names["CORRECT"] == 0 and names["END_SESSION"] == 1
    vocab = registry.vocabulary()
    last_trial = max(at for code, at in run.strobes if vocab.name_of(code) == "TRIAL_START")
    assert last_trial < 5 * 60_000 <= run.strobes[-1][1]


@compiled
def test_an_animal_that_only_goes_right_is_wrong_on_every_left_trial():
    run = simulate(a_task(), Animal(follows_odor=0, follows_odor_end=0, side_bias=1,
                                    leaves_early=0, drops_hold=0, initiates=1, answers=1), 11)
    names = Counter(names_of(run))
    assert names["WATER_POKE_L"] == 0 and names["WATER_POKE_R"] > 0
    assert names["WATER_POKE_ERROR_R"] > 0 and names["WATER_POKE_ERROR_L"] == 0


@compiled
def test_a_hold_longer_than_the_animal_can_manage_fails_at_the_port():
    task = a_task()
    stages = [replace(stage, odor_poke_hold=4000) for stage in task.stages]
    run = simulate(replace(task, stages=stages), Animal(hold_ms=1000, leaves_early=0, initiates=1), 5,
                   limit_ms=10 * 60_000)
    names = Counter(names_of(run))
    assert names["CORRECT"] == 0
    assert names["ODOR_UNPOKE_EARLY"] + names["ODOR_UNPOKE_EARLY_SAMPLING"] == names["ODOR_POKE"] > 0


@compiled
def test_the_live_metrics_are_the_ones_a_running_box_reports():
    run = simulate(a_task(), Animal(), 21)
    moved = telemetry_of(run)
    assert moved and all(0 <= entry["strobe"] < len(run.strobes) for entry in moved)
    last = {metric["id"]: metric for metric in moved[-1]["metrics"]}
    summary = stream.summarize(document_of(run), run.profile)
    assert {m.id for m in summary.metrics} == set(last)
    assert sum(metric["hits"] for metric in last.values()) == Counter(names_of(run))["CORRECT"]


@compiled
def test_a_task_with_nothing_to_present_and_a_seed_out_of_range_are_refused():
    with pytest.raises(SimulationError, match="TSK108"):
        simulate(replace(a_task(), trials=[]), Animal(), 1)
    with pytest.raises(SimulationError, match="seed"):
        simulate(a_task(), Animal(), 0)
    with pytest.raises(SimulationError, match="limit"):
        simulate(a_task(), Animal(), 1, limit_ms=0)


def test_a_stress_test_s_seeds_are_a_fixed_walk_inside_the_seed_range():
    seeds = simulation.stress_seeds(2**31 - 3, 5)
    assert seeds == simulation.stress_seeds(2**31 - 3, 5)
    assert len(set(seeds)) == 5 and all(1 <= seed <= 2**31 - 2 for seed in seeds)
    with pytest.raises(SimulationError):
        simulation.check_stress(0, 5)
    with pytest.raises(SimulationError):
        simulation.check_stress(3, 51)



@compiled
def test_a_staged_simulator_is_built_run_through_a_trial_and_found_by_its_folder(tmp_path, monkeypatch):
    build.build(tmp_path, FIRMWARE)
    build.check(tmp_path)
    monkeypatch.setenv(build.BUNDLED_ENV, str(tmp_path))
    assert {build.locate(mode) for mode in build.MODES} == {build.executable(tmp_path, mode) for mode in build.MODES}
    assert simulate(a_task(), Animal(), 7).ended_by == ENDED_BY_TRIALS


def test_a_simulator_that_will_not_start_fails_the_check(tmp_path):
    """What a Windows runner made of a file that is no program: the launch
    itself raises, before there is a process to listen to."""
    for mode in build.MODES:
        fake = build.executable(tmp_path, mode)
        fake.write_bytes(b"not a program\x00\x01\x02")
        fake.chmod(0o755)
    with pytest.raises(simulation.SimulatorUnavailable, match="did not run a trial: it would not start"):
        build.check(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="the stand-in simulator is a shell script")
def test_a_simulator_that_starts_and_runs_no_trial_fails_the_check(tmp_path):
    for mode in build.MODES:
        fake = build.executable(tmp_path, mode)
        fake.write_text("#!/bin/sh\necho READY\n", encoding="utf-8")
        fake.chmod(0o755)
    with pytest.raises(simulation.SimulatorUnavailable, match="did not run a trial: READY"):
        build.check(tmp_path)



@pytest.fixture
async def sidecar(tmp_path: Path):
    async with live_sidecar(tmp_path) as live:
        yield live


@compiled
async def test_simulate_and_stress_test_answer_over_the_wire(sidecar: LiveSidecar) -> None:
    task = a_task().to_json()
    one = await sidecar.call("tasks.simulate", definition=task, animal={}, seed=17)
    assert one["seed"] == 17 and one["endedBy"] == "trials"
    assert one["animal"] == Animal().to_json()
    assert one["summary"]["status"] == "ok" and one["trialTable"]["kind"] == "grammar2"
    assert one["water"]["rewards"] == one["summary"]["outcomes"]["rewarded"]

    fresh = await sidecar.call("tasks.simulate", definition=task, animal={})
    assert fresh["seed"] != 17

    stress = await sidecar.call(
        "tasks.stressTest", definition=task, sessions=2, seed=5,
        animals=[{"label": "trained", "animal": {}},
                 {"label": "guessing", "animal": {"followsOdor": 0, "followsOdorEnd": 0}}],
    )
    trained, guessing = stress["animals"]
    assert [s["seed"] for s in trained["sessions"]] == stress["seeds"] == [s["seed"] for s in guessing["sessions"]]
    assert trained["meanRewards"] > guessing["meanRewards"]


async def test_an_animal_the_simulation_cannot_be_is_refused_by_code(sidecar: LiveSidecar) -> None:
    with pytest.raises(Refused) as refused:
        await sidecar.call("tasks.simulate", definition=a_task().to_json(), animal={"sideBias": 3})
    assert refused.value.code == "SIMULATION_REFUSED"


async def test_a_computer_with_no_simulator_says_so(sidecar: LiveSidecar, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(build.BUNDLED_ENV, str(tmp_path / "nowhere"))
    with pytest.raises(Refused) as refused:
        await sidecar.call("tasks.simulate", definition=a_task().to_json(), animal={})
    assert refused.value.code == "SIMULATOR_UNAVAILABLE"
