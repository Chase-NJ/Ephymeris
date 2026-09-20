"""Settings payload parsing — `settings.md` §4."""

from __future__ import annotations

from ephymeris_sidecar.settings import BOX_COUNT, DEFAULT_BAUD, SidecarSettings


def test_reads_the_keys_the_sidecar_needs() -> None:
    settings = SidecarSettings.from_payload(
        {
            "arduinoCliPath": "/opt/homebrew/bin/arduino-cli",
            "utilitySketchName": "BOX_Utility",
            "defaultBaud": 9600,
        }
    )
    assert settings.arduino_cli_path == "/opt/homebrew/bin/arduino-cli"
    assert settings.utility_sketch_name == "BOX_Utility"
    assert settings.default_baud == 9600


def test_an_unset_utility_sketch_turns_the_baseline_off() -> None:
    """No sketch is a supported configuration, not a missing one."""
    assert SidecarSettings.from_payload({}).utility_sketch_name is None
    assert SidecarSettings.from_payload({"utilitySketchName": "  "}).utility_sketch_name is None


def test_the_retired_path_valued_key_heals_to_its_basename() -> None:
    """`utilitySketchPath` predates the bundled library.

    The shell migrates its own store, so this branch only fires when an old
    store is pushed verbatim — where dropping the value would silently turn the
    baseline off and six boxes would quietly stop returning to it. The basename
    IS the sketch name, because arduino-cli requires `<folder>/<folder>.ino`.
    """
    old = {"utilitySketchPath": "/tmp/arduino/Utility/BOX_Utility"}
    assert SidecarSettings.from_payload(old).utility_sketch_name == "BOX_Utility"
    # The new key wins when both are present.
    both = {**old, "utilitySketchName": "OTHER_Sketch"}
    assert SidecarSettings.from_payload(both).utility_sketch_name == "OTHER_Sketch"


def test_unknown_keys_are_a_non_event() -> None:
    """Adding a shell-only setting must not disturb the sidecar.

    `arduinoDirectory` is the live case now rather than a hypothetical: a stale
    store still carries it, and the sidecar must shrug it off.
    """
    settings = SidecarSettings.from_payload(
        {"arduinoDirectory": "/tmp/a", "somethingTheShellOwns": {"nested": True}}
    )
    assert settings.default_baud == DEFAULT_BAUD


def test_malformed_values_fall_back_to_defaults_rather_than_raising() -> None:
    settings = SidecarSettings.from_payload(
        {"utilitySketchName": 42, "defaultBaud": "not-a-number"}
    )
    assert settings.utility_sketch_name is None
    assert settings.default_baud == DEFAULT_BAUD


def test_a_non_object_payload_does_not_take_down_the_process() -> None:
    settings = SidecarSettings.from_payload(["nope"])
    assert settings.default_baud == DEFAULT_BAUD
    assert len(settings.boxes) == BOX_COUNT


def test_baud_as_a_numeric_string_is_accepted() -> None:
    assert SidecarSettings.from_payload({"defaultBaud": "115200"}).default_baud == 115200


def test_booleans_are_not_mistaken_for_baud_rates() -> None:
    """bool subclasses int in Python; `True` is not a baud rate."""
    assert SidecarSettings.from_payload({"defaultBaud": True}).default_baud == DEFAULT_BAUD


# --- box bindings ---------------------------------------------------------


def test_all_six_boxes_always_exist_even_when_unbound() -> None:
    settings = SidecarSettings.from_payload({"boxes": [{"box": 2, "hardwareId": "ABC"}]})

    assert [b.box for b in settings.boxes] == [1, 2, 3, 4, 5, 6]
    assert settings.hardware_id_for(2) == "ABC"
    assert settings.hardware_id_for(1) is None


def test_out_of_range_box_numbers_are_discarded() -> None:
    settings = SidecarSettings.from_payload(
        {"boxes": [{"box": 0, "hardwareId": "X"}, {"box": 7, "hardwareId": "Y"}]}
    )
    assert len(settings.boxes) == BOX_COUNT
    assert all(b.hardware_id is None for b in settings.boxes)


def test_unlabelled_boxes_get_a_default_label() -> None:
    settings = SidecarSettings.from_payload({"boxes": [{"box": 3}]})
    assert settings.binding_for(3) is not None
    assert settings.binding_for(3).label == "Box 3"


# --- recording bindings ---------------------------------------------------


def test_a_box_carries_the_digital_input_its_sync_line_reaches():
    settings = SidecarSettings.from_payload(
        {"boxes": [{"box": 2, "hardwareId": "A", "label": "Two", "intanDigitalIn": 5}]}
    )
    assert settings.binding_for(2).intan_digital_in == 5
    assert settings.binding_for(1).intan_digital_in is None


def test_a_digital_input_the_controller_does_not_have_reads_as_unwired():
    for bad in (0, 17, -1, "3", True, 2.0):
        settings = SidecarSettings.from_payload({"boxes": [{"box": 1, "intanDigitalIn": bad}]})
        assert settings.binding_for(1).intan_digital_in is None, bad


def test_two_boxes_cannot_share_a_digital_input():
    """Every edge on a shared input would be matched against both boxes' strobe
    streams. The first claim stands; the second box reads as unwired, which the
    recording walkthrough refuses -- loud, where recording both would be
    plausible and wrong."""
    settings = SidecarSettings.from_payload(
        {"boxes": [{"box": 1, "intanDigitalIn": 4}, {"box": 3, "intanDigitalIn": 4}]}
    )
    assert settings.binding_for(1).intan_digital_in == 4
    assert settings.binding_for(3).intan_digital_in is None


def test_intan_endpoints_default_to_rhx_s_own_and_survive_garbage():
    assert SidecarSettings.from_payload({}).intan.command_port == 5000
    settings = SidecarSettings.from_payload(
        {"intan": {"commandPort": 6000, "waveformPort": "x", "spikePort": 99999}}
    )
    assert (settings.intan.command_port, settings.intan.waveform_port) == (6000, 5001)
    assert settings.intan.spike_port == 5002
