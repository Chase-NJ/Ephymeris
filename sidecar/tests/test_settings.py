"""Settings payload parsing — `settings.md` §4."""

from __future__ import annotations

from ephymeris_sidecar.settings import BOX_COUNT, DEFAULT_BAUD, SidecarSettings


def test_reads_the_keys_the_sidecar_needs() -> None:
    settings = SidecarSettings.from_payload(
        {
            "arduinoDirectory": "/tmp/arduino",
            "arduinoCliPath": "/opt/homebrew/bin/arduino-cli",
            "utilitySketchPath": "/tmp/arduino/Utility/BOX_Utility",
            "defaultBaud": 9600,
        }
    )
    assert settings.arduino_directory == "/tmp/arduino"
    assert settings.arduino_cli_path == "/opt/homebrew/bin/arduino-cli"
    assert settings.utility_sketch_path == "/tmp/arduino/Utility/BOX_Utility"
    assert settings.default_baud == 9600


def test_an_unset_utility_sketch_turns_the_baseline_off() -> None:
    """No sketch is a supported configuration, not a missing one."""
    assert SidecarSettings.from_payload({}).utility_sketch_path is None
    assert SidecarSettings.from_payload({"utilitySketchPath": "  "}).utility_sketch_path is None


def test_unknown_keys_are_a_non_event() -> None:
    """Adding a shell-only setting must not disturb the sidecar."""
    settings = SidecarSettings.from_payload(
        {"arduinoDirectory": "/tmp/a", "somethingTheShellOwns": {"nested": True}}
    )
    assert settings.arduino_directory == "/tmp/a"


def test_malformed_values_fall_back_to_defaults_rather_than_raising() -> None:
    settings = SidecarSettings.from_payload(
        {"arduinoDirectory": 42, "defaultBaud": "not-a-number"}
    )
    assert settings.arduino_directory is None
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
