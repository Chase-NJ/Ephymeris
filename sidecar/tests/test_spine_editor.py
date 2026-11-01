"""What the spine task editor reads from the sidecar — `TASKS.md#the-spine-editor`.

The editor holds an unsaved definition and draws only what `tasks.preview`
answers for it: the seeds a new task starts from, each diagnostic's target,
the channels each slot can bind, the block sequence and the RAM meter. These pin
those answers, and that a task built from a seed on this rig saves clean.
"""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskdef import lowering, seeds, spine as spine_module
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.store import TaskStore
from ephymeris_sidecar.taskdef.validate import validate
from tests.fixtures import spine as fixture
from tests.wire import dispatch, running_app

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


#: How an operator binds each seed's slots on the shipped rig, row by row:
#: one channel per slot, a row-varying slot on a line of its own per row.
BINDINGS = {
    "two_afc": [{"port": "odor_port", "cue": "trial_light", "sample": line, "left": "left_well",
                 "right": "right_well", "reward_l": "fluid_1", "reward_r": "fluid_2"}
                for line in ("odor_line_1", "odor_line_2")],
    "go_no_go": [{"port": "odor_port", "cue": "trial_light", "sample": line, "resp": "right_well",
                  "reward": "fluid_2"} for line in ("odor_line_1", "odor_line_2")],
    "dnms": [{"port": "odor_port", "cue": "trial_light", "sample": sample, "test": test, "match": "left_well",
              "non_match": "right_well", "reward_l": "fluid_1", "reward_r": "fluid_2"}
             for sample, test in (("odor_line_1", "odor_line_3"), ("odor_line_2", "odor_line_4"),
                                  ("odor_line_1", "odor_line_4"), ("odor_line_2", "odor_line_3"))],
    "trace": [{"cs": line, "reward": "fluid_2"} for line in ("odor_line_1", "odor_line_2")],
    "ratio": [{"lever": "right_well", "light": "trial_light", "reward": "fluid_2"}],
}


def built(seed_id: str) -> dict:
    """A new task from a seed, as the editor builds one: the seed's document,
    named, every row named and bound on this rig."""
    document = copy.deepcopy(next(s for s in seeds.SEEDS if s["id"] == seed_id)["definition"])
    document.update(id=f"seed_{seed_id}", name=f"Seed {seed_id}")
    for r, (row, bind) in enumerate(zip(document["rows"], BINDINGS[seed_id], strict=True)):
        row["name"] = f"Row {r + 1}"
        row["bind"] = dict(bind)
    return document


def test_the_seeds_are_the_five_the_adr_names():
    assert [s["id"] for s in seeds.SEEDS] == ["two_afc", "go_no_go", "dnms", "trace", "ratio"]
    assert set(BINDINGS) == {s["id"] for s in seeds.SEEDS}


@pytest.mark.parametrize("seed", seeds.SEEDS, ids=lambda s: s["id"])
def test_a_seed_carries_phases_and_no_names(seed):
    """No row is named and nothing is bound: a new task asks for both, on the
    rows that need them, rather than guessing (`TASKS.md#what-a-definition-holds`)."""
    document = seed["definition"]
    assert document["spine"] and document["blocks"] and document["params"] == {}
    assert all(row["name"] == "" and row["bind"] == {} for row in document["rows"])
    problems = validate(TaskDefinition.from_json(document))
    assert {d.code for d in problems} == {"SPN101", "SPN108"}
    assert {d.target["kind"] for d in problems} == {"row"}


@pytest.mark.parametrize("seed_id", list(BINDINGS))
def test_a_seed_named_and_bound_on_this_rig_is_clean(seed_id):
    assert validate(TaskDefinition.from_json(built(seed_id))) == []


def _edit_a_contingency(seed_id: str, document: dict) -> dict:
    """One edit an operator makes to a seed: a binding changed, and one map entry
    (or, with no window, the row's own reward) changed."""
    row = document["rows"][0]
    if seed_id == "ratio":
        row["bind"]["lever"] = "left_well"
    else:
        slot = next(k for k, v in row["bind"].items() if v.startswith("odor_line"))
        for r in document["rows"]:
            r["bind"][slot] = r["bind"][slot].replace("odor_line_", "odor_line_1")
    if "map" in row:
        key = next(k for k, e in row["map"].items() if e["outcome"] == "correct")
        row["map"][key]["rewardPermille"] = 800
    else:
        row["rewardPermille"] = 900
    return document


arduino = shutil.which("arduino-cli")


@pytest.mark.parametrize("seed_id", list(BINDINGS))
def test_a_task_built_from_a_seed_saves_lowers_and_compiles(seed_id, tmp_path):
    document = _edit_a_contingency(seed_id, built(seed_id))
    definition = TaskDefinition.from_json(document)
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    assert store.save(definition) == []
    assert spine_module._resolve(definition).lowered is not None
    folder = store.sketch_dir(definition)
    assert "#error" not in (folder / "TaskSpine.h").read_text(encoding="utf-8")
    if arduino is None and os.environ.get("REQUIRE_ARDUINO_CLI") != "1":
        pytest.skip("no arduino-cli: saved and lowered, not compiled")
    built_ = subprocess.run([arduino, "compile", "--fqbn", "arduino:avr:mega",
                             "--libraries", str(FIRMWARE / "libraries"), str(folder)],
                            capture_output=True, text=True)
    assert built_.returncode == 0, built_.stdout + built_.stderr


def test_the_task_list_says_which_tasks_are_spines(tmp_path):
    """The landing names a spine task's rows, never a selection mode it does not read."""
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    store.save(TaskDefinition.from_json(built("dnms")))
    store.save(TaskDefinition.from_json({"id": "plain", "name": "Plain"}))
    entries = {e["id"]: e for e in store.list_entries()}
    assert entries["seed_dnms"]["spine"] is True and entries["seed_dnms"]["trials"] == 4
    assert entries["plain"]["spine"] is False


# --------------------------------------------------------------------------- #
# Each diagnostic's target
# --------------------------------------------------------------------------- #


def targets(raw: dict) -> dict[tuple[str, str], dict]:
    return {(d.code, d.location): d.target for d in validate(TaskDefinition.from_json(raw))}


def _hold_on_an_unheld_input() -> dict:
    raw = fixture.two_afc()
    raw["spine"].insert(0, {"phase": "hold", "on": "left", "ms": 100})
    return raw


def _unnamed_first_row() -> dict:
    raw = fixture.two_afc()
    raw["rows"][0]["name"] = " "
    return raw


@pytest.mark.parametrize(
    ("raw", "found", "where"),
    [
        (_hold_on_an_unheld_input(), ("SPN111", "spine[0].on"), {"kind": "phase", "index": 0}),
        (_unnamed_first_row(), ("SPN108", "rows[0].name"), {"kind": "row", "index": 0}),
        (fixture.two_afc(blocks=[{"id": "a", "rows": ["odor_1", "odor_2"], "trials": 10, "next": "nope"}]),
         ("SPN106", "blocks[0].next"), {"kind": "block", "index": 0}),
        (fixture.two_afc(slots=[*fixture.two_afc()["slots"], {"id": "timeout", "type": "digital_in"}]),
         ("SPN105", "slots[7].id"), {"kind": "slot", "index": 7}),
        (fixture.two_afc(sessionTrials=0), ("SPN106", "sessionTrials"), {"kind": "session", "index": None}),
        (fixture.two_afc(params={"no_such_key": 3}), ("SPN110", "params.no_such_key"),
         {"kind": "task", "index": None}),
        # A stored value is shown where its parameter is: the block whose
        # criterion it is, the phase whose counter it is.
        (fixture.reversal(params={"block_a_criterion_of": 5}), ("SPN106", "params.block_a_criterion_of"),
         {"kind": "block", "index": 0}),
        (fixture.variable_ratio(1, 9, params={"counter_0_count": 10}), ("SPN105", "params.counter_0_count"),
         {"kind": "phase", "index": 0}),
    ],
)
def test_each_spine_diagnostic_targets_its_phase_row_or_block(raw, found, where):
    got = targets(raw)
    assert found in got, got
    assert got[found] == where


def test_the_ram_budget_s_diagnostic_targets_the_meter():
    raw = fixture.two_afc()
    rows = [dict(raw["rows"][i % 2], id=f"row_{i}", name=f"Row {i}") for i in range(19)]
    raw["rows"], raw["blocks"][0]["rows"] = rows, [r["id"] for r in rows]
    ram = [d for d in validate(TaskDefinition.from_json(raw)) if "RAM" in d.message]
    assert [(d.code, d.target) for d in ram] == [("SPN105", {"kind": "ram", "index": None})]


def test_a_trial_table_task_s_diagnostics_target_their_rows_too():
    raw = {"id": "plain", "name": "Plain", "trials": [{"odorChannel": "", "onsetStrobe": "", "label": ""}]}
    found = [d.to_json() for d in validate(TaskDefinition.from_json(raw))]
    on_row = [d for d in found if d["location"].startswith("trials[0]")]
    assert on_row and all(d["target"] == {"kind": "row", "index": 0} for d in on_row)
    assert all(d["target"] == {"kind": "task", "index": None} for d in found if d["location"] == "trials")


# --------------------------------------------------------------------------- #
# What the editor draws: `spine.editor_view`
# --------------------------------------------------------------------------- #


def view(raw: dict) -> dict:
    return spine_module.editor_view(TaskDefinition.from_json(raw))


@pytest.mark.parametrize("raw", [fixture.tracer(), fixture.two_afc(), fixture.reversal(),
                                 fixture.progressive_ratio(), fixture.held_trial()],
                         ids=["tracer", "2afc", "reversal", "pr", "held"])
def test_the_meter_is_the_budget_s_own_arithmetic(raw):
    """Its bytes are what SPN105 judges, and its parts add up to them."""
    definition = TaskDefinition.from_json(raw)
    ram = spine_module.editor_view(definition)["ram"]
    assert ram["bytes"] == spine_module.task_ram_bytes(spine_module._resolve(definition).lowered)
    assert sum(part["bytes"] for part in ram["parts"]) == ram["bytes"]
    assert ram["budget"] == spine_module.TASK_RAM_MAX == 5000


def _afc_rows(n: int) -> dict:
    raw = fixture.two_afc()
    raw["rows"] = [dict(raw["rows"][i % 2], id=f"row_{i}", name=f"Row {i}") for i in range(n)]
    raw["blocks"][0]["rows"] = [r["id"] for r in raw["rows"]]
    return raw


def test_the_meter_of_the_largest_2afc_matches_the_documented_figure():
    """TASKS.md#spine-diagnostics: an 18-row 2AFC of one block is 4978 B; 19 rows are 5242 B, over."""
    assert view(_afc_rows(18))["ram"]["bytes"] == 4978
    over = view(_afc_rows(19))["ram"]
    assert over["bytes"] == 5242 and over["bytes"] > over["budget"]


def test_a_spine_that_cannot_be_lowered_has_no_bytes_to_meter():
    raw = fixture.two_afc()
    raw["spine"].pop()  # no ITI
    assert view(raw)["ram"] == {"bytes": None, "budget": 5000, "parts": []}


def test_each_slot_offers_the_channels_of_its_own_type():
    slots = {s["id"]: s for s in view(fixture.two_afc())["slots"]}
    assert slots["port"]["type"] == "digital_in" and slots["port"]["mode"] is None
    assert {"odor_port", "left_well", "right_well"} <= set(slots["port"]["channels"])
    assert "trial_light" not in slots["port"]["channels"]
    assert {"trial_light", "odor_line_1", "fluid_2", "vacuum"} <= set(slots["cue"]["channels"])
    assert "sync_out" not in slots["cue"]["channels"], "never the sync line"
    assert "left_well" not in slots["cue"]["channels"]


def test_a_driven_slot_offers_only_its_type_and_mode():
    fixture.install(*fixture.issued_rig(driven=True))
    slots = {s["id"]: s for s in view(fixture.stimulus())["slots"]}
    assert slots["light"]["channels"] == ["light"]
    assert slots["tone"]["channels"] == ["tone"]
    assert slots["laser"]["channels"] == ["laser"] and slots["laser"]["mode"] == "train"
    assert "laser" not in slots["cue"]["channels"], "a train is not a level line"


def test_the_block_sequence_says_what_follows_each_block():
    reversal = view(fixture.reversal())
    assert reversal["blocks"] == [{"id": "a", "next": 1}, {"id": "b", "next": None}]
    assert reversal["sessionEnds"] is True
    bandit = view(fixture.bandit())
    assert bandit["blocks"] == [{"id": "a", "next": 1}, {"id": "b", "next": 0}]
    assert bandit["sessionEnds"] is False, "the blocks loop; only sessionTrials ends it"


def test_a_stored_value_is_shown_on_what_it_tunes():
    stored = view(fixture.reversal(params={"block_a_criterion_of": 9, "iti_4_ms": 5000, "stray": 1}))["stored"]
    assert sorted(stored, key=lambda s: s["key"]) == [
        {"key": "block_a_criterion_of", "value": 9, "target": {"kind": "block", "index": 0}},
        {"key": "iti_4_ms", "value": 5000, "target": {"kind": "phase", "index": 4}},
    ], "a key no parameter reads is SPN110's, not a stored value"


# --------------------------------------------------------------------------- #
# On the wire
# --------------------------------------------------------------------------- #


async def test_the_palette_serves_the_seeds_and_the_model_s_own_lists(tmp_path):
    async with running_app(tmp_path / "app") as app:
        palette = await dispatch(app, "tasks.spinePalette")
    assert [s["id"] for s in palette["seeds"]] == [s["id"] for s in seeds.SEEDS]
    assert palette["seeds"][0]["definition"] == seeds.SEEDS[0]["definition"]
    assert palette["phases"] == list(lowering.PHASES)
    assert palette["outcomeClasses"] == list(lowering.OUTCOME_CLASSES)
    assert palette["selections"] == list(lowering.SELECTIONS)


async def test_a_preview_of_a_seed_carries_the_spine_view_and_located_problems(tmp_path):
    async with running_app(tmp_path / "app") as app:
        fixture.install()
        reply = await dispatch(app, "tasks.preview", definition=seeds.SEEDS[0]["definition"])
        legacy = await dispatch(app, "tasks.preview", definition={"id": "plain", "name": "Plain"})
    assert reply["spine"]["ram"]["bytes"] is not None and reply["spine"]["ram"]["budget"] == 5000
    assert [s["id"] for s in reply["spine"]["slots"]] == [s["id"] for s in seeds.SEEDS[0]["definition"]["slots"]]
    assert {d["target"]["kind"] for d in reply["diagnostics"]} == {"row"}
    assert reply["profile"]["spine"]["spine"] == seeds.SEEDS[0]["definition"]["spine"]
    assert legacy["spine"] is None
