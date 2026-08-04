"""The shipping firmware still carries the changes the model requires.

`Arduino/patches/0001-behaviorbox-model-conformance.patch` has been applied to the
firmware repo. This file is what stops it from quietly coming back out.

WHY THIS EXISTS SEPARATELY FROM GATE B. Gate B would catch a reverted strobe order
or a reverted omission code, because it walks both implementations and compares the
streams. It would not catch two things:

  * the `task.json` strobe mirrors. Nothing in the trial loop reads them, so a code
    the firmware emits and the table fails to name reaches Ephymeris as a bare
    number and no gate anywhere notices;
  * the shape of the fix rather than its effect. `while (digitalRead(pokedWell))`
    reappearing is worth naming as itself, not as "seed 1 diverged at trial 812".

The firmware repo is developed independently of this one, so these assertions read
its files directly. They are the contract between the two repos, written down.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec,
)
from tests.compiler.tgpaths import firmware_repo  # noqa: E402

FIRMWARE_REPO = firmware_repo()
BEHAVIORBOX = FIRMWARE_REPO / "libraries" / "BehaviorBox" / "BehaviorBox.h"
PATCH = FIRMWARE / "patches" / "0001-behaviorbox-model-conformance.patch"

pytestmark = pytest.mark.skipif(
    not BEHAVIORBOX.is_file(), reason="needs the reference BehaviorBox.h"
)


@pytest.fixture(scope="module")
def firmware() -> str:
    return BEHAVIORBOX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def resp_omit() -> int:
    vocab = json.loads((SCHEMA_DIR / "strobe_vocab.v1.json").read_text(encoding="utf-8"))
    return vocab["codes"]["RESP_OMIT"]["code"]


def test_the_checked_in_patch_is_the_change_that_landed():
    """The patch reverse-applies, which is the same statement as "it is applied".

    Keeping it checked in after the fact is what makes the change reviewable as a
    unit six months from now -- `git log` on the firmware repo will show it folded
    into whatever commit it shipped in. If the two ever drift, that is worth
    knowing, and this is cheaper than diffing by eye.
    """
    r = subprocess.run(
        ["git", "apply", "--reverse", "--check", str(PATCH)],
        cwd=FIRMWARE_REPO, capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "the checked-in patch no longer describes what is in the firmware repo:\n"
        f"{r.stderr}\n"
        "Either a change was reverted, or the firmware moved and the patch should "
        "be regenerated or retired."
    )


def test_the_well_unpoke_wait_tests_the_right_edge(firmware):
    """docs/firmware-changes.md #0, the one that could hang a box.

    INPUT_PULLUP means HIGH = unpoked, so a bare truthiness test waits for a POKE.
    The explicit comparison is the whole fix, and it must match the identical wait
    on the odor port.
    """
    assert "while (digitalRead(pokedWell) == LOW)" in firmware
    assert "while (digitalRead(pokedWell))" not in firmware, (
        "the inverted well-unpoke wait is back: this both mis-times every "
        "WATER_UNPOKE_* and hangs the box when an animal leaves during the pulse"
    )
    assert "while (digitalRead(odorPort) == LOW)" in firmware, (
        "the odor-port wait changed shape; the two are meant to read alike"
    )


def test_an_omission_announces_itself(firmware, resp_omit):
    """docs/firmware-changes.md #2. END_INCORRECT_ITI is reached by three different
    outcomes, so without this the class is recoverable only from the preceding
    strobe -- and an omission has none."""
    assert f"#define BF_RESP_OMIT            {resp_omit} " in firmware, (
        f"firmware does not define BF_RESP_OMIT as the schema's {resp_omit}"
    )
    assert "emitStrobe(clock, BF_RESP_OMIT);" in firmware


def test_cue_off_follows_the_behavioural_strobe(firmware):
    """docs/firmware-changes.md #1. The behavioural strobe reports what happened;
    LIGHTS_OFF reports a consequence of it. Reading a stream, you want the event
    before its consequences -- and one consistent order is what let the
    `cue_off_placement` topology knob be deleted rather than kept for a quirk."""
    ordered = {
        "abstention": ("BF_LAZY_RAT", 1),
        "hold broken": ("BF_ODOR_UNPOKE_EARLY", 2),
    }
    for path, (partner, count) in ordered.items():
        right = f"emitStrobe(clock, {partner});\n    emitStrobe(clock, BF_LIGHTS_OFF);"
        wrong = f"emitStrobe(clock, BF_LIGHTS_OFF);\n    emitStrobe(clock, {partner});"
        # The abstention path sits one block deeper; compare on stripped lines so
        # indentation is not what this test is really asserting.
        flat = "\n".join(ln.strip() for ln in firmware.splitlines())
        right = right.replace("\n    ", "\n")
        wrong = wrong.replace("\n    ", "\n")
        assert flat.count(right) == count, f"{path}: expected {count} site(s) in model order"
        assert wrong not in flat, f"{path}: LIGHTS_OFF is back in front of {partner}"


def test_every_task_json_names_the_new_code(resp_omit):
    """The BF_* block calls itself a "mirror of task.json `strobes`". A code the
    firmware emits but the table does not name reaches Ephymeris as a bare number,
    and nothing in the trial loop would ever notice."""
    tables = [
        p for p in FIRMWARE_REPO.rglob("task.json")
        if ".retired" not in p.parts and "strobes" in json.loads(p.read_text(encoding="utf-8"))
    ]
    assert len(tables) == 7, f"expected 7 strobe tables, found {len(tables)}"
    for p in tables:
        strobes = json.loads(p.read_text(encoding="utf-8"))["strobes"]
        assert strobes.get(str(resp_omit)) == "RESP_OMIT", (
            f"{p.relative_to(FIRMWARE_REPO)} does not name {resp_omit}"
        )
