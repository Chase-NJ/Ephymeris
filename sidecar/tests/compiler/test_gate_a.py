"""GATE A — the C++ interpreter must emit exactly what the Python reference does.

Two independent implementations of the same compiled table, driven by the same
scripted animal, compared byte for byte.

WHY THIS GATE COMES FIRST. Gate B compares the interpreter against `runTrial()`,
and until the firmware changes in `docs/firmware-changes.md` land, some of those
differences are EXPECTED. If the interpreter also had bugs, the two kinds of
difference would be indistinguishable and every Gate B failure would need
adjudicating by hand. Passing Gate A first makes every Gate B difference
unambiguously firmware-versus-model.

BOTH SIDES READ ONE TABLE. `taskgraph/emit/c_table.py` emits the compiled table as
a C initialiser and the C++ test includes it. Hand-transcribing it would be a third
copy that can drift, and drift there looks exactly like an interpreter bug.

Skips if there is no C++ toolchain, which is the only thing here that is not
already in the repo.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.c_table import emit
from ephymeris_sidecar.taskgraph.interpret import Act, Interpreter, ScriptedSubject
from ephymeris_sidecar.taskgraph.pipeline import compile_spec

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, spec,
)

LIB = FIRMWARE_LIB


pytestmark = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)

#: The same eight scripts the C++ side runs, expressed as the Python subject sees
#: them. Kept in step by name: a mismatch shows up as a missing key, not as a
#: silently different animal.
#:
#: Each entry is (trial_type_index, [Act, ...]). The Acts answer, in order, the
#: states that ask: engagement window, commitment hold, sampling hold, sampling
#: release, response window, response hold, consumption.
SCRIPTS: dict[str, tuple[int, list[Act]]] = {
    "correct_right": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True), Act(sustained=True),
        Act(dwell=300), Act(dwell=300, channel="right_well"), Act(sustained=True),
        Act(dwell=1000),
    ]),
    "wrong_port": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True), Act(sustained=True),
        Act(dwell=300), Act(dwell=300, channel="left_well"),
    ]),
    "omission": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True), Act(sustained=True),
        Act(dwell=300), Act(channel=None),
    ]),
    "abstention": (0, [Act(channel=None)]),
    "break_commit_hold": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=False, dwell=200),
    ]),
    "break_sampling_hold": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True),
        Act(sustained=False, dwell=100),
    ]),
    "response_hold_broken": (0, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True), Act(sustained=True),
        Act(dwell=300), Act(dwell=300, channel="right_well"),
        Act(sustained=False, dwell=50),
    ]),
    "correct_left": (1, [
        Act(dwell=300, channel="odor_port"), Act(sustained=True), Act(sustained=True),
        Act(dwell=300), Act(dwell=300, channel="left_well"), Act(sustained=True),
        Act(dwell=1000),
    ]),
}


@pytest.fixture(scope="module")
def compiled():
    r = compile_spec(spec("two_afc"))
    assert r.ok, r.bag.render()
    return r


@pytest.fixture(scope="module")
def cpp_streams(compiled, tmp_path_factory):
    """Build and run the C++ side, returning name -> (verdict, [(code, t), ...])."""
    (HOST_TEST / "grgl_table.h").write_text(emit(compiled.table))
    binary = tmp_path_factory.mktemp("gate_a") / "gate_a"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_a.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    out = subprocess.run([str(binary)], check=True, capture_output=True, text=True).stdout

    streams = {}
    for line in out.strip().splitlines():
        parts = line.split("\t")
        name, verdict = parts[0], parts[1]
        events = []
        for tok in parts[2:]:
            code, _, t = tok.partition("@")
            events.append((int(code), int(t)))
        streams[name] = (verdict, events)
    return streams


def python_stream(compiled, trial_index: int, script: list[Act]):
    it = Interpreter(compiled.spec, compiled.table)
    tt = compiled.spec.contingency.trial_types[trial_index]
    tr = it.run_trial(tt, ScriptedSubject(list(script)))
    verdict = "ADVANCE" if tr.ended == "TRIAL_ADVANCE" else "REPEAT"
    return verdict, [(e.code, e.t) for e in tr.emissions]


def test_the_cpp_side_actually_ran(cpp_streams):
    """A build that silently produced nothing would make every comparison below
    vacuous -- the same failure mode that made the first harness capture zero
    strobes."""
    assert set(cpp_streams) == set(SCRIPTS)
    assert all(events for _, events in cpp_streams.values())


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_streams_are_byte_identical(name, compiled, cpp_streams):
    """THE GATE. Same table, same animal, same stream -- codes, order, and timings."""
    trial_index, script = SCRIPTS[name]
    py_verdict, py_events = python_stream(compiled, trial_index, script)
    cpp_verdict, cpp_events = cpp_streams[name]

    def fmt(events):
        from ephymeris_sidecar.taskgraph.registries import vocabulary

        v = vocabulary()
        return " ".join(f"{v.name_of(c) or c}@{t}" for c, t in events)

    assert py_verdict == cpp_verdict, (
        f"{name}: python says {py_verdict}, C++ says {cpp_verdict}"
    )
    assert py_events == cpp_events, (
        f"{name} diverges:\n  python: {fmt(py_events)}\n  c++   : {fmt(cpp_events)}"
    )


def test_every_outcome_class_is_covered(compiled, cpp_streams):
    """A gate that only ever drove the correct path would pass while the error
    branches were broken. Assert the battery reaches every terminal state the
    graph has."""
    reached = set()
    for _verdict, events in cpp_streams.values():
        reached |= {c for c, _ in events}
    from ephymeris_sidecar.taskgraph.registries import vocabulary

    v = vocabulary()
    for required in ("END_CORRECT_ITI", "END_INCORRECT_ITI", "INVALID_TRIAL",
                     "LAZY_RAT", "ODOR_UNPOKE_EARLY", "RESP_OMIT",
                     "WATER_POKE_ERROR_L", "WATER_UNPOKE_EARLY_R"):
        assert v.code_of(required) in reached, f"no script reaches {required}"
