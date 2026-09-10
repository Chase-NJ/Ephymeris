"""Task profiles: the model, the generator, the store, and the traps.

Everything here fails QUIETLY without a check. The generator writes C that
compiles either way, so a wrong pin is a valve that never fires and a wrong
strobe code is an event that decodes as something else — neither raises, and
neither is visible in a session that otherwise looks normal.

`conftest.py` sets `EPHYMERIS_WIRE_VALIDATE=1` globally, so the payload shapes
built here are checked against `protocol/schema.py` on the way out.
"""

from __future__ import annotations

import json

import pytest

from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import generate, store
from tests.fixtures import task_definitions as presets
from ephymeris_sidecar.taskdef.model import (
    StageRow,
    TaskDefinition,
    TaskDefinitionError,
    TrialTypeDef,
)
from ephymeris_sidecar.taskdef.validate import validate
from ephymeris_sidecar.tasks.start_command import (
    START_LINE_MAX,
    build_start_command,
    with_trial_seed,
)


@pytest.fixture(autouse=True)
def _shipped_wiring():
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


def a_task(**edits) -> TaskDefinition:
    """The shipped 2-odor discrimination, with edits applied."""
    from dataclasses import replace

    return replace(presets.instantiate("grgl_2odor", "probe"), **edits)


def codes(definition: TaskDefinition) -> set[str]:
    return {d.code for d in validate(definition)}


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


def test_a_document_that_is_not_a_definition_is_refused():
    for bad in (None, [], "task", {"id": "x"}, {"id": "x", "name": ""}):
        with pytest.raises(TaskDefinitionError):
            TaskDefinition.from_json(bad)


def test_an_id_that_would_not_survive_being_a_filename_is_refused():
    for bad in ("../evil", "Has Caps", "", "9leading", "x" * 60):
        with pytest.raises(TaskDefinitionError):
            TaskDefinition.from_json({"id": bad, "name": "Fine"})


def test_an_unfinished_trial_row_parses_and_is_reported_rather_than_refused():
    """A half-filled row is an incomplete TASK, not a non-definition.

    It used to be refused at parse time, which meant `tasks.preview` failed
    outright the moment "Add trial type" was pressed: the state machine, the
    parameter rail and every other diagnostic left the screen until both
    dropdowns were filled. Nothing caught it while every task started from a
    preset with its rows already filled.
    """
    definition = TaskDefinition.from_json({
        "id": "fresh",
        "name": "Fresh",
        "trials": [
            {"odorChannel": "", "onsetStrobe": "", "isGo": True, "label": ""}
        ],
    })
    assert definition.trials[0].odor_channel == ""

    found = {(d.code, d.location) for d in validate(definition)}
    assert ("TSK101", "trials[0].odorChannel") in found
    assert ("TSK104", "trials[0].onsetStrobe") in found
    # And the empty row says "not filled in yet" rather than naming '' as a
    # channel this rig has lost — a different thing to do about it.
    message = next(
        d.message for d in validate(definition) if d.location == "trials[0].odorChannel"
    )
    assert "no stimulus channel yet" in message


def test_a_name_that_would_not_survive_being_a_sketch_folder_is_refused():
    # It becomes `<name>/<name>.ino`, which is arduino-cli's own rule.
    for bad in ("../evil", "trailing/slash", "", "x" * 60):
        with pytest.raises(TaskDefinitionError):
            TaskDefinition.from_json({"id": "ok", "name": bad})


def test_a_definition_round_trips():
    original = presets.instantiate("shaping_right", "probe", "Probe")
    assert TaskDefinition.from_json(original.to_json()) == original


def test_a_true_weight_is_not_a_one():
    """`True` is an int in Python and would silently become weight 1."""
    with pytest.raises(TaskDefinitionError):
        TrialTypeDef.from_json(
            {"odorChannel": "odor_line_1", "onsetStrobe": "ODOR_1_ON", "weight": True}
        )


def test_a_definition_saved_before_reward_time_existed_pays_what_it_paid():
    """Every fluid line paid 100 ms then; a row without the key reads as that."""
    row = TrialTypeDef.from_json({"odorChannel": "odor_line_1", "onsetStrobe": "ODOR_1_ON"})
    assert row.reward_time == 100
    assert row.to_json()["rewardTime"] == 100
    with pytest.raises(TaskDefinitionError):
        TrialTypeDef.from_json(
            {"odorChannel": "odor_line_1", "onsetStrobe": "ODOR_1_ON", "rewardTime": True}
        )


# --------------------------------------------------------------------------- #
# The presets
# --------------------------------------------------------------------------- #


def test_every_preset_validates_and_generates_against_the_shipped_wiring():
    """If a preset does not run on the wiring the app ships with, it is the
    preset that is wrong — nothing else in the app has been touched."""
    for preset in presets.PRESETS:
        definition = presets.instantiate(preset["id"], preset["id"])
        assert validate(definition) == [], preset["id"]
        profile = generate.build_profile(definition)
        assert profile.config and profile.strobes and profile.live_metrics


def test_every_preset_fits_the_start_line():
    """Checked rather than trusted: `readLineInto()` truncates in silence, so an
    over-declared profile runs on whichever values happened to fit."""
    for preset in presets.PRESETS:
        definition = presets.instantiate(preset["id"], preset["id"])
        profile = generate.build_profile(definition)
        config = {f.metadata_key: f.default for f in profile.config}
        line = with_trial_seed(build_start_command(profile, config), 2147483646)
        assert len(line) <= START_LINE_MAX, (preset["id"], len(line))


def test_a_preset_is_a_starting_point_not_a_task():
    """Instantiating twice from one preset yields two independent tasks. If the
    preset's own id came through, the second would overwrite the first."""
    first = presets.instantiate("grgl_2odor", "cohort_a", "Cohort A")
    second = presets.instantiate("grgl_2odor", "cohort_b", "Cohort B")
    assert (first.id, first.name) == ("cohort_a", "Cohort A")
    assert (second.id, second.name) == ("cohort_b", "Cohort B")
    assert first.trials == second.trials


# --------------------------------------------------------------------------- #
# The generator — where a wrong answer still compiles
# --------------------------------------------------------------------------- #


def test_the_odor_table_is_in_declaration_order_not_pin_order():
    """THE TRAP THIS WHOLE FILE EXISTS FOR.

    `Odors[i]` is odor line i+1, and the pins behind those lines are NOT
    monotonic — 22,24,26,28,30,32 then 23,25,27,29,31,33. `of_kind()` sorts by
    pin, so using a position from it as an odor index puts line 7 second and
    swaps ten of the twelve lines. The sketch compiles, drives the wrong valve,
    and announces it with the wrong onset code; every trial still looks correct
    in the record.
    """
    pins = generate.task_pins_h(a_task())
    assert "#define BOX_ODOR_PINS {22, 24, 26, 28, 30, 32, 23, 25, 27, 29, 31, 33}" in pins


def test_an_onset_code_is_the_vocabulary_s_own_never_derived():
    """The codes are not contiguous — the onsets run 101-109 and then 114-116,
    because 110-113 are retired codes 29 recorded sessions contain. Odor 9 is
    109 and odor 10 is 114, so anything computing one from an index is wrong by
    construction."""
    vocab = registry.vocabulary()
    definition = a_task(trials=[
        TrialTypeDef("odor_line_7", "ODOR_7_ON", True, "right_well", "fluid_2"),
        TrialTypeDef("odor_line_12", "ODOR_12_ON", True, "left_well", "fluid_0"),
    ])
    pins = generate.task_pins_h(definition)
    assert f"#define BF_ODOR_7_ON {vocab.code_of('ODOR_7_ON')}" in pins
    assert f"#define BF_ODOR_12_ON {vocab.code_of('ODOR_12_ON')}" in pins
    # ...and the table indexes the same declaration-ordered list the pins do.
    trials = generate.task_trials_h(definition)
    assert "Odors[6]" in trials and "Odors[11]" in trials


def test_the_trial_table_reproduces_the_hand_written_one():
    """The shipped `GRGL/TaskTrials.h` was written by hand before any of this
    existed. Generating something different from the same task would mean the
    generator and the firmware disagree about what GRGL is."""
    trials = generate.task_trials_h(a_task())
    assert (
        "TrialType(true, Odors[0], rightWell, 2, BF_ODOR_1_ON, BF_FLUID_R, "
        "BF_STOP_FLUID_G_R, 100)" in trials
    )
    assert (
        "TrialType(true, Odors[2], leftWell, 0, BF_ODOR_3_ON, BF_FLUID_L, "
        "BF_STOP_FLUID_G_L, 100)" in trials
    )
    # Not const: the last argument is overwritten from the START line.
    assert "static TrialType kTrials[]" in trials
    assert "static const TrialType" not in trials


def test_the_reward_volume_rides_the_row_into_the_table_and_the_wire():
    """Two conditions paying from ONE fluid line may pay differently -- that is
    the whole reason the volume moved off the line and onto the type."""
    from dataclasses import replace

    task = a_task()
    task = replace(task, trials=[
        replace(task.trials[0], reward_time=150),
        replace(task.trials[1], reward_time=80),
    ])
    trials = generate.task_trials_h(task)
    assert "BF_STOP_FLUID_G_R, 150)" in trials
    assert "BF_STOP_FLUID_G_L, 80)" in trials
    profile = generate.build_profile(task)
    by_key = {f.wire_key: f for f in profile.config}
    assert by_key["RW1"].default == 150 and by_key["RW2"].default == 80
    assert by_key["RW1"].group == "Reward volume"
    assert not any(k.startswith("FL") for k in by_key)


def test_a_reward_field_is_read_off_the_row_never_out_of_params():
    """`params` merges only catalogue fields. A stale `reward_time_1` entry --
    say from a row that was deleted and re-added -- must not reach the wire."""
    from dataclasses import replace

    task = replace(a_task(), params={"reward_time_1": 999})
    profile = generate.build_profile(task)
    assert next(f for f in profile.config if f.wire_key == "RW1").default == 100


def test_the_stage_count_and_its_key_list_always_agree():
    """A key list LONGER than the count writes past the end of `stage[]`. The
    two are emitted together for exactly this reason."""
    for n in (1, 2, 5, 8):
        definition = a_task(stages=[StageRow(trials=i * 10) for i in range(n)])
        pins = generate.task_pins_h(definition)
        assert f"#define NUM_STAGES {n}" in pins
        keys = " ".join(f"P_STAGE({i})" for i in range(n))
        assert f"#define BOX_STAGE_KEY_LIST {keys}" in pins


def test_the_trial_count_and_its_pool_keys_always_agree():
    trials = [
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2"),
        TrialTypeDef("odor_line_2", "ODOR_2_ON", True, "right_well", "fluid_2"),
        TrialTypeDef("odor_line_3", "ODOR_3_ON", True, "left_well", "fluid_0"),
    ]
    pins = generate.task_pins_h(a_task(trials=trials))
    assert "#define BOX_MAX_TRIAL_TYPES 3" in pins
    assert 'P_INT("PW3", poolWeights[2])' in pins
    assert 'P_INT("PW4"' not in pins


def test_the_trial_count_and_its_reward_keys_always_agree():
    """Same pairing rule as the pool list, and the no-go slot keeps its key so
    the list is exactly BOX_MAX_TRIAL_TYPES long; only task.json omits it."""
    trials = [
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2"),
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
        TrialTypeDef("odor_line_3", "ODOR_3_ON", True, "left_well", "fluid_0"),
    ]
    definition = a_task(trials=trials)
    pins = generate.task_pins_h(definition)
    assert "#define BOX_MAX_TRIAL_TYPES 3" in pins
    assert (
        '#define BOX_REWARD_KEY_LIST P_INT("RW1", rewardTimes[0]) '
        'P_INT("RW2", rewardTimes[1]) P_INT("RW3", rewardTimes[2])' in pins
    )
    assert 'P_INT("RW4"' not in pins
    keys = {f.wire_key for f in generate.build_profile(definition).config}
    assert "RW1" in keys and "RW3" in keys and "RW2" not in keys
    # An empty table: bare macros, not the guarded four-slot defaults.
    empty = generate.task_pins_h(a_task(trials=[]))
    assert "#define BOX_REWARD_KEY_LIST\n" in empty
    assert "#define BOX_POOL_KEY_LIST\n" in empty


def test_a_one_row_ramp_declares_no_stage_group_and_no_engage_field():
    """Row 0 is live from trial 0 by construction — `liveStage()` never reads
    its count — so a task that does not ramp has no "Stage 0" to speak of."""
    profile = generate.build_profile(a_task())
    groups = {f.group for f in profile.config}
    assert "Holds & windows" in groups and "Stage 0" not in groups
    assert not any(f.wire_key == "S0T" for f in profile.config)


def test_a_ramped_task_declares_every_row_in_full():
    """A single field per ramped value would appear to work and then be silently
    overwritten around trial 15-20, when the firmware rewrites all four from the
    next `stage[]` row."""
    profile = generate.build_profile(presets.instantiate("shaping_right", "probe"))
    for row in range(5):
        keys = {f.wire_key for f in profile.config}
        for suffix in ("P", "H", "W", "O"):
            assert f"S{row}{suffix}" in keys, (row, suffix)
        assert (f"S{row}T" in keys) == (row > 0)


def test_the_selection_mode_reaches_the_firmware():
    assert "#define BOX_SELECTION_MODE BOX_SELECT_ANTIBIAS" in generate.task_pins_h(a_task())
    assert "#define BOX_SELECTION_MODE BOX_SELECT_POOL" in generate.task_pins_h(
        a_task(selection_mode="pool")
    )
    weighted = generate.task_pins_h(a_task(selection_mode="weighted"))
    assert "#define BOX_SELECTION_MODE BOX_SELECT_WEIGHTED" in weighted
    assert "#define BOX_SELECT_WEIGHTED 2" in weighted


def test_an_unknown_selection_mode_is_refused_not_defaulted():
    with pytest.raises(TaskDefinitionError):
        TaskDefinition.from_json({"id": "x", "name": "X", "selectionMode": "novelty"})


def test_the_weights_are_front_row_only_where_they_are_read():
    """Under plain anti-bias the weight column does nothing, so it folds behind
    the advanced disclosure and the mapping step's quick-tune strip skips it."""
    def weight_fields(mode):
        return [f for f in generate.build_profile(a_task(selection_mode=mode)).config
                if f.wire_key.startswith("PW")]
    assert all(f.advanced for f in weight_fields("antibias"))
    assert not any(f.advanced for f in weight_fields("pool"))
    assert not any(f.advanced for f in weight_fields("weighted"))
    assert "ITS side" in weight_fields("weighted")[0].help


def test_a_no_go_type_carries_the_sentinel_and_no_reward():
    definition = a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2",
                     label="Go right"),
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
    ])
    assert validate(definition) == []
    trials = generate.task_trials_h(definition)
    assert "TrialType(false, Odors[4], SENTINEL, SENTINEL, BF_ODOR_5_ON, 0, 0, 0)" in trials


def test_a_repin_moves_the_generated_header_and_nothing_else():
    """A task profile names channels and never numbers, so re-wiring changes
    what every task compiles to while its identity is unchanged."""
    from ephymeris_sidecar.hardware import store as rig_store

    before = generate.task_pins_h(a_task())
    doc = rig_store.default_document()
    doc["pins"]["odor_line_1"]["index"] = 12
    registry.set_rig_source(lambda: doc)
    after = generate.task_pins_h(a_task())

    assert "{22, 24," in before and "{12, 24," in after
    # The trial table names Odors[0] either way -- the indirection is the point.
    assert generate.task_trials_h(a_task()).count("Odors[0]") == 1


def test_the_generated_profile_is_parsed_by_the_same_code_an_authored_one_is():
    """Round-tripping through `parse_profile` is what subjects a generated
    profile to every check an authored one gets — a duplicate wire key, a
    reserved key, a default of the wrong type."""
    profile = generate.build_profile(presets.instantiate("shaping_eased", "probe"))
    keys = [f.wire_key for f in profile.config]
    assert len(keys) == len(set(keys))
    assert "SEED" not in keys


def test_live_metrics_gate_the_state_machine_drawing():
    """`topology.ts` gives a stimulus an arm only when a metric SCORES it. So
    the metrics are not only the charts: they are what makes the diagram
    describe the task rather than the whole twelve-odor vocabulary."""
    profile = generate.build_profile(a_task())
    assert len(profile.live_metrics) == 2
    triggers = {m.trigger_code for m in profile.live_metrics}
    assert triggers == {101, 103}
    for metric in profile.live_metrics:
        assert metric.success_code != metric.alternate_code


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def test_a_channel_this_rig_lacks_is_reported():
    assert "TSK101" in codes(a_task(trials=[
        TrialTypeDef("odor_line_99", "ODOR_1_ON", True, "right_well", "fluid_2")
    ]))


def test_a_channel_of_the_wrong_kind_is_reported():
    assert "TSK102" in codes(a_task(trials=[
        TrialTypeDef("trial_light", "ODOR_1_ON", True, "right_well", "fluid_2")
    ]))


def test_rewarding_the_other_well_is_reported():
    """THE ONE THAT LOOKS CORRECT ON SCREEN. The row reads "odor 3 → left well",
    the animal answers left, and the water arrives on the right."""
    assert "TSK103" in codes(a_task(trials=[
        TrialTypeDef("odor_line_3", "ODOR_3_ON", True, "left_well", "fluid_2")
    ]))


def test_an_undeclared_strobe_is_reported():
    assert "TSK104" in codes(a_task(trials=[
        TrialTypeDef("odor_line_1", "NOT_A_CODE", True, "right_well", "fluid_2")
    ]))


def test_two_types_sharing_an_onset_code_are_reported():
    """Two conditions reporting one code are indistinguishable in the data —
    every analysis would pool them without saying so."""
    assert "TSK105" in codes(a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2"),
        TrialTypeDef("odor_line_3", "ODOR_1_ON", True, "left_well", "fluid_0"),
    ]))


def test_an_unnamed_condition_is_reported():
    """The name is the only handle every readout has on a condition: it titles
    the live sparkline, the learning curve and a strategy axis. Unnamed, the
    generator falls back to the channel — so the chart is titled after whatever
    line happened to carry it, which is a fact about the bench and not the
    task."""
    assert "TSK110" in codes(a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2"),
    ]))
    # Whitespace is not a name.
    assert "TSK110" in codes(a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2",
                     label="   "),
    ]))


def test_two_conditions_under_one_name_are_reported():
    """The same argument TSK105 makes about onset codes, one layer up: two
    curves under one title, and nothing downstream can tell which is which.
    Compared the way a reader compares them — case and spacing are not what
    distinguishes two conditions."""
    assert "TSK111" in codes(a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2",
                     label="Go right"),
        TrialTypeDef("odor_line_3", "ODOR_3_ON", True, "left_well", "fluid_0",
                     label="go  RIGHT"),
    ]))
    assert "TSK111" not in codes(a_task())


def test_a_condition_s_name_titles_its_live_metric():
    """What the operator typed is what Mission Control's strip, the learning
    curve and the strategy axis read back."""
    profile = generate.build_profile(a_task(trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2",
                     label="orange → right"),
    ]))
    assert [m.label for m in profile.live_metrics] == ["P(right well | orange → right)"]


def test_an_unordered_ramp_is_reported():
    """`liveStage()` scans DOWN, so an out-of-order row never engages — the
    schedule simply appears to skip a step."""
    assert "TSK106" in codes(a_task(stages=[
        StageRow(trials=0), StageRow(trials=50), StageRow(trials=20)
    ]))


def test_an_over_long_start_line_is_reported():
    """The firmware cannot report this: `readLineInto()` truncates and drops the
    rest, so the session runs on whichever values fit."""
    assert "TSK107" in codes(a_task(stages=[StageRow(trials=i * 10) for i in range(40)]))


def test_a_table_with_no_presentable_trial_is_reported():
    assert "TSK108" in codes(a_task(trials=[]))


def test_a_pool_that_adds_up_to_nothing_is_reported():
    """The firmware SURVIVES this, which is why it needs saying.
    `generateTrials()` would divide by the summed weight, so an all-zero pool
    falls back to weighting every row equally — the box runs a uniform pool and
    reports nothing unusual while the table on screen says otherwise."""
    from dataclasses import replace

    task = a_task(selection_mode="pool")
    assert "TSK109" not in codes(task)
    zeroed = replace(task, trials=[replace(t, weight=0) for t in task.trials])
    assert "TSK109" in codes(zeroed)


def test_a_zero_weight_on_some_rows_is_a_parked_type_not_a_fault():
    """A zero is how a trial type is disabled without deleting it — the
    firmware simply never draws it. Only the TOTAL is a problem."""
    from dataclasses import replace

    task = a_task(selection_mode="pool")
    parked = replace(task, trials=[
        replace(task.trials[0], weight=0), *task.trials[1:]
    ])
    assert "TSK109" not in codes(parked)


def test_an_all_zero_pool_is_silent_under_anti_bias_selection():
    """Anti-bias draws a SIDE and weights nothing, so the pool column is inert
    there. Reporting it would be a diagnostic against a field with no effect."""
    from dataclasses import replace

    task = a_task(selection_mode="antibias")
    zeroed = replace(task, trials=[replace(t, weight=0) for t in task.trials])
    assert "TSK109" not in codes(zeroed)


def test_an_all_zero_table_is_reported_under_weighted_selection_too():
    """The weighted selector reads the same weights and makes the same uniform
    fallback, so the same silent-wrong-data case applies."""
    from dataclasses import replace

    task = a_task(selection_mode="weighted")
    assert "TSK109" not in codes(task)
    zeroed = replace(task, trials=[replace(t, weight=0) for t in task.trials])
    assert "TSK109" in codes(zeroed)


def test_a_go_condition_paying_nothing_is_reported():
    """The line opens for 0 ms between two fluid strobes: a dry well that every
    readout scores as rewarded. A no-go pays nothing by definition and is not."""
    from dataclasses import replace

    task = a_task()
    dry = replace(task, trials=[replace(task.trials[0], reward_time=0), task.trials[1]])
    found = validate(dry)
    assert [d.code for d in found] == ["TSK113"]
    assert found[0].location == "trials[0].rewardTime"
    nogo = a_task(trials=[
        task.trials[0],
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
    ])
    assert "TSK113" not in codes(nogo)


def test_every_problem_is_reported_not_just_the_first():
    found = codes(a_task(
        trials=[TrialTypeDef("odor_line_99", "NOT_A_CODE", True, "right_well", "fluid_0")],
        stages=[StageRow(trials=0), StageRow(trials=0)],
    ))
    assert {"TSK101", "TSK104", "TSK103", "TSK106"} <= found


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


def test_saving_writes_a_definition_and_a_flashable_sketch(tmp_path, library):
    s = store.TaskStore(tmp_path, library_root=library)
    definition = presets.instantiate("grgl_2odor", "probe", "Probe Task")
    assert s.save(definition) == []

    folder = s.sketch_dir(definition)
    # The folder-name-matches-.ino rule is arduino-cli's, and the single most
    # common reason a sketch silently fails to appear.
    assert (folder / "Probe Task.ino").is_file()
    assert (folder / "TaskPins.h").is_file()
    assert (folder / "TaskTrials.h").is_file()
    assert json.loads((folder / "task.json").read_text(encoding="utf-8"))["taskName"] == "Probe Task"


def test_a_definition_with_diagnostics_still_saves(tmp_path, library):
    """A half-finished task must be savable — the gate is flashing, not saving."""
    s = store.TaskStore(tmp_path, library_root=library)
    definition = presets.instantiate("grgl_2odor", "probe")
    definition = TaskDefinition.from_json({**definition.to_json(), "trials": []})
    assert s.save(definition)          # diagnostics returned...
    assert s.get("probe") is not None   # ...and it is on disk


def test_renaming_a_task_takes_its_old_folder_with_it(tmp_path, library):
    """Otherwise the previous folder stays discoverable, the picker offers two
    sketches for one task, and flashing the wrong one is silent."""
    from dataclasses import replace

    s = store.TaskStore(tmp_path, library_root=library)
    definition = presets.instantiate("grgl_2odor", "probe", "Before")
    s.save(definition)
    assert (s.root / definition.category / "Before").is_dir()

    s.save(replace(definition, name="After"))
    assert not (s.root / definition.category / "Before").exists()
    assert (s.root / definition.category / "After").is_dir()


def test_deleting_removes_both_halves(tmp_path, library):
    s = store.TaskStore(tmp_path, library_root=library)
    definition = presets.instantiate("grgl_2odor", "probe")
    s.save(definition)
    assert s.delete("probe") is True
    assert s.get("probe") is None
    assert not s.sketch_dir(definition).exists()
    # Idempotent: two clients racing on one task is not an error.
    assert s.delete("probe") is False


def test_a_rewiring_regenerates_every_stored_sketch(tmp_path, library):
    """THE REASON `hardware.save` CALLS THIS. A pin is compiled into TaskPins.h,
    so a folder generated under the old wiring flashes the old pins — silently,
    because it still compiles and the only symptom is a valve that never fires.
    """
    from ephymeris_sidecar.hardware import store as rig_store

    s = store.TaskStore(tmp_path, library_root=library)
    definition = presets.instantiate("grgl_2odor", "probe")
    s.save(definition)
    header = s.sketch_dir(definition) / "TaskPins.h"
    assert "#define BOX_PIN_TRIAL_LIGHT 36" in header.read_text(encoding="utf-8")

    doc = rig_store.default_document()
    doc["pins"]["trial_light"]["index"] = 12
    registry.set_rig_source(lambda: doc)
    assert s.regenerate_all() == 1
    assert "#define BOX_PIN_TRIAL_LIGHT 12" in header.read_text(encoding="utf-8")


def test_a_broken_definition_does_not_make_the_library_unlistable(tmp_path, library):
    s = store.TaskStore(tmp_path, library_root=library)
    s.save(presets.instantiate("grgl_2odor", "good"))
    s.root.joinpath("broken.json").write_text("{ not json", encoding="utf-8")
    assert [d.id for d in s.list_definitions()] == ["good"]


def test_failures_reads_the_wiring_in_force(tmp_path, library):
    """`impact_of` installs a HYPOTHETICAL wiring and asks again, so this must
    consult the registries live rather than anything cached — that difference is
    the entire mechanism by which a rewiring's cost is known before the write."""
    from ephymeris_sidecar.hardware import store as rig_store

    s = store.TaskStore(tmp_path, library_root=library)
    s.save(presets.instantiate("grgl_2odor", "probe"))
    assert s.failures("probe") == set()

    doc = rig_store.default_document()
    doc["channels"].pop("odor_line_1")
    doc["pins"].pop("odor_line_1")
    registry.set_rig_source(lambda: doc)
    assert "TSK101" in s.failures("probe")


@pytest.fixture
def library(tmp_path_factory):
    """A minimal bundled library holding the root sketch.

    Only `GRGL/GRGL.ino` matters — the store copies it verbatim, so its contents
    are irrelevant here and its PRESENCE is what is being exercised.
    """
    root = tmp_path_factory.mktemp("library")
    sketch = root / "Olfactory Behavior" / "GRGL"
    sketch.mkdir(parents=True)
    (sketch / "GRGL.ino").write_text("// root sketch\n", encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# The vocabulary against the firmware
# --------------------------------------------------------------------------- #


def _firmware_codes() -> dict[str, int] | None:
    """Every `BF_*` the staged firmware defines, or None outside a checkout.

    Read from `sketches/`, which `npm run stage:sketches` writes from the
    behaviour firmware repo. Skipped rather than failed when it is absent: a
    packaged sidecar has no library beside it, and this is a developer guard.
    """
    import re
    from pathlib import Path

    from ephymeris_sidecar import discovery

    root, _ = discovery.library_root()
    if root is None:
        return None
    header = Path(root) / "libraries" / "BehaviorBox" / "BoxStrobes.h"
    if not header.is_file():
        return None
    return {
        m.group(1)[3:]: int(m.group(2))
        for m in re.finditer(r"^#define (BF_[A-Z0-9_]+) +(\d+)", header.read_text(encoding="utf-8"), re.M)
    }


def test_the_vocabulary_declares_exactly_what_the_firmware_emits():
    """DECLARED MEANS EMITTABLE, checked rather than asserted in prose.

    Both directions fail silently without this. A code the vocabulary declares
    and the firmware cannot produce is a name in every picker that no session
    will ever contain — thirty of them sat here describing response ports 3-7
    that a two-port trial runner has no way to poll. A code the FIRMWARE emits
    and the vocabulary does not declare is worse: it arrives in the data as an
    unlabelled number, and `docs/tasks.md` records a real instance.

    Cross-repo, so it is a guard rather than a gate — the firmware can be edited
    without this suite running. It is still the only thing that compares them.
    """
    firmware = _firmware_codes()
    if firmware is None:
        pytest.skip("no staged sketch library (run `npm run stage:sketches`)")

    vocab = registry.vocabulary()
    declared = {e.name: e.code for e in vocab}

    assert set(declared) == set(firmware), (
        f"only in the vocabulary: {sorted(set(declared) - set(firmware))}; "
        f"only in the firmware: {sorted(set(firmware) - set(declared))}"
    )
    assert declared == firmware, "a code number disagrees across the two repos"


def test_a_retired_code_is_never_reissued_and_never_free():
    """The third state, and the reason it exists.

    `retired` is for codes a REAL SESSION contains. Reissuing one would silently
    merge two unrelated event types in any analysis spanning the change, so it
    is excluded from `free_ranges` as well as from `codes` — dropping either
    half would let `is_free()` hand it out.
    """
    vocab = registry.vocabulary()
    assert vocab.retired, "the dummy solenoid clicks are in the recorded archive"
    for code, name in vocab.retired.items():
        assert not vocab.is_free(code), name
        assert vocab.name_of(code) is None, name
        assert vocab.retired_name(code) == name


def test_the_odor_onsets_step_over_the_retired_block():
    """The gap is load-bearing, not cosmetic.

    Numbering odor 10 as 110 would make a `110` in a recorded file mean
    DUMMY_SOLENOID_CLICK_1 before some date and ODOR_10_ON after it — the exact
    silent merge the append-only rule exists to prevent, and the reason the run
    resumes at 114 rather than continuing.
    """
    vocab = registry.vocabulary()
    assert [vocab.code_of(f"ODOR_{n}_ON") for n in range(1, 13)] == [
        101, 102, 103, 104, 105, 106, 107, 108, 109, 114, 115, 116
    ]
    for code in (110, 111, 112, 113):
        assert vocab.retired_name(code), code
        assert vocab.name_of(code) is None, code


def test_the_free_ranges_are_exactly_what_is_unallocated():
    """A number that is neither used, retired, nor listed free is LOST — nothing
    will ever issue it. One was (259), until the ranges were recomputed rather
    than hand-maintained."""
    vocab = registry.vocabulary()
    allocated = {e.code for e in vocab} | set(vocab.retired)
    for code in range(min(allocated), vocab.code_max + 1):
        assert vocab.is_free(code) == (code not in allocated), code


# --------------------------------------------------------------------------- #
# Rig-pinned copies of the bundled sketches
# --------------------------------------------------------------------------- #


def _bundle(root, *sketches, pins=True):
    """A miniature bundled library. `pins` decides whether each opts in."""
    for category, name in sketches:
        folder = root / category / name
        folder.mkdir(parents=True)
        include = '#include "TaskPins.h"\n' if pins else ""
        (folder / f"{name}.ino").write_text(
            include + "#include <BehaviorBox.h>\n", encoding="utf-8"
        )
        if pins:
            (folder / "TaskPins.h").write_text("#ifndef TASK_PINS_H\n#endif\n", encoding="utf-8")
    return root


def test_a_sketch_opts_in_by_including_the_header(tmp_path):
    """The signal is the `#include` itself. A manifest key would be a second
    declaration, and the two disagreeing means a sketch that includes the header,
    gets the shipped copy that declares nothing, and runs the wrong pins."""
    from ephymeris_sidecar.taskdef import bundled

    root = _bundle(tmp_path / "yes", ("Utility", "Wants"))
    plain = _bundle(tmp_path / "no", ("Utility", "Plain"), pins=False)
    assert bundled.wants_pinning(root / "Utility" / "Wants")
    assert not bundled.wants_pinning(plain / "Utility" / "Plain")


def test_a_rebuild_carries_this_rig_s_pins_and_the_rest_of_the_sketch(tmp_path):
    from ephymeris_sidecar.hardware import store as rig_store
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Probe"))
    # A file the sketch owns but the generator knows nothing about. Copying the
    # `.ino` alone would drop `extras/`, `task.json`, everything.
    (library / "Utility" / "Probe" / "task.json").write_text('{"taskName":"Probe"}', encoding="utf-8")

    doc = rig_store.default_document()
    doc["pins"]["trial_light"]["index"] = 12
    registry.set_rig_source(lambda: doc)

    out = tmp_path / "pinned"
    landed = bundled.repin(library / "Utility" / "Probe", "Utility", out)
    assert landed == out / "Utility" / "Probe"
    assert (landed / "Probe.ino").is_file()
    assert (landed / "task.json").is_file()
    assert "#define BOX_PIN_TRIAL_LIGHT 12" in (landed / "TaskPins.h").read_text(encoding="utf-8")


def test_a_rebuild_replaces_the_bundled_entry_rather_than_joining_it(tmp_path, monkeypatch):
    """A rebuild is the SAME sketch with the right pins, not a second one.
    Offering both would make flashing a coin flip, and the picker would show a
    name twice with nothing to choose between."""
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Probe"))
    monkeypatch.setenv(discovery.LIBRARY_ENV, str(library))
    (library / "libraries").mkdir()

    plain = discovery.discover()
    assert [(s.name, s.source) for s in plain.sketches] == [("Probe", "bundled")]

    out = tmp_path / "pinned"
    bundled.repin_all(out)
    rebuilt = discovery.discover(None, out)
    assert len(rebuilt.sketches) == 1
    entry = rebuilt.sketches[0]
    # Still `bundled`: what it IS has not changed, only which pins it compiles
    # against, and nothing downstream should have to know which copy it got.
    assert (entry.name, entry.source) == ("Probe", "bundled")
    assert str(out) in entry.path


def test_a_rebuild_of_a_sketch_this_version_no_longer_ships_is_reported(tmp_path, monkeypatch):
    """Not offered, and not silently dropped either. Flashing it would run
    firmware this build does not contain, and dropping it in silence would hide
    that the folder is there at all."""
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Probe"))
    monkeypatch.setenv(discovery.LIBRARY_ENV, str(library))
    (library / "libraries").mkdir()
    out = tmp_path / "pinned"
    bundled.repin_all(out)

    # An app update dropped a sketch; its rebuild is still on disk, and it is
    # perfectly well-formed — which is exactly why it has to be reported rather
    # than left to the folder-name rule to catch.
    orphan = out / "Utility" / "Retired"
    orphan.mkdir(parents=True)
    (orphan / "Retired.ino").write_text("//\n", encoding="utf-8")

    result = discovery.discover(None, out)
    assert [s.name for s in result.sketches] == ["Probe"]
    assert any("no longer ships" in s.reason for s in result.skipped), result.skipped


def test_repinning_sweeps_what_no_bundled_sketch_claims(tmp_path, monkeypatch):
    """Otherwise a renamed or dropped sketch stays discoverable forever — and it
    would be served in place of nothing at all."""
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Probe"))
    monkeypatch.setenv(discovery.LIBRARY_ENV, str(library))
    (library / "libraries").mkdir()
    out = tmp_path / "pinned"
    bundled.repin_all(out)

    stale = out / "Utility" / "Gone"
    stale.mkdir(parents=True)
    (stale / "Gone.ino").write_text("//\n", encoding="utf-8")
    assert bundled.repin_all(out) == 1
    assert not stale.exists()
    assert (out / "Utility" / "Probe").is_dir()


def test_a_sketch_that_does_not_opt_in_is_left_alone(tmp_path, monkeypatch):
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Plain"), pins=False)
    monkeypatch.setenv(discovery.LIBRARY_ENV, str(library))
    (library / "libraries").mkdir()
    out = tmp_path / "pinned"
    assert bundled.repin_all(out) == 0
    assert str(out) not in discovery.discover(None, out).sketches[0].path


def test_every_bundled_sketch_that_drives_a_pin_asks_to_be_rebuilt():
    """The one that matters on the real library.

    A sketch driving hardware against `BoxPins.h`'s shipped defaults is silently
    wrong on a rewired rig — `utility.identify` lights the old pin, the
    simulator opens the old valve — and it still compiles and still reports a
    perfect strobe stream. Opting in is one `#include`; forgetting it is
    invisible.
    """
    from pathlib import Path

    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.taskdef import bundled

    result = discovery.discover()
    if not result.sketches:
        pytest.skip("no staged sketch library (run `npm run stage:sketches`)")
    missing = [
        s.name for s in result.sketches if not bundled.wants_pinning(Path(s.path))
    ]
    assert missing == [], f"these do not include TaskPins.h: {missing}"


def test_rebuilding_twice_keeps_the_copies_and_moves_their_pins(tmp_path, monkeypatch):
    """THE BUG THIS CAUGHT, and the only way to see it.

    `repin_all` used to take a sketch list, and the caller's nearest one was
    `Application.discovery` — whose entries point at the PREVIOUS rebuild once
    one exists. Every source became its own target, `repin` cleared the target
    first, and the copy was destroyed. Silently: discovery fell back to the
    bundle and the rig ran the SHIPPED pins, which is the exact failure this
    whole mechanism exists to prevent.

    One rebuild always worked. It took a second one to show.
    """
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.hardware import store as rig_store
    from ephymeris_sidecar.taskdef import bundled

    library = _bundle(tmp_path / "lib", ("Utility", "Probe"))
    monkeypatch.setenv(discovery.LIBRARY_ENV, str(library))
    (library / "libraries").mkdir()
    out = tmp_path / "pinned"

    assert bundled.repin_all(out) == 1
    header = out / "Utility" / "Probe" / "TaskPins.h"
    assert "#define BOX_PIN_TRIAL_LIGHT 36" in header.read_text(encoding="utf-8")

    # ...now rewire and rebuild again, exactly as `hardware.save` does.
    doc = rig_store.default_document()
    doc["pins"]["trial_light"]["index"] = 12
    registry.set_rig_source(lambda: doc)

    assert bundled.repin_all(out) == 1
    assert header.is_file(), "the second rebuild destroyed the copy"
    assert "#define BOX_PIN_TRIAL_LIGHT 12" in header.read_text(encoding="utf-8")
    # ...and it is still the sketch, not just a header.
    assert (out / "Utility" / "Probe" / "Probe.ino").is_file()


def test_a_rebuild_refuses_to_be_its_own_source(tmp_path):
    """Belt and braces under the fix above: even handed a path inside the
    output root, `repin` declines rather than deleting it."""
    from ephymeris_sidecar.taskdef import bundled

    out = tmp_path / "pinned"
    inside = out / "Utility" / "Probe"
    inside.mkdir(parents=True)
    (inside / "Probe.ino").write_text('#include "TaskPins.h"\n', encoding="utf-8")

    assert bundled.repin(inside, "Utility", out) is None
    assert (inside / "Probe.ino").is_file(), "it deleted the thing it refused to copy"
