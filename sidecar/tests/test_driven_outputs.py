"""PWM, tone and pulse-train channels in the rig (TASKS.md#driven-outputs).

A `pwm_out`, a `tone_out` and a `digital_out` in `train` mode are channel-set
declarations like any other: their edges get codes from a save, their type and
mode are in the channel-set hash, and the board's limits on them (RIG109) are
wiring rules, refused at save.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import allocation, board, registry
from ephymeris_sidecar.taskdef import generate, lowering, utility
from ephymeris_sidecar.taskdef.model import TaskDefinition
from ephymeris_sidecar.taskdef.validate import validate
from tests.fixtures import spine as fixture


@pytest.fixture(autouse=True)
def _shipped_rig_definition():
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)
    yield
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


def with_outputs(**channels: tuple[dict, int]) -> dict:
    """The shipped document plus `name=(entry, pin)` channels, appended."""
    doc = store.default_document()
    for name, (entry, pin) in channels.items():
        doc["channels"][name] = entry
        doc["pins"][name] = {"index": pin}
    return doc


LASER = {"kind": "cue", "type": "digital_out", "mode": "train", "role": "stimulus"}
TONE = {"kind": "cue", "type": "tone_out", "role": "stimulus"}
LIGHT = {"kind": "cue", "type": "pwm_out", "role": "stimulus"}


def codes(doc: dict) -> list[tuple[str, str]]:
    return [(p["code"], p["location"]) for p in service.problems_for(doc) if p["code"]]


def test_each_type_has_its_edges_and_a_train_strobes_only_its_start_and_end():
    assert registry.edges_of("pwm_out") == ("on", "off")
    assert registry.edges_of("tone_out") == ("on", "off")
    assert registry.edges_of("digital_out") == ("on", "off")
    assert registry.edges_of("digital_out", "level") == ("on", "off")
    assert registry.edges_of("digital_out", "train") == ("train_on", "train_off")
    assert [registry.drive_of(*t) for t in (("pwm_out", None), ("tone_out", None), ("digital_out", "train"),
                                            ("digital_out", None), ("digital_in", None))] == \
        ["pwm", "tone", "train", None, None]


def test_a_save_issues_train_codes_named_for_the_channel():
    doc = with_outputs(laser=(LASER, 11), tone=(TONE, 12), light=(LIGHT, 45))
    filled, issued = allocation.plan(doc, registry.vocabulary())
    assert filled["channels"]["laser"]["edges"] == {"train_on": "LASER_TRAIN_ON", "train_off": "LASER_TRAIN_OFF"}
    assert filled["channels"]["tone"]["edges"] == {"on": "TONE_ON", "off": "TONE_OFF"}
    assert filled["channels"]["light"]["edges"] == {"on": "LIGHT_ON", "off": "LIGHT_OFF"}
    assert [a.name for a in issued][-6:] == ["LASER_TRAIN_ON", "LASER_TRAIN_OFF", "TONE_ON", "TONE_OFF",
                                             "LIGHT_ON", "LIGHT_OFF"]


def test_the_three_types_on_free_pins_break_no_rule():
    doc = with_outputs(laser=(LASER, 11), tone=(TONE, 12), light=(LIGHT, 45))
    assert codes(doc) == []
    chans = registry.ChannelMap(*registry.split_rig(doc))
    assert [chans.get(n).drive for n in ("laser", "tone", "light")] == ["train", "tone", "pwm"]


def test_a_stored_level_mode_is_the_level_line_it_always_was():
    doc = store.default_document()
    base = registry.ChannelMap(*registry.split_rig(doc)).channel_set.content_hash()
    doc["channels"]["trial_light"]["mode"] = "level"
    chans = registry.ChannelMap(*registry.split_rig(doc))
    assert chans.get("trial_light").mode is None and chans.get("trial_light").drive is None
    assert chans.channel_set.content_hash() == base
    assert codes(doc) == []


def test_a_train_moves_the_channel_set_hash_and_an_unchanged_set_hashes_as_before():
    """`mode` joins a channel's hashed entry only when it is a train, so every
    channel set saved before modes existed keeps its hash (and its version)."""
    doc = store.default_document()
    base = registry.ChannelMap(*registry.split_rig(doc)).channel_set.content_hash()
    shipped = registry.shipped_channels().channel_set.content_hash()
    assert base == shipped
    for change in ({"mode": "train"}, {"type": "pwm_out"}, {"type": "tone_out"}):
        changed = copy.deepcopy(doc)
        changed["channels"]["trial_light"].update(change)
        assert registry.ChannelMap(*registry.split_rig(changed)).channel_set.content_hash() != base, change
    assert registry.CHANNEL_SET_HASH_VERSION == 2


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("fluid_2", {"type": "pwm_out"}),                    # a reward line the trial runner switches
        ("odor_line_1", {"mode": "train"}),                  # an emitter
        ("sync_out", {"type": "tone_out"}),                  # the sync line
        ("trial_light", {"type": "pwm_out", "mode": "train"}),  # a mode on a type that has none
        ("trial_light", {"edges": {"on": "TRIAL_START"}, "mode": "train"}),  # `on` is no train edge
    ],
)
def test_rig107_a_driven_output_off_a_cue_or_a_misplaced_mode_is_reported(name, change):
    doc = store.default_document()
    doc["channels"][name].update(change)
    assert ("RIG107", f"channels.{name}") in codes(doc), change


@pytest.mark.parametrize("change", [{"mode": "train"}, {"type": "tone_out"}, {"type": "pwm_out"}])
def test_rig107_the_trial_light_is_never_a_driven_output(change):
    """GRGL and GRGL_Sim `digitalWrite(trialLight, HIGH)`: a train there is a laser
    held on, a tone a speaker on DC."""
    doc = store.default_document()
    doc["channels"]["trial_light"].update(change)
    assert ("RIG107", "channels.trial_light") in codes(doc), change


def without(doc: dict, *names: str) -> dict:
    for name in names:
        doc["channels"].pop(name)
        doc["pins"].pop(name)
    return doc


@pytest.mark.parametrize(
    ("dropped", "pin"),
    [
        (("trial_light",), 36),                                   # BoxPins.h's trial light, kept
        (("vacuum",), 40),
        (tuple(f"odor_line_{i}" for i in range(1, 13)), 22),       # BOX_ODOR_PINS' first, kept
        (("fluid_0", "fluid_1", "fluid_2", "fluid_3"), 42),
    ],
)
def test_rig107_a_driven_output_where_the_trial_runner_keeps_a_level_line(dropped, pin):
    """A rig without the channel leaves BoxPins.h's pin to the trial runner, so
    the line is judged by where it lands, not by its name."""
    doc = with_outputs(laser=(LASER, pin))
    without(doc, *dropped)
    assert ("RIG107", "channels.laser") in codes(doc)


def test_every_level_line_the_trial_runner_writes_is_one_rig107_knows():
    """Every `digitalWrite` in BehaviorBox.h and the bundled trial-runner sketches
    writes a pin from a BoxPins.h macro that `registry.LEVEL_LINES` lists, or one
    derived from those arrays. BoxSpine.h and BoxUtility.h drive by the rig's
    drive, so they are not trial runners."""
    import re
    from pathlib import Path

    firmware = Path(__file__).resolve().parents[2] / "firmware"
    pins_h = (firmware / "libraries" / "BehaviorBox" / "BoxPins.h").read_text(encoding="utf-8")
    macro_of = dict(re.findall(r"const int (\w+)(?:\[\w*\])?\s*=\s*(BOX_\w+);", pins_h))
    # Pins a trial runner reaches through its trial table, each read from these arrays.
    derived = {"trial.odorPin": "Odors", "trial->odorPin": "Odors", "activeTrial->odorPin": "Odors",
               "fluidPin": "Fluids"}
    sources = [firmware / "libraries" / "BehaviorBox" / "BehaviorBox.h",
               *[p for p in firmware.rglob("*.ino") if "extras" not in p.parts]]
    written = set()
    for source in sources:
        text = re.sub(r"/\*.*?\*/", "", source.read_text(encoding="utf-8"), flags=re.S)
        text = re.sub(r"//.*", "", text)
        written |= set(re.findall(r"digitalWrite\(\s*([\w.>\-]+)", text))
    assert written, "the grep found the writes"
    macros = {macro_of[derived.get(w, w).split("[")[0]] for w in written}
    assert macros <= {m for m, *_ in registry.LEVEL_LINES}, macros
    assert {m for m, *_ in registry.LEVEL_LINES} <= macros, "and every listed line is written"
    # A macro filled by name is the generator's own (`PIN_MACROS`), and a kept
    # default is the shipped pinout's, which is BoxPins.h's.
    named = dict((m, n) for n, m in registry.PIN_MACROS)
    shipped = registry.shipped_channels()
    for macro, by, key, _ in registry.LEVEL_LINES:
        if by == "name":
            assert named[macro] == key
            assert f"#define {macro} {shipped.get(key).index}" in pins_h


@pytest.mark.parametrize(
    ("channels", "where"),
    [
        ({"light": (LIGHT, 47)}, "light"),                       # pin 47: no timer
        ({"light": (LIGHT, 9), "tone": (TONE, 12)}, "light"),     # Timer2, which tone() takes
        ({"light": (LIGHT, 10), "tone": (TONE, 12)}, "light"),
        ({"tone": (TONE, 12), "tone_2": (TONE, 11)}, "tone_2"),  # a second tone
    ],
)
def test_rig109_hardware_the_board_cannot_run_is_refused(channels, where):
    doc = with_outputs(**channels)
    assert codes(doc) == [("RIG109", f"pins.{where}")]


def test_two_pwm_channels_on_one_timer_and_a_pwm_on_timer2_without_a_tone_are_fine():
    doc = with_outputs(a=(LIGHT, 6), b=(LIGHT, 7), c=(LIGHT, 9), d=(LIGHT, 13))
    assert codes(doc) == []


def test_the_timer_table_is_the_avr_core_s():
    """Every PWM pin of a Mega 2560 (`pins_arduino.h`), and tone() on Timer2."""
    assert sorted(board.PWM_TIMER) == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 44, 45, 46]
    assert [p for p, t in board.PWM_TIMER.items() if t == board.TONE_TIMER] == [9, 10]


# --------------------------------------------------------------------------- #
# Lowering: a bit per row, a parameter per value
# --------------------------------------------------------------------------- #

#: Wait for a poke, then the light at the row's duty, the tone at its pitch and
#: the laser's train together for a second, then an ITI.
STIM = [
    {"phase": "wait", "on": "port"},
    {"phase": "present", "outputs": ["light", "tone", "laser"], "ms": 1000},
    {"phase": "iti", "ms": 2000},
]
DRIVES = {"light": "pwm", "tone": "tone", "laser": "train"}
STIM_BIND = {"port": "odor_port", "light": "light", "tone": "tone", "laser": "laser"}


def test_a_driven_slot_has_a_bit_per_row_and_each_value_is_a_parameter():
    rows = [{"bind": STIM_BIND}, {"bind": STIM_BIND}]
    low = lowering.lower(STIM, inputs=["port"], outputs=["light", "tone", "laser"], rows=rows, drives=DRIVES,
                         session_cap=True)
    # One channel per slot, but one bit per row: each row drives it at its own value.
    assert low.outputs == (("light", "light"), ("light", "light"), ("tone", "tone"), ("tone", "tone"),
                           ("laser", "laser"), ("laser", "laser"))
    assert low.params == ("NT", "T1", "T2",
                          "PD1_1", "TF1_2", "TH1_3", "TW1_3", "TL1_3",
                          "PD2_1", "TF2_2", "TH2_3", "TW2_3", "TL2_3")
    slot = {k: i for i, k in enumerate(low.params)}
    assert low.drives == ((0, "pwm", slot["PD1_1"]), (1, "pwm", slot["PD2_1"]),
                          (2, "tone", slot["TF1_2"]), (3, "tone", slot["TF2_2"]),
                          (4, "train", slot["TH1_3"]), (5, "train", slot["TH2_3"]))
    present = [s for s, p in zip(low.states, low.phases) if p == 1]
    assert [s[0] for s in present] == [0b010101, 0b101010], "each row's present lights its own bits"
    by_key = {s.key: s for s in low.slots}
    assert (by_key["TW2_3"].role, by_key["TW2_3"].row, by_key["TW2_3"].slot) == ("train_width", 1, "laser")


def test_a_level_slot_is_still_one_bit_per_channel_beside_driven_ones():
    rows = [{"bind": dict(STIM_BIND, cue="trial_light")}, {"bind": dict(STIM_BIND, cue="trial_light")}]
    spine = [dict(STIM[0], outputs=["cue"]), {"phase": "present", "outputs": ["light"], "ms": 10}, STIM[2]]
    low = lowering.lower(spine, inputs=["port"], outputs=["cue", "light"], rows=rows, drives={"light": "pwm"})
    assert low.outputs == (("cue", "trial_light"), ("light", "light"), ("light", "light"))
    assert low.params[-2:] == ("PD1_2", "PD2_2"), "numbered by the slot's place among the outputs"


def test_a_driven_slot_in_every_row_of_many_is_refused_past_32_bits():
    rows = [{"bind": STIM_BIND} for _ in range(11)]
    with pytest.raises(lowering.LoweringError, match="33 output bits"):
        lowering.lower(STIM, inputs=["port"], outputs=["light", "tone", "laser"], rows=rows, drives=DRIVES)


# --------------------------------------------------------------------------- #
# A spine task that drives them
# --------------------------------------------------------------------------- #


@pytest.fixture
def driven_rig():
    fixture.install(*fixture.issued_rig(driven=True))
    yield
    fixture.uninstall()


def stimulus(**edits) -> TaskDefinition:
    return TaskDefinition.from_json(fixture.stimulus(**edits))


def spn(definition: TaskDefinition) -> list[tuple[str, str]]:
    return [(d.code, d.location) for d in validate(definition)]


def test_a_task_driving_all_three_is_clean_and_its_snapshot_names_each_drive(driven_rig):
    definition = stimulus()
    assert spn(definition) == []
    snapshot = generate.build_profile(definition).spine
    assert snapshot["interp"] == lowering.INTERP_VERSION == 6
    laser = [o for o in snapshot["outputs"] if o["slot"] == "laser"]
    assert laser == [
        {"slot": "laser", "channel": "laser", "on": "LASER_TRAIN_ON", "off": "LASER_TRAIN_OFF",
         "drive": "train", "params": ["TH1_4", "TW1_4", "TL1_4"]},
        {"slot": "laser", "channel": "laser", "on": "LASER_TRAIN_ON", "off": "LASER_TRAIN_OFF",
         "drive": "train", "params": ["TH2_4", "TW2_4", "TL2_4"]},
    ]
    cue = next(o for o in snapshot["outputs"] if o["slot"] == "cue")
    assert "drive" not in cue and "params" not in cue
    fields = {f.metadata_key: f for f in generate.build_profile(definition).config}
    assert (fields["pwm_duty_dim_light"].default, fields["pwm_duty_dim_light"].wire_key) == (64, "PD1_2")
    assert fields["tone_hz_bright_tone"].default == 4000
    assert [fields[f"train_{k}_dim_laser"].default for k in ("hz", "width_ms", "ms")] == [20, 5, 300]
    assert (fields["train_width_ms_dim_laser"].min, fields["train_width_ms_dim_laser"].max) == (1, 999)


def test_the_folder_names_each_drive_and_links_tone_only_when_there_is_one(driven_rig):
    header = generate.task_spine_h(stimulus())
    assert "#error" not in header
    assert "#define SPINE_NUM_DRIVES 6" in header and "#define SPINE_HAS_TONE 1" in header
    assert "{5, SPINE_DRIVE_TRAIN, " in header
    plain = generate.task_spine_h(TaskDefinition.from_json(fixture.tracer()))
    assert "#define SPINE_NUM_DRIVES 0" in plain and "#define SPINE_HAS_TONE 0" in plain


@pytest.mark.parametrize(
    ("edit", "code", "where"),
    [
        # A train slot bound to the PWM line: the type and mode must both agree.
        (lambda d: d["rows"][0]["bind"].update(laser="light"), "SPN102", "rows[0].bind.laser"),
        # A level slot bound to a train channel.
        (lambda d: d["rows"][0]["bind"].update(cue="laser"), "SPN102", "rows[0].bind.cue"),
        (lambda d: d["rows"][0]["drive"].pop("tone"), "SPN112", "rows[0].drive.tone.hz"),
        (lambda d: d["rows"][1]["drive"]["light"].update(duty=256), "SPN112", "rows[1].drive.light.duty"),
        (lambda d: d["rows"][1]["drive"]["laser"].update(hz=101), "SPN112", "rows[1].drive.laser.hz"),
        (lambda d: d["rows"][0]["drive"]["laser"].update(widthMs=50), "SPN112", "rows[0].drive.laser.widthMs"),
        (lambda d: d["rows"][0]["drive"].update(cue={"duty": 1}), "SPN112", "rows[0].drive.cue"),
        (lambda d: d["slots"][4].update(mode="burst"), "SPN105", "slots[4].mode"),
        (lambda d: d["slots"][2].update(mode="train"), "SPN105", "slots[2].mode"),
    ],
)
def test_each_drive_problem_is_located(driven_rig, edit, code, where):
    raw = fixture.stimulus()
    edit(raw)
    assert (code, where) in spn(TaskDefinition.from_json(raw))


@pytest.mark.parametrize(("hz", "width"), [(20, 50), (20, 60), (100, 15)])
def test_a_train_whose_width_is_not_shorter_than_its_period_is_never_compiled(driven_rig, hz, width):
    """It would hold the line HIGH: a steady output where a train was asked for,
    which replay would agree with. So the folder refuses to compile."""
    raw = fixture.stimulus()
    raw["rows"][0]["drive"]["laser"].update(hz=hz, widthMs=width)
    definition = TaskDefinition.from_json(raw)
    assert ("SPN112", "rows[0].drive.laser.widthMs") in spn(definition)
    assert "#error" in generate.task_spine_h(definition)
    raw["rows"][0]["drive"]["laser"].update(widthMs=1000 // hz - 1)
    assert "#error" not in generate.task_spine_h(TaskDefinition.from_json(raw))


def test_a_reward_line_is_a_level_output(driven_rig):
    raw = fixture.stimulus()
    raw["spine"].insert(2, {"phase": "outcome", "line": "laser", "ms": 0})
    assert ("SPN105", "spine[2].line") in spn(TaskDefinition.from_json(raw))


def test_the_ram_a_drive_costs_is_counted(driven_rig):
    from ephymeris_sidecar.taskdef import spine as spine_module

    low = spine_module._resolve(stimulus()).lowered
    without = spine_module.task_ram_bytes(dataclasses.replace(low, drives=()))
    assert spine_module.task_ram_bytes(low) - without == \
        spine_module.DRIVE_RUN_BYTES + spine_module.DRIVE_BYTES * 6 + spine_module.TONE_RAM_BYTES


# --------------------------------------------------------------------------- #
# BOX_Utility: each one driven as what it is
# --------------------------------------------------------------------------- #


def test_the_utility_drives_each_one_as_what_it_is(driven_rig):
    header = utility.utility_channels_h("BOX_Utility")
    # Each is a stimulus by role, though a cue by kind (RIG107).
    assert '{"laser", "laser \\302\\267 test train", 11, BOX_UTIL_STIMULUS, BOX_UTIL_TRAIN}' in header
    assert '{"tone", "tone \\302\\267 test tone", 12, BOX_UTIL_STIMULUS, BOX_UTIL_TONE}' in header
    assert '{"light", "light", 45, BOX_UTIL_STIMULUS, BOX_UTIL_PWM}' in header
    assert '{"trial_light", "trial light", 36, BOX_UTIL_CUE, BOX_UTIL_LEVEL}' in header
    assert "#define BOX_UTILITY_HAS_TONE 1" in header
    fixture.install()
    assert "#define BOX_UTILITY_HAS_TONE 0" in utility.utility_channels_h("BOX_Utility")
    profile = utility.utility_profile({})
    assert profile["identify"] == {"on": "ON trial_light", "off": "OFF trial_light"}, "the first cue"


# --------------------------------------------------------------------------- #
# The refusal an operator reads
# --------------------------------------------------------------------------- #


def test_a_train_refused_for_its_pair_says_both_values_and_the_rule(driven_rig):
    """Each value was in its own range: the message names the pulse, the rate and
    the period, never "outside the range"."""
    from ephymeris_sidecar.tasks.start_command import ParamsReply, StartRefused, build_start_command

    profile = generate.build_profile(stimulus())
    config = {f.metadata_key: f.default for f in profile.config} | {"train_hz_dim_laser": 100,
                                                                   "train_width_ms_dim_laser": 15}
    command = build_start_command(profile, config)
    width = next(f.wire_key for f in profile.config if f.metadata_key == "train_width_ms_dim_laser")
    with pytest.raises(StartRefused) as caught:
        command.verify(ParamsReply(command.count, command.crc32, (width,)))
    assert str(caught.value) == ("The train on laser has a 15 ms pulse at 100 Hz; a pulse must be shorter "
                                 "than the 10 ms between pulses, so lower the width or the frequency, and "
                                 "start again.")
    assert caught.value.reason == "clamped" and caught.value.detail == {"keys": [width]}

    # A value truly outside its own range keeps the range message.
    with pytest.raises(StartRefused, match="outside the range") as caught:
        command.verify(ParamsReply(command.count, command.crc32, ("NT",)))
