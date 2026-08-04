"""GATE E — a whole session, not a trial.

Gates A–D each compare ONE trial, from a clean clock, with the session's state
reset. A session is not a sequence of independent trials: the stage ramp moves
with the completed count, an aborted trial re-presents the same side,
INVALID_TRIAL is a terminal the loop must NOT duplicate, and the clock runs
continuously from START_SESSION. None of that is exercised per-trial, and all of
it is what the roadmap's parallel run would actually compare.

WHAT IT DOES NOT COVER, AND THIS IS A REAL LIMIT. `runTrial()` calls into the
policy objects from inside the trial; `tgRunTrial()` calls nothing, because policy
stays outside the interpreter. So anti-bias selection, correction budgets and
penalty escalation are not wired, and a session using them would diverge on trial
selection alone. Rather than invent a hook and then validate the invention, this
runs the configuration that already ships without them — nullptr policy, which is
what all four shaping sketches pass.
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
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)

LIB = FIRMWARE_LIB


SEEDS = (20260803, 1, 424242)
SESSIONS = 20
TRIALS = 40

pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytest.fixture(scope="module")
def gate_e(tmp_path_factory):
    r = compile_spec(spec("grgl_2odor"))
    assert r.ok, r.bag.render()
    (HOST_TEST / "grgl_table.h").write_text(emit(r.table))
    binary = tmp_path_factory.mktemp("gate_e") / "gate_e"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_e.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


def run(binary, seed: int) -> dict:
    out = subprocess.run(
        [str(binary), str(seed), str(SESSIONS), str(TRIALS)],
        capture_output=True, text=True,
    ).stdout
    got: dict[str, int] = {}
    for key in ("sessions", "compared", "diverged", "events"):
        m = re.search(rf"\b{key}=(\d+)", out)
        if m:
            got[key] = int(m.group(1))
    got["_raw"] = out
    return got


@pytest.mark.parametrize("seed", SEEDS)
def test_a_whole_session_is_stream_identical(gate_e, seed):
    """THE GATE.

    START_SESSION to END_SESSION, every strobe, every timestamp, across twenty
    sessions of forty completed trials each.
    """
    r = run(gate_e, seed)
    assert r["diverged"] == 0, (
        f"seed {seed}: {r['diverged']} of {r['compared']} sessions differ\n\n{r['_raw']}"
    )
    assert r["compared"] == r["sessions"], "sessions were skipped, not compared"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_sessions_are_long_enough_to_mean_something(gate_e, seed):
    """Forty completed trials is enough to cross several stage-ramp boundaries and
    to accumulate the repeats an abort produces. A gate over two-trial sessions
    would prove almost nothing about a session."""
    r = run(gate_e, seed)
    assert r["events"] > 8000, f"only {r['events']} strobes compared\n\n{r['_raw']}"


def test_invalid_trial_is_not_emitted_twice(gate_e):
    """The bug this gate found on its first run.

    GRGL_2-Odor.ino:175 emits INVALID_TRIAL from the loop, because runTrial()
    cannot. In the model it is a TERMINAL's entry strobe (D20) — it has to be,
    since a wrong answer under an unspent correction budget emits
    END_INCORRECT_ITI *and then* INVALID_TRIAL, and two strobes in that order mean
    two nodes in that order. A session layer that copied the sketch faithfully
    doubled it.

    Asserted through the gate rather than by grepping: a duplicate strobe is a
    stream difference, and the stream is what is compared.
    """
    src = (FIRMWARE_LIB / "TgSession.h").read_text()
    body = src[src.index("inline TgTrialResult tgSessionTrial"):]
    assert "emitStrobe" not in body, (
        "the session layer emits a strobe; the graph already carries INVALID_TRIAL"
    )
    assert run(gate_e, SEEDS[0])["diverged"] == 0
