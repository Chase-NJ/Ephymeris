"""GRGL's penalties, trial flow and selection, as a spine definition writes
them and lowering lowers them (`TASKS.md#grgls-rules-on-the-spine`, #166).

Lowering is checked on the tables it writes; then a whole GRGL-shaped 2AFC is
simulated through its snapshot, so every rule is seen working end to end.
"""

from __future__ import annotations

import copy

import pytest

from ephymeris_sidecar.analytics import stream
from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream import simulate as sim
from ephymeris_sidecar.analytics.stream import spine as spine_stream
from ephymeris_sidecar.taskdef import generate, lowering
from ephymeris_sidecar.taskdef import spine as spine_task
from ephymeris_sidecar.taskdef.model import TaskDefinition
from tests.fixtures import spine as fixture


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def lowered(definition: dict) -> lowering.Lowered:
    slots = definition["slots"]
    return lowering.lower(
        definition["spine"],
        inputs=[s["id"] for s in slots if s["type"] == "digital_in"],
        outputs=[s["id"] for s in slots if s["type"] != "digital_in"],
        rows=definition["rows"], blocks=definition["blocks"],
        repeat_aborts=bool(definition.get("repeatAborts")),
    )


def slot(low: lowering.Lowered, key: str) -> int:
    return low.params.index(key)


def states_reading(low: lowering.Lowered, key: str) -> list[tuple[int, ...]]:
    return [s for s in low.states if s[2] == slot(low, key)]


def grgl_2afc(**edits) -> dict:  # noqa: ANN003
    """The 2AFC fixture with GRGL's penalties: a Wait timeout of 4 s whose lazy
    penalty escalates 6 s a time to 30 s, a sampling abort of 10 s, a wrong well
    of 20 s, a broken hold of 10 s, the well's exit awaited after a reward."""
    doc = fixture.two_afc(**edits)
    wait, present, window, outcome, _ = doc["spine"]
    wait.update(timeoutMs=4000, penaltyMs=6000, escalateMs=6000, escalateMaxMs=30000)
    present.update(penaltyMs=10000)
    window.update(brokenPenaltyMs=10000)
    outcome.update(awaitExit=True)
    for row in doc["rows"]:
        for key, entry in row["map"].items():
            if entry["outcome"] != "correct":
                entry["penaltyMs"] = 20000
    return doc


# --- penalties ----------------------------------------------------------------


def test_lowering_writes_interp_8():
    assert lowering.INTERP_VERSION == rp.INTERP_VERSION == 8


def test_an_exit_with_a_penalty_ends_in_an_iti_copy_that_reads_it():
    low = lowered(grgl_2afc())
    assert "P0" in low.params and "P1" in low.params
    lazy_end = states_reading(low, "P0")
    abort_end = states_reading(low, "P1")
    assert lazy_end and abort_end
    assert all(s[11] == lowering.OUTCOME_ABORT_BEFORE for s in lazy_end)
    assert all(s[11] == lowering.OUTCOME_ABORT_DURING for s in abort_end)
    assert all(s[4] == 0 for s in lazy_end + abort_end), "a penalty replaces the ITI: next is the trial's start"


def test_an_exit_with_no_penalty_keeps_the_iti():
    low = lowered(fixture.two_afc(spine=[dict(p, **({"timeoutMs": 4000} if p["phase"] == "wait" else {}))
                                         for p in fixture.two_afc()["spine"]]))
    assert not any(k.startswith("P") and k[1:].isdigit() for k in low.params)
    marked = [s for s in low.states if s[11] == lowering.OUTCOME_ABORT_BEFORE]
    assert marked and all(s[2] == slot(low, "T4") for s in marked)


def test_a_wait_s_escalating_penalty_marks_its_end_and_names_its_step_and_cap():
    low = lowered(grgl_2afc())
    assert all(s[10] & lowering.ESCALATE for s in states_reading(low, "P0"))
    assert not any(s[10] & lowering.ESCALATE for s in states_reading(low, "P1"))
    assert low.lazy == (slot(low, "LS0"), slot(low, "LM0"))


def test_a_map_entry_s_penalty_ends_its_branch_in_its_own_copy():
    low = lowered(grgl_2afc())
    for r in (1, 2):
        copies = [k for k in low.params if k.startswith(f"PE{r}_")]
        assert copies, "each row's wrong well and timeout carry the penalty"
        for key in copies:
            assert states_reading(low, key), key


def test_a_broken_hold_s_penalty_reads_the_window_s_slot():
    low = lowered(grgl_2afc())
    assert states_reading(low, "PB2")


# --- the well's exit ------------------------------------------------------------


def test_an_awaited_exit_follows_the_reward_and_the_well_stays_watched():
    low = lowered(grgl_2afc())
    awaits = [i for i, s in enumerate(low.states) if s[10] & lowering.AWAIT_LOW]
    assert len(awaits) == 2, "one per row: after its correct well's reward"
    for i in awaits:
        s = low.states[i]
        (bit, edge, _), = [low.edges[s[8]]]
        assert edge == lowering.FALL and s[1] >> bit & 1 and s[2] == lowering.NONE
        rewards = [r for r in low.states if r[4] == i]
        assert rewards and all(r[1] >> bit & 1 for r in rewards), "the reward watches the well it pays at"


# --- blocks ---------------------------------------------------------------------


def test_a_block_can_override_the_well_hold():
    doc = grgl_2afc()
    doc["blocks"][0]["holdMs"] = {"2": 50}
    low = lowered(doc)
    assert (0, slot(low, "H2"), slot(low, "B1H2")) in low.overrides


def test_grgl_anti_bias_and_the_run_cap_go_in_the_block():
    doc = grgl_2afc()
    doc["blocks"][0].update(select="antibias", biasWindow=20, biasStrength=500, biasMin=20, biasMax=980, maxRun=10)
    low = lowered(doc)
    block = low.blocks[0]
    assert block[11:] == (slot(low, "BS1"), slot(low, "BL1"), slot(low, "BH1"), slot(low, "BR1"))
    assert lowering.BLOCK_BYTES == 16


def test_aborts_that_repeat_are_a_task_switch():
    assert lowered(grgl_2afc(repeatAborts=True)).repeat_aborts
    assert not lowered(grgl_2afc()).repeat_aborts


# --- end to end -------------------------------------------------------------------


def snapshot(definition: dict) -> dict:
    return generate.build_profile(TaskDefinition.from_json(definition)).to_json()


@pytest.mark.parametrize("animal", ["correct", "random", "silent"])
def test_a_grgl_shaped_2afc_simulates_and_replays_clean(animal):
    doc = grgl_2afc(repeatAborts=True)
    doc["blocks"][0].update(select="antibias", biasWindow=20, biasStrength=500, biasMin=20, biasMax=980,
                            maxRun=3, holdMs={"2": 100}, trials=40)
    assert spine_task.diagnostics(TaskDefinition.from_json(doc)) == []
    result = sim.simulate(snapshot(doc), sim.Animal(animal), 9, limit_ms=20 * 60_000)
    summary = stream.summarize(result.document, None)
    assert summary.status == "ok", summary.detail


def test_a_lazy_animal_s_penalties_escalate_in_its_run():
    doc = grgl_2afc()
    result = sim.simulate(snapshot(doc), sim.Animal("silent"), 9, limit_ms=3 * 60_000)
    table = spine_stream.trial_table(result.document)
    starts = [t["atMs"] for t in table["trials"]]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    # Each trial: the 4 s wait, then 6, 12, 18 ... 30 s of penalty.
    assert gaps[:6] == [10_000, 16_000, 22_000, 28_000, 34_000, 34_000]


def test_a_definition_that_uses_none_of_this_lowers_as_before():
    doc = fixture.two_afc()
    before = lowered(copy.deepcopy(doc))
    assert not before.repeat_aborts and before.lazy is None
    assert not any(s[10] & (lowering.ESCALATE | lowering.AWAIT_LOW) for s in before.states)


@pytest.mark.parametrize("repeat, ended_by", [(True, "timeLimit"), (False, "trials")])
def test_aborts_that_repeat_never_reach_the_session_cap(repeat, ended_by):
    # An animal that never pokes aborts every trial: counted, the cap of 5 ends
    # the session; repeated uncounted, only the time limit does.
    doc = grgl_2afc(repeatAborts=repeat, sessionTrials=5)
    result = sim.simulate(snapshot(doc), sim.Animal("silent"), 9, limit_ms=5 * 60_000)
    assert result.ended_by == ended_by
    assert stream.summarize(result.document, None).status == "ok"


# --- what the editor is told -------------------------------------------------------


def with_phase(i: int, **fields) -> dict:  # noqa: ANN003
    doc = grgl_2afc()
    doc["spine"][i].update(fields)
    return doc


def with_block(**fields) -> dict:  # noqa: ANN003
    doc = grgl_2afc()
    doc["blocks"][0].update(fields)
    return doc


def with_entry(**fields) -> dict:  # noqa: ANN003
    doc = grgl_2afc()
    doc["rows"][0]["map"]["left"].update(fields)
    return doc


BAD = [
    (with_phase(0, penaltyMs=-1), "spine[0].penaltyMs"),
    (with_phase(2, penaltyMs=1000), "spine[2].penaltyMs"),
    (with_phase(0, escalateMaxMs=None), "spine[0].escalateMaxMs"),
    (with_phase(0, penaltyMs=None), "spine[0].escalateMs"),
    (with_phase(0, timeoutMs=None), "spine[0].penaltyMs"),
    (with_phase(1, escalateMs=10, escalateMaxMs=20), "spine[1].escalateMs"),
    (with_phase(2, brokenPenaltyMs=-5), "spine[2].brokenPenaltyMs"),
    (with_phase(2, holdMs=None, brokenPenaltyMs=10), "spine[2].brokenPenaltyMs"),
    (with_phase(1, awaitExit=True), "spine[1].awaitExit"),
    (with_entry(penaltyMs=-1), "rows[0].map.left.penaltyMs"),
    (with_block(holdMs={"1": 50}), "blocks[0].holdMs.1"),
    (with_block(holdMs={"2": -1}), "blocks[0].holdMs.2"),
    (with_block(biasStrength=500), "blocks[0].biasStrength"),
    (with_block(select="antibias", biasStrength=1001), "blocks[0].biasStrength"),
    (with_block(select="antibias", biasMin=600, biasMax=400), "blocks[0].biasMin"),
    (with_block(select="antibias", maxRun=0), "blocks[0].maxRun"),
]


@pytest.mark.parametrize("raw, location", BAD, ids=[loc for _, loc in BAD])
def test_each_misuse_is_a_diagnostic_at_its_field(raw, location):
    found = [d.location for d in spine_task.diagnostics(TaskDefinition.from_json(raw))]
    assert location in found, found


def test_two_escalating_waits_are_one_too_many():
    doc = grgl_2afc()
    doc["spine"].insert(0, {"phase": "wait", "on": "port", "timeoutMs": 100, "penaltyMs": 10, "escalateMs": 1,
                            "escalateMaxMs": 2})
    found = [d.location for d in spine_task.diagnostics(TaskDefinition.from_json(doc))]
    assert "spine[1].escalateMs" in found


def test_the_grgl_2afc_itself_is_clean():
    assert spine_task.diagnostics(TaskDefinition.from_json(grgl_2afc(repeatAborts=True))) == []


def test_an_awaited_well_stays_watched_through_phases_before_the_outcome():
    # A Delay between the window and the Outcome: a release there must be seen,
    # or the await would wait for one that already happened.
    doc = grgl_2afc()
    doc["spine"].insert(3, {"phase": "delay", "ms": 500})
    low = lowered(doc)
    for r, row in enumerate(doc["rows"]):
        correct = next(k for k, e in row["map"].items() if e["outcome"] == "correct")
        bit = next(i for i, (slot, channel) in enumerate(low.inputs) if slot == correct)
        delays = [s for s, p, rr in zip(low.states, low.phases, low.rows) if p == 3 and rr == r and s[1] >> bit & 1]
        assert delays, f"row {r}'s delay after {correct!r} watches that well"


def test_a_release_during_a_delay_before_the_outcome_does_not_hang_the_trial():
    doc = grgl_2afc()
    doc["spine"].insert(3, {"phase": "delay", "ms": 500})
    result = sim.simulate(snapshot(doc), sim.Animal("correct"), 9, limit_ms=5 * 60_000)
    table = spine_stream.trial_table(result.document)
    assert result.ended_by == "blocks", "every trial of the block finished"
    assert len(table["trials"]) == 20 and {t["outcome"] for t in table["trials"]} == {"correct"}


def test_a_run_cap_fits_the_core_s_count():
    # The core counts a run in a byte, saturating at 255: a cap past it never fires.
    found = [d.location for d in spine_task.diagnostics(TaskDefinition.from_json(
        with_block(select="antibias", maxRun=256)))]
    assert "blocks[0].maxRun" in found


def test_an_escalation_s_cap_is_at_least_its_base():
    found = [d.location for d in spine_task.diagnostics(TaskDefinition.from_json(
        with_phase(0, penaltyMs=40000, escalateMaxMs=30000)))]
    assert "spine[0].escalateMaxMs" in found


def test_a_stored_escalation_cap_below_its_base_is_refused():
    # Held as a pair, as a drawn N's ends are: in the editor, and by the board at SET.
    doc = grgl_2afc()
    doc["params"] = {"wait_0_escalate_max_ms": 1}
    definition = TaskDefinition.from_json(doc)
    assert "params.wait_0_escalate_max_ms" in [d.location for d in spine_task.diagnostics(definition)]
    low = spine_task._resolve(definition).lowered
    assert (low.params.index("P0"), low.params.index("LM0")) in spine_task.pairs(low)


def test_the_awaited_well_is_watched_only_up_to_the_await():
    low = lowered(grgl_2afc())
    for i, s in enumerate(low.states):
        if s[10] & lowering.AWAIT_LOW:
            bit = low.edges[s[8]][0]
            after = low.states[low.edges[s[8]][2]]
            assert not after[1] >> bit & 1, "the class timeout after the await does not watch the well"
