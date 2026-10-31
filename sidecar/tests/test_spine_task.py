"""A phase-spine task, saved and generated — `TASKS.md#spine-tasks`.

A spine definition is saved like any task and generates a sketch folder whose
only firmware is the library's: a fixed `.ino`, this rig's pins and codes, and
the lowered state table. These pin what that folder says, what the profile it
carries tells replay, and what the diagnostics catch before a flash.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import generate, lowering
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.store import TaskStore
from ephymeris_sidecar.taskdef.validate import validate
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.start_command import build_start_command
from tests.fixtures import spine as fixture

FIRMWARE = Path(__file__).resolve().parents[2] / "firmware"


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def tracer(**edits) -> TaskDefinition:
    return TaskDefinition.from_json(fixture.tracer(**edits))


def codes(definition: TaskDefinition) -> set[str]:
    return {d.code for d in validate(definition)}


def test_a_spine_definition_round_trips_and_a_legacy_one_is_untouched():
    raw = fixture.tracer()
    assert TaskDefinition.from_json(raw).to_json() == raw | {"legacyNames": [], "notes": ""}
    legacy = TaskDefinition.from_json({"id": "plain", "name": "Plain"}).to_json()
    assert "spine" not in legacy and "slots" not in legacy


def test_the_tracer_is_clean_on_a_rig_whose_edges_have_codes():
    assert validate(tracer()) == []


def test_saving_generates_a_folder_with_no_hand_written_firmware(tmp_path):
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    assert store.save(tracer()) == []
    folder = tmp_path / "tasks" / "Tasks" / "Spine Tracer"
    assert sorted(p.name for p in folder.iterdir()) == [
        "Spine Tracer.ino", "TaskPins.h", "TaskSpine.h", "task.json"
    ]
    ino = (folder / "Spine Tracer.ino").read_text(encoding="utf-8")
    assert "box_spine::setup();" in ino and "box_spine::loop();" in ino
    assert ino.index('"TaskPins.h"') < ino.index('"TaskSpine.h"') < ino.index("<BoxSpine.h>")


def test_the_table_names_pins_and_codes_from_the_rig_and_the_vocabulary(tmp_path):
    channels, vocab = registry.channels(), registry.vocabulary()
    header = generate.task_spine_h(tracer())
    port, light = channels.get("odor_port"), channels.get("trial_light")
    assert f"{{{port.index}, 0, {port.debounce_ms}, BF_ODOR_PORT_ENTER, BF_ODOR_PORT_EXIT}}" in header
    assert f"{{{light.index}, BF_TRIAL_LIGHT_ON, BF_TRIAL_LIGHT_OFF}}" in header
    assert "#define SPINE_NUM_STATES 7" in header and "#define SPINE_NUM_EDGES 2" in header
    assert '{"NT", 20UL, 1UL, ' in header and '{"T1", 1000UL, 0UL, ' in header
    pins = generate.task_pins_h(tracer())
    assert f"#define BF_ODOR_PORT_ENTER {vocab.code_of('ODOR_PORT_ENTER')}" in pins
    assert f"#define BF_TRIAL_START {vocab.code_of('TRIAL_START')}" in pins


def test_the_profile_carries_everything_replay_needs():
    profile = generate.build_profile(tracer())
    spine = profile.spine
    low = lowering.lower([p.to_json() for p in tracer().spine.phases],
                         inputs=["port"], outputs=["cue", "sample", "reward"])
    assert spine["interp"] == lowering.INTERP_VERSION
    assert spine["table"] == {"states": [list(s) for s in low.states], "edges": [list(e) for e in low.edges],
                              "phases": [0, 1, 2, 3, 3, 3, 4], "rows": [0] * 7}
    assert spine["params"] == list(low.params)
    assert spine["inputs"] == [{"slot": "port", "channel": "odor_port",
                                "rise": "ODOR_PORT_ENTER", "fall": "ODOR_PORT_EXIT"}]
    assert [o["channel"] for o in spine["outputs"]] == ["trial_light", "odor_line_1", "fluid_2"]
    assert spine["structural"] == {"sessionStart": "START_SESSION", "trialStart": "TRIAL_START",
                                   "sessionEnd": "END_SESSION"}
    # Every parameter slot is a declared field, so its value reaches the header.
    assert [f.wire_key for f in profile.config] == list(low.params)
    assert profile.live_metrics == [] and profile.end_code == registry.vocabulary().code_of("END_SESSION")


def test_the_profile_round_trips_byte_for_byte_through_the_parser(tmp_path):
    TaskStore(tmp_path, library_root=FIRMWARE).save(tracer())
    folder = tmp_path / "tasks" / "Tasks" / "Spine Tracer"
    loaded = task_profile.load_profile(folder)
    again = task_profile.parse_profile(loaded.to_json())
    assert json.dumps(again.to_json(), sort_keys=True) == json.dumps(loaded.to_json(), sort_keys=True)
    assert task_profile.profile_hash(again) == task_profile.profile_hash(loaded)


def test_a_legacy_profile_carries_no_spine_and_hashes_as_before():
    profile = task_profile.parse_profile({"taskName": "GRGL"})
    assert "spine" not in profile.to_json()


def test_the_set_lines_carry_every_parameter_and_an_override_wins():
    definition = tracer(params={"block_trials": 5})
    command = build_start_command(generate.build_profile(definition), {})
    tokens = list(command.tokens)
    assert "NT=5" in tokens and "T1=1000" in tokens and "RW1=100" in tokens and "RP1=1000" in tokens


def test_a_rig_whose_edges_have_no_codes_is_diagnosed():
    fixture.uninstall()  # the shipped channel set names no edge codes
    found = {(d.code, d.location) for d in validate(tracer())}
    assert ("SPN103", "rows[0].bind.port") in found


def test_a_vocabulary_without_the_trial_start_code_is_diagnosed():
    rig, vocab = fixture.issued_rig()
    del vocab["codes"]["TRIAL_START"]
    fixture.install(rig, vocab)
    assert "SPN104" in codes(tracer())
    assert '#error "the strobe vocabulary has no TRIAL_START' in generate.task_spine_h(tracer())


# --- the Response window, the contingency map and several rows (#101) ----------


@pytest.mark.parametrize("make", [fixture.two_afc, fixture.go_no_go], ids=["2afc", "go_no_go"])
def test_a_task_with_a_window_and_rows_round_trips_and_is_clean(make):
    raw = make()
    assert TaskDefinition.from_json(raw).to_json() == raw | {"legacyNames": [], "notes": ""}
    assert validate(TaskDefinition.from_json(raw)) == []


def test_the_go_no_go_snapshot_names_each_bit_and_annotates_each_state():
    definition = TaskDefinition.from_json(fixture.go_no_go())
    spine = generate.build_profile(definition).spine
    assert spine["interp"] == lowering.INTERP_VERSION == 3
    # One bit per channel: `sample` is two odor lines, one per row.
    assert [(o["slot"], o["channel"]) for o in spine["outputs"]] == [
        ("cue", "trial_light"), ("sample", "odor_line_1"), ("sample", "odor_line_2"), ("reward", "fluid_2")]
    assert spine["outputs"][2] == {"slot": "sample", "channel": "odor_line_2",
                                   "on": "ODOR_LINE_2_ON", "off": "ODOR_LINE_2_OFF"}
    table = spine["table"]
    assert len(table["phases"]) == len(table["rows"]) == len(table["states"])
    assert table["phases"][0] is None and table["rows"][0] is None, "the pick state is no phase's and no row's"
    assert table["states"][0][10] == lowering.STARTS_TRIAL | lowering.PICK
    assert set(table["rows"][1:]) == {0, 1}
    # Every class the two maps name is marked by exactly one state.
    marked = sorted(lowering.OUTCOME_CLASSES[s[11] - 1] for s in table["states"] if s[11])
    assert marked == ["correct", "false_alarm", "omission", "withheld"]


def test_each_row_and_entry_has_its_own_parameter_keyed_by_row_id():
    profile = generate.build_profile(TaskDefinition.from_json(fixture.two_afc()))
    fields = {f.metadata_key: (f.wire_key, f.default) for f in profile.config}
    assert fields == {
        "block_trials": ("NT", 20),
        "present_1_ms": ("T1", 1000),
        "response_2_ms": ("T2", 5000),
        "response_2_hold_ms": ("H2", 200),
        "outcome_3_ms": ("T3", 0),
        "iti_4_ms": ("T4", 3000),
        "reward_ms_odor_1": ("RW1", 100),
        "reward_permille_odor_1_right": ("RP1_2", 1000),
        "reward_ms_odor_2": ("RW2", 100),
        "reward_permille_odor_2_left": ("RP2_1", 1000),
    }
    assert [f.wire_key for f in profile.config] == profile.spine["params"]


def test_the_tracer_s_reward_keys_name_its_row():
    keys = [f.metadata_key for f in generate.build_profile(tracer()).config]
    assert keys[-2:] == ["reward_ms_r1", "reward_permille_r1"]


def test_a_go_no_go_folder_carries_its_table():
    header = generate.task_spine_h(TaskDefinition.from_json(fixture.go_no_go()))
    assert "#define SPINE_INTERP 3" in header and "#error" not in header
    assert "#define SPINE_NUM_STATES 15" in header and "#define SPINE_NUM_OUTPUTS 4" in header


def _window(d: dict) -> dict:
    return d["spine"][2]


@pytest.mark.parametrize(
    ("edit", "code", "where"),
    [
        (lambda d: _window(d).update(responses=["left", "left"]), "SPN105", "spine[2].responses"),
        (lambda d: _window(d).update(responses=["cue"]), "SPN105", "spine[2].responses"),
        (lambda d: _window(d).update(responses=[]), "SPN105", "spine[2].responses"),
        (lambda d: _window(d).pop("ms"), "SPN105", "spine[2].ms"),
        (lambda d: d["spine"].insert(3, dict(_window(d))), "SPN105", "spine"),
        (lambda d: d["spine"].pop(3), "SPN105", "spine"),
        (lambda d: d["spine"].insert(3, {"phase": "outcome", "ms": 0}), "SPN105", "spine"),
        (lambda d: d["spine"][3].update(line="reward_r"), "SPN105", "spine[3].line"),
        (lambda d: d["slots"].append({"id": "timeout", "type": "digital_in"}), "SPN105", "slots[7].id"),
        (lambda d: d["spine"].insert(0, {"phase": "outcome", "line": "reward_r", "ms": 0}), "SPN105", "spine[0]"),
        # A second Outcome would mark a trial's class twice.
        (lambda d: d["spine"].insert(1, {"phase": "outcome", "line": "reward_r", "ms": 0}), "SPN105", "spine"),
        (lambda d: d["blocks"][0].update(rows=["odor_1"]), "SPN106", "blocks[0].rows"),
        (lambda d: d["blocks"][0].update(rows=["odor_1", "odor_1", "odor_2"]), "SPN106", "blocks[0].rows"),
        (lambda d: d["rows"][1].update(id="odor_1"), "SPN106", "rows[1].id"),
        (lambda d: d["rows"][1].update(id="Odor 2"), "SPN106", "rows[1].id"),
        (lambda d: d["rows"][1].update(rewardMs=9000), "SPN106", "rows[1].rewardMs"),
        (lambda d: d["rows"][1]["bind"].update(sample="fluid_1"), "SPN107", "rows[1].bind.sample"),
        (lambda d: d["rows"][1].update(name=""), "SPN108", "rows[1].name"),
        (lambda d: d["rows"][0]["map"].pop("left"), "SPN109", "rows[0].map.left"),
        (lambda d: d["rows"][0]["map"].pop("timeout"), "SPN109", "rows[0].map.timeout"),
        (lambda d: d["rows"][0]["map"].update(port={"outcome": "correct"}), "SPN109", "rows[0].map.port"),
        (lambda d: d["rows"][0]["map"]["left"].update(outcome="great"), "SPN109", "rows[0].map.left.outcome"),
        (lambda d: d["rows"][0]["map"]["left"].update(line="port"), "SPN109", "rows[0].map.left.line"),
        (lambda d: d["rows"][0]["map"]["right"].update(rewardPermille=1001), "SPN109",
         "rows[0].map.right.rewardPermille"),
        (lambda d: d["rows"][0]["map"]["left"].update(rewardPermille=500), "SPN109",
         "rows[0].map.left.rewardPermille"),
        (lambda d: d["rows"][0]["map"]["timeout"].update(hold=True), "SPN109", "rows[0].map.timeout.hold"),
        (lambda d: _window(d).pop("holdMs"), "SPN109", "rows[0].map.right.hold"),
    ],
)
def test_each_window_and_map_problem_is_located(edit, code, where):
    raw = fixture.two_afc()
    edit(raw)
    found = {(d.code, d.location) for d in validate(TaskDefinition.from_json(raw))}
    assert (code, where) in found, found
    if code == "SPN105":  # a spine of the wrong shape is no table: its folder refuses to compile
        assert "#error" in generate.task_spine_h(TaskDefinition.from_json(raw))


def test_a_task_whose_row_ids_collide_still_saves_and_says_why(tmp_path):
    """Row ids name parameters, so two rows of one id would declare one key
    twice: the profile is refused unless the table is withheld."""
    raw = fixture.two_afc()
    raw["rows"][1]["id"] = "odor_1"
    raw["blocks"][0]["rows"] = ["odor_1"]
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    problems = store.save(TaskDefinition.from_json(raw))
    assert ("SPN106", "rows[1].id") in {(d["code"], d["location"]) for d in problems}
    profile = task_profile.load_profile(store.sketch_dir(TaskDefinition.from_json(raw)))
    assert profile.spine["table"] is None


def test_a_tracer_saved_with_one_row_keys_keeps_its_reward_values(tmp_path):
    """A one-row spine saved before rewards were keyed by row id stored
    `reward_ms` and `reward_permille`. Those values are the row's: they reach
    the profile, the folder and the START line, and a save stores them under
    the row's keys. Never the row's default in their place."""
    raw = fixture.tracer(params={"reward_ms": 250, "reward_permille": 600})
    definition = TaskDefinition.from_json(raw)
    assert validate(definition) == []
    profile = generate.build_profile(definition)
    fields = {f.metadata_key: f.default for f in profile.config}
    assert fields["reward_ms_r1"] == 250 and fields["reward_permille_r1"] == 600
    assert '{"RW1", 250UL' in generate.task_spine_h(definition)
    tokens = list(build_start_command(profile, {}).tokens)
    assert "RW1=250" in tokens and "RP1=600" in tokens

    store = TaskStore(tmp_path, library_root=FIRMWARE)
    assert store.save(definition) == []
    stored = json.loads(next(tmp_path.rglob("spine_tracer.json")).read_text(encoding="utf-8"))
    assert stored["params"] == {"reward_ms_r1": 250, "reward_permille_r1": 600}


def test_a_stored_value_no_parameter_reads_is_named_not_dropped():
    """A key the spine declares no parameter for would be ignored; the
    diagnostic names it so the value is not lost without a word."""
    raw = fixture.go_no_go(params={"reward_ms": 250, "present_9_ms": 5})
    found = {(d.code, d.location) for d in validate(TaskDefinition.from_json(raw))}
    assert {("SPN110", "params.reward_ms"), ("SPN110", "params.present_9_ms")} <= found


def test_two_rows_whose_parameter_keys_collide_are_diagnosed(tmp_path):
    """Row `odor_far` paying on slot `right` and row `odor` paying on slot
    `far_right` would both be `reward_permille_odor_far_right`."""
    raw = fixture.two_afc()
    raw["slots"].insert(3, {"id": "far_right", "type": "digital_in"})
    raw["spine"][2]["responses"] = ["left", "right", "far_right"]
    first, second = raw["rows"]
    first.update(id="odor_far", map={"right": {"outcome": "correct", "line": "reward_r", "rewardPermille": 1000},
                                     "left": {"outcome": "wrong_response"},
                                     "far_right": {"outcome": "wrong_response"},
                                     "timeout": {"outcome": "omission"}})
    second.update(id="odor", map={"far_right": {"outcome": "correct", "line": "reward_l", "rewardPermille": 1000},
                                  "left": {"outcome": "wrong_response"},
                                  "right": {"outcome": "wrong_response"},
                                  "timeout": {"outcome": "omission"}})
    raw["blocks"][0]["rows"] = ["odor_far", "odor"]
    definition = TaskDefinition.from_json(raw)
    found = {(d.code, d.location) for d in validate(definition)}
    assert ("SPN106", "rows[1].id") in found
    store = TaskStore(tmp_path, library_root=FIRMWARE)
    store.save(definition)
    assert task_profile.load_profile(store.sketch_dir(definition)).spine["table"] is None


def test_two_windows_are_one_problem_not_a_map_problem_per_row():
    raw = fixture.two_afc()
    raw["spine"].insert(3, dict(raw["spine"][2]))
    found = [(d.code, d.location) for d in validate(TaskDefinition.from_json(raw))]
    assert ("SPN105", "spine") in found
    assert not [f for f in found if f[0] == "SPN109"]


def test_a_table_over_the_ram_budget_is_refused_by_name():
    """The table sits in the board's RAM. A legal 23-row 2AFC is 254 states,
    which leaves a Mega too little for its stack."""
    raw = fixture.two_afc()
    raw["rows"] = [dict(raw["rows"][i % 2], id=f"row_{i}", name=f"Row {i}") for i in range(19)]
    raw["blocks"][0]["rows"] = [r["id"] for r in raw["rows"]]
    definition = TaskDefinition.from_json(raw)
    problems = [d for d in validate(definition) if d.code == "SPN105"]
    assert [d.location for d in problems] == ["spine"] and "RAM" in problems[0].message
    assert "#error" in generate.task_spine_h(definition)
    raw["rows"], raw["blocks"][0]["rows"] = raw["rows"][:18], raw["blocks"][0]["rows"][:18]
    assert validate(TaskDefinition.from_json(raw)) == []


def test_a_tables_bytes_are_its_rows_at_the_c_structs_sizes():
    low = generate.build_profile(TaskDefinition.from_json(fixture.go_no_go())).spine["table"]
    assert lowering.table_bytes(len(low["states"]), len(low["edges"])) == \
        len(low["states"]) * lowering.STATE_ROW_BYTES + len(low["edges"]) * lowering.EDGE_ROW_BYTES


@pytest.mark.skipif(shutil.which("clang++") is None and shutil.which("g++") is None, reason="no host C++ compiler")
def test_the_row_sizes_are_boxinterp_hs_structs_as_avr_packs_them(tmp_path):
    """AVR aligns nothing, so a struct's size there is its members' sizes. A host
    build packed to 1 byte gives the same: a member added to either struct moves it."""
    source = tmp_path / "sizes.cpp"
    source.write_text(
        "#include <cstdio>\n#pragma pack(push, 1)\n#include \"BoxInterp.h\"\n#pragma pack(pop)\n"
        "int main() { std::printf(\"%u %u\", (unsigned)sizeof(InterpStateRow), (unsigned)sizeof(InterpEdgeRow)); }\n",
        encoding="utf-8")
    binary = tmp_path / "sizes"
    compiler = shutil.which("clang++") or shutil.which("g++")
    subprocess.run([compiler, "-std=c++11", f"-I{FIRMWARE / 'libraries' / 'BehaviorBox'}", str(source),
                    "-o", str(binary)], check=True)
    out = subprocess.run([str(binary)], capture_output=True, text=True, check=True).stdout
    assert out == f"{lowering.STATE_ROW_BYTES} {lowering.EDGE_ROW_BYTES}"


def test_a_map_on_a_spine_with_no_window_is_diagnosed():
    raw = fixture.tracer()
    raw["rows"][0]["map"] = {"timeout": {"outcome": "omission"}}
    assert ("SPN109", "rows[0].map") in {(d.code, d.location) for d in validate(TaskDefinition.from_json(raw))}


def test_a_table_over_the_format_s_size_is_diagnosed():
    raw = fixture.go_no_go()
    raw["rows"] = [dict(raw["rows"][i % 2], id=f"row_{i}", name=f"Row {i}") for i in range(40)]
    raw["blocks"][0]["rows"] = [r["id"] for r in raw["rows"]]
    found = {(d.code, d.location) for d in validate(TaskDefinition.from_json(raw))}
    assert ("SPN105", "spine") in found


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        (lambda d: d["rows"][0]["bind"].pop("sample"), "SPN101"),
        (lambda d: d["rows"][0]["bind"].update(sample="no_such_line"), "SPN101"),
        (lambda d: d["rows"][0]["bind"].update(port="fluid_2"), "SPN102"),
        (lambda d: d["spine"].pop(), "SPN105"),
        (lambda d: d["spine"].insert(0, {"phase": "juggle"}), "SPN105"),
        (lambda d: d["spine"][0].update(on="cue"), "SPN105"),
        (lambda d: d["rows"].append(dict(d["rows"][0], id="r2", name="Odor 2")), "SPN106"),
        (lambda d: d["blocks"][0].update(rows=["nope"]), "SPN106"),
        (lambda d: d["rows"][0].update(rewardMs=9000), "SPN106"),
        (lambda d: d["rows"][0]["bind"].update(sample="trial_light"), "SPN107"),
        (lambda d: d["rows"][0].update(name="  "), "SPN108"),
    ],
)
def test_each_problem_is_located_rather_than_refused(edit, code):
    raw = fixture.tracer()
    edit(raw)
    assert code in codes(TaskDefinition.from_json(raw))
