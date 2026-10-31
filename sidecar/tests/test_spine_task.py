"""A phase-spine task, saved and generated — `TASKS.md#spine-tasks`.

A spine definition is saved like any task and generates a sketch folder whose
only firmware is the library's: a fixed `.ino`, this rig's pins and codes, and
the lowered state table. These pin what that folder says, what the profile it
carries tells replay, and what the diagnostics catch before a flash.
"""

from __future__ import annotations

import json
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
    assert spine["table"] == {"states": [list(s) for s in low.states], "edges": [list(e) for e in low.edges]}
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
