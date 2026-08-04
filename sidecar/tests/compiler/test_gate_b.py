"""GATE B — the interpreter must emit exactly what runTrial() emits.

THE CRUX. Everything before this is preparation; everything after is comparatively
mechanical. Replacing a hand-verified trial loop with a table interpreter is a
change nobody can partially trust: either the two provably agree, or the lab keeps
flashing the old firmware and this work dies at 90% complete.

Compared against the MODEL table (template v2). This gate spent Phase 3 comparing
against the as-built v1 table with one documented allowance, because firmware had
not yet shipped docs/firmware-changes.md. It has. So the allowance is gone and the
bar is the one it was always meant to be:

    NOTHING DIFFERS, AND NEITHER SIDE HANGS.

No explained-difference class, no tolerated remainder. The as-built fixture stays
alive for tests/test_corpus_replay.py, where it belongs -- the recorded sessions
predate the firmware change and always will.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.c_table import emit
from ephymeris_sidecar.taskgraph.pipeline import compile_spec

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, grgl_equivalent, spec,
)

LIB = FIRMWARE_LIB

MODEL = grgl_equivalent()

#: Three seeds, so a pass is not one lucky draw. Kept modest per seed because the
#: battery is exhaustive per trial, not per run -- 9000 trials covers every
#: outcome class hundreds of times over.
SEEDS = (20260803, 1, 424242)
TRIALS = 3000

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytest.fixture(scope="module")
def gate_b(tmp_path_factory):
    """Build the battery against the model table."""
    r = compile_spec(MODEL)
    assert r.ok, r.bag.render()
    assert r.table.template_version == 2, "Gate B compares against the MODEL graph"
    (HOST_TEST / "grgl_table.h").write_text(emit(r.table), encoding="utf-8")

    binary = tmp_path_factory.mktemp("gate_b") / "gate_b"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_b.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


def run_battery(binary, seed: int, trials: int = TRIALS) -> dict:
    out = subprocess.run(
        [str(binary), str(seed), str(trials)], capture_output=True, text=True
    ).stdout
    got: dict[str, int] = {}
    for key in ("trials", "checked", "diverged", "hangs", "runTrial", "interpreter",
                "correct", "wrong", "omission", "abstain", "holdbreak", "holdfail"):
        m = re.search(rf"\b{re.escape(key)}=(\d+)", out)
        if m:
            got[key] = int(m.group(1))
    got["_raw"] = out
    return got


@pytest.mark.parametrize("seed", SEEDS)
def test_the_streams_are_identical(gate_b, seed):
    """THE GATE.

    Same table, same scripted animal: same codes, same order, same timestamps,
    same advance/repeat verdict. Every trial. Any difference at all is one of the
    two implementations being wrong, and that is worth failing a build over.
    """
    r = run_battery(gate_b, seed)
    assert r["diverged"] == 0, (
        f"seed {seed}: {r['diverged']} of {r['checked']} trials differ\n\n{r['_raw']}"
    )
    assert r["checked"] == r["trials"], (
        f"seed {seed}: only {r['checked']} of {r['trials']} trials were compared, so "
        f"the count above is not the whole battery\n\n{r['_raw']}"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_neither_side_hangs(gate_b, seed):
    """A box that stops with an animal in it is the failure this project exists to
    prevent.

    This asserted `interpreter == 0` while runTrial() still hung ~1% of the time on
    the inverted well-unpoke wait. That is fixed, so the bar is both sides: a hang
    reappearing in EITHER is the same emergency.
    """
    r = run_battery(gate_b, seed)
    assert r["hangs"] == 0, (
        f"seed {seed}: {r['runTrial']} runTrial and {r['interpreter']} interpreter "
        f"hangs\n\n{r['_raw']}"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_the_battery_covers_every_outcome(gate_b, seed):
    """A battery that only drove the correct path would pass while every error
    branch was broken. Assert each outcome class is exercised enough times to
    mean something."""
    r = run_battery(gate_b, seed)
    for cls in ("correct", "wrong", "omission", "abstain", "holdbreak", "holdfail"):
        assert r[cls] >= 50, f"seed {seed}: only {r[cls]} {cls} trials\n\n{r['_raw']}"
