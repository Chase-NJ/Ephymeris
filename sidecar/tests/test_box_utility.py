"""The box utility, generated from the rig — `TASKS.md#the-box-utility`.

Wrong here is quiet: a row whose token names one channel and whose label names
another primes the wrong line under the right name. So the table and the
profile are checked against each other, and a generated header is compiled
against the real engine for a rig unlike the lab's.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.hardware.store import default_document
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.taskdef import bundled, utility

REPO = Path(__file__).resolve().parents[2]
FIRMWARE = REPO / "firmware"
TEMPLATE = json.loads(
    (FIRMWARE / "Utility" / "BOX_Utility" / "task.json").read_text(encoding="utf-8")
)


@pytest.fixture(autouse=True)
def _shipped_rig():
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


def small_relabelled_rig() -> dict:
    """The shipped box with three odor lines, relabelled, and no vacuum."""
    doc = default_document()
    for n in range(4, 13):
        del doc["channels"][f"odor_line_{n}"], doc["pins"][f"odor_line_{n}"]
    del doc["channels"]["vacuum"], doc["pins"]["vacuum"]
    doc["channels"]["odor_line_1"]["label"] = "Sandalwood"
    doc["channels"]["fluid_2"]["label"] = 'Right "A"'
    return doc


def install(doc: dict) -> None:
    registry.set_rig_source(lambda: copy.deepcopy(doc))


def test_every_output_and_beam_comes_from_the_rig_and_sync_never_does():
    header = utility.utility_channels_h("BOX_Utility")
    assert "#define BOX_UTILITY_NUM_OUTPUTS 18" in header  # 12 + 4 + light + vacuum
    assert '{"odor_line_7", "odor line 7", 23, BOX_UTIL_EMITTER}' in header
    assert "#define BOX_UTILITY_NUM_INPUTS 3" in header
    assert "sync_out" not in header, "a pulse on the sync line is an edge in a recording"


def test_a_relabelled_smaller_rig_is_what_gets_generated():
    install(small_relabelled_rig())
    header = utility.utility_channels_h("BOX_Utility")
    assert "#define BOX_UTILITY_NUM_OUTPUTS 8" in header
    assert '"Sandalwood"' in header and "odor_line_4" not in header
    assert '"Right \\"A\\" \\302\\267 right well"' in header, "quoted and UTF-8 escaped"
    assert "BOX_UTIL_VACUUM" not in header.split("#define BOX_UTILITY_OUTPUTS")[1]


def test_the_profile_keeps_the_template_and_adds_the_box():
    profile = utility.utility_profile(TEMPLATE)
    ids = [c["id"] for c in profile["controls"]]
    assert ids[:4] == ["selftest", "stop", "alloff", "pulse_ms"], "the template's own controls first"
    assert ids[4:] == ["fluids", "aux", "emitters"]
    fluids = profile["controls"][4]["channels"]
    assert fluids[0] == {
        "label": "fluid 0 · left well", "state": "fluid_0",
        "toggle": "TOGGLE fluid_0", "pulse": "PULSE fluid_0", "kind": "reward",
    }
    assert profile["identify"] == {"on": "ON trial_light", "off": "OFF trial_light"}
    assert [f["key"] for f in profile["telemetry"]["fields"]][-3:] == [
        "odor_port", "right_well", "left_well",
    ]
    assert profile["legacyNames"] == TEMPLATE["legacyNames"]


def test_regenerating_is_idempotent():
    once = utility.utility_profile(TEMPLATE)
    assert utility.utility_profile(once) == once


def test_every_grid_row_drives_a_channel_the_header_declares():
    """The two halves are generated together so they cannot disagree; this is
    the check that they do not."""
    install(small_relabelled_rig())
    header = utility.utility_channels_h("BOX_Utility")
    for control in utility.utility_profile(TEMPLATE)["controls"]:
        for row in control.get("channels", []):
            assert f'{{"{row["state"]}", ' in header, row


def test_the_rebuild_writes_both_halves(tmp_path):
    target = bundled.repin(FIRMWARE / "Utility" / "BOX_Utility", "Utility", tmp_path)
    assert target is not None
    assert "BOX_UTILITY_OUTPUTS" in (target / "UtilityChannels.h").read_text(encoding="utf-8")
    profile = json.loads((target / "task.json").read_text(encoding="utf-8"))
    assert any(c["id"] == "fluids" for c in profile["controls"])
    # Its own task.json is the template, untouched in the source.
    assert "fluids" not in (FIRMWARE / "Utility" / "BOX_Utility" / "task.json").read_text()


def test_the_baseline_finds_the_utility_without_being_told():
    """No setting names it any more: discovery over the shipped firmware must
    yield exactly one box utility, and it must be BOX_Utility."""
    from ephymeris_sidecar import discovery
    from ephymeris_sidecar.utility import _is_generated_utility

    found = [s.name for s in discovery.discover().sketches if _is_generated_utility(s)]
    assert found == ["BOX_Utility"]


def test_a_sketch_that_does_not_include_the_table_is_not_a_utility():
    assert utility.wants_utility(FIRMWARE / "Utility" / "BOX_Utility")
    assert not utility.wants_utility(FIRMWARE / "Utility" / "GRGL_Sim")


@pytest.mark.skipif(shutil.which("clang++") is None and shutil.which("g++") is None,
                    reason="no host C++ compiler")
def test_a_generated_table_compiles_against_the_engine(tmp_path):
    """Generated C is checked by a compiler, not by eye: the small relabelled
    rig's table, through the real BOX_Utility.ino and BoxUtility.h, on the
    instrumented host shim."""
    install(small_relabelled_rig())
    (tmp_path / "UtilityChannels.h").write_text(
        utility.utility_channels_h("BOX_Utility"), encoding="utf-8"
    )
    host = FIRMWARE / "libraries" / "BehaviorBox" / "extras" / "host_test"
    source = tmp_path / "main.cpp"
    source.write_text(
        '#include <Arduino.h>\n'
        '#include "strobe_fixture.h"\n'
        f'#include "{tmp_path / "UtilityChannels.h"}"\n'
        f'#include "{FIRMWARE / "Utility" / "BOX_Utility" / "BOX_Utility.ino"}"\n'
        "int main() { ::setup(); bb_feed(\"TOGGLE odor_line_1\"); ::loop();\n"
        "  return digitalRead(22) == HIGH ? 0 : 1; }\n",
        encoding="utf-8",
    )
    compiler = shutil.which("clang++") or shutil.which("g++")
    # Windows will not launch a binary without its .exe.
    binary = tmp_path / ("utility.exe" if os.name == "nt" else "utility")
    built = subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Werror", "-Wno-unused-function",
         f"-I{host / 'box_shim'}", f"-I{host}", f"-I{host.parents[1]}",
         "-x", "c++", str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, f"{compiler} failed:\n{built.stdout}{built.stderr}"
    ran = subprocess.run([str(binary)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr
