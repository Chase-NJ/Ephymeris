"""PWM, tone and pulse-train channels in the rig (TASKS.md#driven-outputs).

A `pwm_out`, a `tone_out` and a `digital_out` in `train` mode are channel-set
declarations like any other: their edges get codes from a save, their type and
mode are in the channel-set hash, and the board's limits on them (RIG109) are
wiring rules, refused at save.
"""

from __future__ import annotations

import copy

import pytest

from ephymeris_sidecar.hardware import service, store
from ephymeris_sidecar.rig import allocation, board, registry
from ephymeris_sidecar.taskdef import utility
from tests.fixtures import rig as fixture


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
    derived from those arrays. BoxUtility.h drives by the rig's drive, so it
    is not a trial runner."""
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

@pytest.fixture
def driven_rig():
    fixture.install(*fixture.issued_rig(driven=True))
    yield
    fixture.uninstall()


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
