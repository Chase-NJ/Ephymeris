"""The box utility, generated from the rig — `TASKS.md#the-box-utility`.

Wrong here is quiet: a row whose token names one channel and whose label names
another primes the wrong line under the right name. So the table and the
profile are checked against each other, and a generated header is compiled
against the real engine for a rig unlike the lab's.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
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
    assert '{"odor_line_7", "odor line 7", 23, BOX_UTIL_STIMULUS, BOX_UTIL_LEVEL}' in header
    assert '{"odor_port", "odor port", 2, 0}' in header, "a beam is active LOW, pulled up"
    assert "#define BOX_UTILITY_NUM_INPUTS 3" in header
    assert "sync_out" not in header, "a pulse on the sync line is an edge in a recording"


def test_a_relabelled_smaller_rig_is_what_gets_generated():
    install(small_relabelled_rig())
    header = utility.utility_channels_h("BOX_Utility")
    assert "#define BOX_UTILITY_NUM_OUTPUTS 8" in header
    assert '"Sandalwood"' in header and "odor_line_4" not in header
    assert '"Right \\"A\\" \\302\\267 right well"' in header, "quoted and UTF-8 escaped"
    assert "BOX_UTIL_ROUTING" not in header.split("#define BOX_UTILITY_OUTPUTS")[1]


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
@pytest.mark.skipif(os.name == "nt", reason="clang on Windows compiles against MSVC's "
                    "standard library, which needs C++14; the AVR build is C++11, so this "
                    "runs on Linux and macOS")
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
    binary = tmp_path / "utility"
    built = subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Werror", "-Wno-unused-function",
         f"-I{host / 'box_shim'}", f"-I{host}", f"-I{host.parents[1]}",
         "-x", "c++", str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, f"{compiler} failed:\n{built.stdout}{built.stderr}"
    ran = subprocess.run([str(binary)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr


# --------------------------------------------------------------------------- #
# A channel of each type, added to the rig, is in the utility and responds
# --------------------------------------------------------------------------- #

#: One new channel of each type and mode (`TASKS.md#the-box-utility`), on free
#: pins: (entry, pin). The lever is active HIGH, unlike every shipped beam, and
#: the laser is a stimulus by role though a cue by kind, as RIG107 requires.
EVERY_TYPE = {
    "lever": ({"kind": "response", "type": "digital_in", "role": "port", "label": "Lever",
               "active_level": "high", "debounce_ms": 0}, 38),
    "buzzer": ({"kind": "cue", "type": "digital_out", "role": "cue", "label": "Buzzer"}, 47),
    "laser": ({"kind": "cue", "type": "digital_out", "mode": "train", "role": "stimulus",
               "label": "Laser"}, 11),
    "house": ({"kind": "cue", "type": "pwm_out", "role": "cue", "label": "House light"}, 45),
    "speaker": ({"kind": "cue", "type": "tone_out", "role": "cue", "label": "Speaker"}, 12),
}


def every_type_rig() -> dict:
    """The shipped box with `EVERY_TYPE` added. Composed directly: a third
    input breaks RIG104 today (two port slots), and the utility reads neither
    the kind nor the slot, so nothing here depends on that rule."""
    doc = default_document()
    for name, (entry, pin) in EVERY_TYPE.items():
        doc["channels"][name] = copy.deepcopy(entry)
        doc["pins"][name] = {"index": pin}
    return doc


def grid_rows(profile: dict) -> dict[str, tuple[str, dict]]:
    """state key -> (grid id, row), over every grid."""
    return {row["state"]: (c["id"], row) for c in profile["controls"]
            for row in c.get("channels", [])}


def test_each_new_channel_is_a_row_with_its_drive_or_its_active_level():
    install(every_type_rig())
    header = utility.utility_channels_h("BOX_Utility")
    assert '{"lever", "Lever", 38, 1}' in header, "active HIGH, so not pulled up"
    assert '{"buzzer", "Buzzer", 47, BOX_UTIL_CUE, BOX_UTIL_LEVEL}' in header
    assert '{"laser", "Laser \\302\\267 test train", 11, BOX_UTIL_STIMULUS, BOX_UTIL_TRAIN}' in header
    assert '{"house", "House light", 45, BOX_UTIL_CUE, BOX_UTIL_PWM}' in header
    assert '{"speaker", "Speaker \\302\\267 test tone", 12, BOX_UTIL_CUE, BOX_UTIL_TONE}' in header
    assert "#define BOX_UTILITY_NUM_OUTPUTS 22" in header and "#define BOX_UTILITY_NUM_INPUTS 4" in header


def test_each_new_channel_appears_in_debug_mode_with_its_control():
    install(every_type_rig())
    profile = utility.utility_profile(TEMPLATE)
    rows = grid_rows(profile)
    assert rows["buzzer"] == ("aux", {"label": "Buzzer", "state": "buzzer", "toggle": "TOGGLE buzzer",
                                      "pulse": "PULSE buzzer", "kind": "cue"})
    grid, house = rows["house"]
    assert grid == "aux" and house["setting"] == {
        "label": "Duty", "state": "house.duty", "options": [
            {"label": "10%", "value": "26", "command": "DUTY house 26"},
            {"label": "25%", "value": "64", "command": "DUTY house 64"},
            {"label": "50%", "value": "128", "command": "DUTY house 128"},
            {"label": "100%", "value": "255", "command": "DUTY house 255"},
        ]}
    assert rows["speaker"][1]["setting"]["label"] == "Pitch"
    assert [o["command"] for o in rows["speaker"][1]["setting"]["options"]] == [
        "HZ speaker 500", "HZ speaker 1000", "HZ speaker 2000", "HZ speaker 4000", "HZ speaker 8000"]
    grid, laser = rows["laser"]
    assert grid == "emitters", "a stimulus by role sits with the stimulus lines"
    assert laser["setting"]["state"] == "laser.hz"
    assert [o["value"] for o in laser["setting"]["options"]] == ["5", "10", "20", "40"]
    assert {"key": "lever", "label": "Lever"} in profile["telemetry"]["fields"]


def test_the_generated_profile_loads_as_it_was_written(tmp_path):
    """What Debug Mode receives is the folder's task.json through the profile
    loader: every row's setting survives it."""
    from ephymeris_sidecar.tasks.profile import load_profile

    install(every_type_rig())
    target = bundled.repin(FIRMWARE / "Utility" / "BOX_Utility", "Utility", tmp_path)
    written = json.loads((target / "task.json").read_text(encoding="utf-8"))
    loaded = load_profile(target).to_json()
    assert loaded["controls"] == written["controls"]
    assert grid_rows(loaded)["laser"][1]["setting"]["state"] == "laser.hz"


def test_every_setting_offered_is_one_the_board_takes():
    """The options are the generator's, the limits the board's and a spine
    row's (`taskdef/spine.py`'s DRIVE_VALUES): an option outside them would be
    a control that silently does nothing."""
    from ephymeris_sidecar.taskdef.spine import DRIVE_VALUES

    for drive, (_, suffix, _, values) in utility.SETTINGS.items():
        key = "duty" if suffix == "duty" else "hz"
        lo, hi = next((lo, hi) for k, *_, lo, hi in DRIVE_VALUES[drive] if k == key)
        assert all(lo <= n <= hi for _, n in values), drive
    width_ms = 5  # BoxUtility.h's BOX_UTIL_TRAIN_WIDTH_MS
    assert all(width_ms < 1000 // n for _, n in utility.SETTINGS["train"][3]), "width < period"


def test_every_output_but_the_sync_line_and_every_input_is_generated():
    """The property, over the rig itself: nothing is picked by a list of
    kinds, so no type or role can fall through."""
    install(every_type_rig())
    header = utility.utility_channels_h("BOX_Utility")
    outputs, inputs = header.split("#define BOX_UTILITY_INPUTS")
    for declared in registry.channels():
        if declared.type == "digital_in":
            assert f'{{"{declared.name}", ' in inputs, declared.name
        elif declared.role == "sync":
            assert declared.name not in header, "a pulse on the sync line is an edge in a recording"
        else:
            assert f'{{"{declared.name}", ' in outputs, declared.name


def test_identify_and_the_beam_mirror_never_take_a_driven_cue():
    """Identify lights a box while animals are placed: a cue declared before
    the trial light that plays a tone or runs a train must not be it."""
    doc = every_type_rig()
    doc["channels"] = {"speaker": doc["channels"].pop("speaker"), **doc["channels"]}
    install(doc)
    assert utility.utility_profile(TEMPLATE)["identify"] == {"on": "ON trial_light", "off": "OFF trial_light"}
    doc["channels"] = {k: v for k, v in doc["channels"].items() if k not in ("trial_light", "buzzer")}
    install(doc)
    assert "identify" not in utility.utility_profile(TEMPLATE), "a rig whose only cues are driven has none"


def _host_compiler() -> str | None:
    return shutil.which("clang++") or shutil.which("g++")


no_host_compiler = pytest.mark.skipif(_host_compiler() is None, reason="no host C++ compiler")
on_windows = pytest.mark.skipif(
    os.name == "nt", reason="clang on Windows compiles against MSVC's standard library, which "
    "needs C++14; the AVR build is C++11, so this runs on Linux and macOS")


def run_on_host(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """The generated table for the rig in force, through the real BOX_Utility.ino
    and BoxUtility.h on the instrumented host shim, with `body` as `main`."""
    (tmp_path / "UtilityChannels.h").write_text(
        utility.utility_channels_h("BOX_Utility"), encoding="utf-8"
    )
    host = FIRMWARE / "libraries" / "BehaviorBox" / "extras" / "host_test"
    source = tmp_path / "main.cpp"
    source.write_text(
        '#include <Arduino.h>\n'
        '#include <cstdio>\n'
        '#include "strobe_fixture.h"\n'
        f'#include "{tmp_path / "UtilityChannels.h"}"\n'
        f'#include "{FIRMWARE / "Utility" / "BOX_Utility" / "BOX_Utility.ino"}"\n'
        "static int failed = 0;\n"
        "static void check(const char *what, bool ok) {\n"
        "  if (!ok) { std::printf(\"FAIL %s\\n\", what); failed++; } }\n"
        "static void send(const char *line) { bb_feed(line); ::loop(); }\n"
        "static bool status(const char *token) {\n"
        "  size_t at = bb_output().rfind(\"STATUS \");\n"
        "  size_t end = bb_output().find('\\n', at);\n"
        "  return at != std::string::npos &&\n"
        "         (\" \" + bb_output().substr(at, end - at) + \" \").find(std::string(\" \") + token + \" \")\n"
        "             != std::string::npos; }\n"
        f"int main() {{\n{body}\n  return failed; }}\n",
        encoding="utf-8",
    )
    binary = tmp_path / "utility"
    built = subprocess.run(
        [_host_compiler(), "-std=c++11", "-Wall", "-Werror", "-Wno-unused-function",
         f"-I{host / 'box_shim'}", f"-I{host}", f"-I{host.parents[1]}",
         "-x", "c++", str(source), "-o", str(binary)],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, f"compile failed:\n{built.stdout}{built.stderr}"
    return subprocess.run([str(binary)], capture_output=True, text=True)


@no_host_compiler
@on_windows
def test_each_new_channel_responds_on_the_host(tmp_path):
    install(every_type_rig())
    ran = run_on_host(tmp_path, r"""
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;  // beams clear
  bb_pinValue[38] = LOW;                                         // the lever at rest
  ::setup();
  check("the lever is not pulled up", bb_pinMode[38] == INPUT);
  check("a shipped beam still is", bb_pinMode[2] == INPUT_PULLUP);
  check("a LOW lever is inactive", status("lever=0"));
  bb_pinValue[38] = HIGH; send("STATUS?");
  check("a HIGH lever is active", status("lever=1"));

  send("TOGGLE buzzer");
  check("a level line switches", digitalRead(47) == HIGH && status("buzzer=1"));

  check("PWM starts at full duty", status("house.duty=255"));
  send("DUTY house 64"); send("ON house");
  check("PWM drives its duty", bb_pwm[45] == 64 && status("house=1") && status("house.duty=64"));
  send("DUTY house 128");
  check("a new duty applies at once", bb_pwm[45] == 128);
  send("DUTY house 256");
  check("a duty past 255 is refused", bb_pwm[45] == 128 && status("house.duty=128"));
  send("HZ house 1000");
  check("HZ is not a PWM verb", status("house.duty=128") && bb_tone[45] == 0);
  send("OFF house");
  check("PWM off is LOW", digitalRead(45) == LOW && bb_pwm[45] == 0);

  check("a tone starts at 1 kHz", status("speaker.hz=1000"));
  send("HZ speaker 2000"); send("ON speaker");
  check("a tone plays its pitch", bb_tone[12] == 2000);
  send("HZ speaker 30");
  check("a tone under 31 Hz is refused", bb_tone[12] == 2000 && status("speaker.hz=2000"));
  send("DUTY speaker 10");
  check("DUTY is not a tone verb", bb_tone[12] == 2000);
  send("OFF speaker");
  check("a tone stops", bb_tone[12] == 0);

  check("a train starts at 20 Hz", status("laser.hz=20"));
  send("HZ laser 101");
  check("a train over 100 Hz is refused", status("laser.hz=20"));
  send("HZ laser 40"); send("ON laser");
  int rises = 0; bool was = true;
  unsigned long start = millis();
  while (millis() - start < 100) {
    ::loop();
    bool now = digitalRead(11) == HIGH;
    if (now && !was) rises++;
    was = now;
  }
  check("a 40 Hz train rises about every 25 ms", rises >= 3 && rises <= 4);
  send("OFF laser");
  check("a train ends LOW", digitalRead(11) == LOW);

  send("ALLOFF");
  check("ALLOFF keeps the settings", status("house.duty=128") && status("laser.hz=40"));
""")
    assert ran.returncode == 0, ran.stdout + ran.stderr


@no_host_compiler
@on_windows
def test_the_self_test_reaches_every_new_channel(tmp_path):
    install(every_type_rig())
    ran = run_on_host(tmp_path, r"""
  for (int i = 0; i < BB_MAX_PIN; i++) bb_pinValue[i] = HIGH;  // every beam clear
  bb_pinValue[38] = LOW;                                         // the lever at rest
  ::setup();
  send("SELFTEST");
  const std::string &out = bb_output();
  check("the laser fires with the stimulus lines",
        out.find("  Laser \302\267 test train (laser)") != std::string::npos);
  check("with the routing lines on, by label", out.find("with vacuum on") != std::string::npos);
  check("the buzzer blinks", out.find("Cue, six blinks: Buzzer (buzzer)") != std::string::npos);
  check("the PWM line blinks", out.find("Cue, six blinks: House light (house)") != std::string::npos);
  check("the speaker blinks",
        out.find("Cue, six blinks: Speaker \302\267 test tone (speaker)") != std::string::npos);
  check("every input reads inactive at rest, the lever by its own level",
        out.find("[pass] every sensor reads clear at rest") != std::string::npos);
  check("the lever is prompted", out.find("press the Lever") != std::string::npos);
  check("and the box is left off", digitalRead(11) == LOW && bb_tone[12] == 0 && bb_pwm[45] == 0);
""")
    assert ran.returncode == 0, ran.stdout + ran.stderr


# --------------------------------------------------------------------------- #
# Nothing in the utility names a channel
# --------------------------------------------------------------------------- #


def _shipped_names() -> set[str]:
    return registry.shipped_channels().names()


def _code_without_comments(text: str) -> str:
    """C, C++ or TypeScript with its comments removed. String literals stay:
    a channel name in one is exactly a hand-listed channel."""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"(?<![:\"'])//[^\n]*", " ", text)


def _python_strings(path: Path) -> list[str]:
    """Every string constant in a Python module but its docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings]


def _named(text: str, names: set[str]) -> list[str]:
    return sorted(n for n in names if re.search(rf"(?<![\w.]){re.escape(n)}(?!\w)", text))


UTILITY_SOURCES = (
    FIRMWARE / "libraries" / "BehaviorBox" / "BoxUtility.h",
    *sorted((FIRMWARE / "Utility" / "BOX_Utility").glob("*.ino")),
    *sorted((FIRMWARE / "Utility" / "BOX_Utility").glob("*.h")),
)
DEBUG_MODE_SOURCES = (
    REPO / "src" / "components" / "debug" / "UtilityControls.tsx",
    REPO / "src" / "components" / "debug" / "PrimeControls.tsx",
    REPO / "src" / "components" / "debug" / "all" / "BroadcastControls.tsx",
)


@pytest.mark.parametrize("path", UTILITY_SOURCES, ids=lambda p: p.name)
def test_the_firmware_hand_lists_no_channel(path):
    assert _named(_code_without_comments(path.read_text(encoding="utf-8")), _shipped_names()) == []


def test_the_template_and_the_generator_hand_list_no_channel():
    names = _shipped_names()
    assert _named(json.dumps(TEMPLATE), names) == []
    assert _named("\n".join(_python_strings(Path(utility.__file__))), names) == []


@pytest.mark.parametrize("path", DEBUG_MODE_SOURCES, ids=lambda p: p.name)
def test_debug_mode_hand_lists_no_channel(path):
    """The panel renders what the profile declares. A kind is a colour family
    and may be named (`vacuum` is one); a channel is not."""
    names = _shipped_names() - set(registry.KIND_DEFAULTS)
    assert _named(_code_without_comments(path.read_text(encoding="utf-8")), names) == []


def test_the_hand_listing_check_can_fail():
    """The checks above pass on clean sources; this proves each reader would
    not on a dirty one."""
    names = _shipped_names()
    assert _named(_code_without_comments('// fluid_0\nint x = read("fluid_0");'), names) == ["fluid_0"]
    assert _named(_code_without_comments('/* trial_light */ const char *k = "x";'), names) == []
    assert _named(json.dumps({"command": "TOGGLE odor_line_3"}), names) == ["odor_line_3"]
    assert _named("house.duty odor_line_10", names) == ["odor_line_10"], "no prefix match"
    assert _named("\n".join(_python_strings(Path(__file__))), {"odor_port"}) == ["odor_port"]
