"""GATE F — a whole session with anti-bias, correction and escalation live.

Gate E runs the no-policy configuration, which is what the four shaping sketches
pass and is a real thing that ships. This is the harder half.

It is hard because `runTrial()` calls into the policy objects from *inside* the
trial — `recordChoice` at BehaviorBox.h:1084, `recordAbstention` at :1161, :1183
and :1199, `shouldRepeat` at :1231 — and `tgRunTrial()` calls nothing, because
policy stays outside the interpreter. The session layer has to make the same
calls, at the same moments, with the same arguments, from facts the walk reports.

WHY IT IS A SHARP TEST. The anti-bias estimator is a ring buffer over expressed
sides, so a single mis-attributed vote changes every draw after it. A wrong
reconstruction does not produce a subtle difference — the two sessions part on
trial selection within a handful of trials and never rejoin.

THE THREE CLASSES ARE THE SAME OBJECTS ON BOTH SIDES, constructed identically and
fed the same START parameters. What is under test is not their arithmetic but
*when* they are called and *with what*.
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
def gate_f(tmp_path_factory):
    r = compile_spec(spec("grgl_2odor"))
    assert r.ok, r.bag.render()
    (HOST_TEST / "grgl_table.h").write_text(emit(r.table))
    binary = tmp_path_factory.mktemp("gate_f") / "gate_f"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_f.cpp"), "-o", str(binary)],
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
def test_policy_driven_sessions_are_stream_identical(gate_f, seed):
    """THE GATE.

    Anti-bias selection, per-side correction budgets and the escalating
    abstention penalty, all live, on both sides. Every strobe, every timestamp,
    twenty sessions of forty completed trials.
    """
    r = run(gate_f, seed)
    assert r["diverged"] == 0, (
        f"seed {seed}: {r['diverged']} of {r['compared']} sessions differ\n\n{r['_raw']}"
    )
    assert r["compared"] == r["sessions"]


@pytest.mark.parametrize("seed", SEEDS)
def test_the_sessions_are_long_enough_for_policy_to_bite(gate_f, seed):
    """Forty completed trials with a budget of three per side, an escalator that
    reaches its ceiling, and a bias ring of twenty. A shorter run would compare
    two policies that had barely started."""
    r = run(gate_f, seed)
    assert r["events"] > 10000, f"only {r['events']} strobes compared\n\n{r['_raw']}"


def test_the_facts_the_policy_needs_are_facts_about_the_walk(gate_f):
    """The interpreter must not have learned any task vocabulary.

    Everything the session layer needs is derived from the watch mapping and the
    triggers — `engaged`, `broke`, `offered`, `enteredPort`. If a name like
    `odor` or `well` ever appears in the interpreter, policy has leaked inward and
    the thing that made it reusable is gone.
    """
    #: CODE only. The header's prose says "no odors, no wells, no shaping
    #: schedule" — which is the claim, not a violation of it — and matching raw
    #: text flagged exactly that sentence.
    src = (LIB / "TgInterpret.h").read_text()
    code = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code).lower()

    #: The precise invariant: the interpreter never names a policy TYPE and never
    #: calls one. `correctionBudget` is a parameter — the caller's answer to "does
    #: this side still have budget", passed as a bool — and that IS the design, so
    #: a blunt search for "correction" flagged the very thing that keeps policy
    #: outside.
    for kind in ("AntiBiasSelector", "AbstentionPenalty", "CorrectionPolicy",
                 "TrialPolicy"):
        assert kind.lower() not in code, (
            f"the interpreter names {kind}; policy has leaked into the one "
            f"component that must stay fixed"
        )
    for call in ("recordchoice", "recordabstention", "nextdelay", "shouldrepeat",
                 "selectnext", "onadvance"):
        assert call not in code, f"the interpreter calls {call}(); policy must stay outside"

    #: And no task vocabulary. `rewardLine`/`rewardCode` are table FIELDS — the
    #: interpreter opens whichever line a row names and never knows what is in it.
    for word in ("odor", "lazyrat", "shaping"):
        assert word not in code, f"the interpreter mentions {word!r}"
    assert not re.search(r"\bwell\b", code)


def test_the_escalator_and_the_selector_do_not_fire_together(gate_f):
    """The bug this gate found second, asserted where a reader will meet it.

    `recordAbstention` is called from all three abort paths; `nextDelay` only from
    the no-engagement one, because a broken hold is penalised with a flat
    `noPokeHoldTimeout` and leaves the escalator alone. Counting all three
    escalated one step early on every hold break, which showed up as a 6000 ms
    difference in a penalty six trials later.
    """
    src = (HOST_TEST / "gate_f.cpp").read_text()
    body = src[src.index("case TG_OUTCOME_ABSTAINED:"):]
    body = body[: body.index("break;")]
    assert "if (!r.engaged)" in body, (
        "the escalator advances on every abstention again; it must advance only "
        "when the subject never engaged"
    )
