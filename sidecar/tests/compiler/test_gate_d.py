"""GATE D — the actuators, not the strobes. And reward volume above all.

The roadmap names this gap in so many words: *"the equivalence gate proved the
strobe stream; it did not prove actuator timing, and reward volume is a solenoid
open-time."*

Gates A, B and C all compare what the box SAID. A box can say exactly the right
thing while opening the wrong valve, holding it open for the wrong duration, or
leaving the vacuum closed — and the odor lines and the vacuum emit no strobe at
all, so on those channels the earlier gates were not weak evidence, they were no
evidence.

WHAT THIS IS NOT. Not a substitute for a scope. It proves the two implementations
produce the same waveform on the same mock clock; it says nothing about what a real
MOSFET and a real solenoid do with it. That is the bench half of Phase 5 and it
needs hardware. What this removes is the possibility that a bench discrepancy is
the INTERPRETER's fault rather than the rig's.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ephymeris_sidecar.taskgraph.emit.c_table import emit
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.table import DUR_FROM_TRIAL, NodeType

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, grgl_equivalent, spec,
)

LIB = FIRMWARE_LIB

SPECS = all_specs()

SEEDS = (20260803, 1, 424242)
TRIALS = 2000


# --------------------------------------------------------------------------- #
# Reward volume, at the compiler
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_every_reward_pulse_is_the_volume_the_spec_declared(spec_id):
    """THE NUMBER TO CHECK HARDEST.

    Pulse width *is* delivered magnitude, and it is the one duration resolved per
    trial rather than from the timing vector — which is exactly where Phase 1's
    one compiler bug lived. Checked against the SPEC's YAML rather than against
    anything else the compiler produced, so a compiler that resolved the wrong
    entry cannot agree with itself.
    """
    path = spec(spec_id)
    doc = yaml.safe_load(path.read_text())
    declared_ms = {t["id"]: t["ms"] for t in doc["timing"]}
    ports_yaml = doc["contingency"]["ports"]

    t = compile_spec(path).table
    for i, port in enumerate(t.ports):
        want_id = ports_yaml[port.name].get("reward_duration")
        if want_id is None:
            continue  # a port that delivers nothing -- go/no-go's withhold side
        assert port.reward_dur_idx < len(t.timing), f"{port.name}: index out of range"
        assert t.timing[port.reward_dur_idx] == declared_ms[want_id], (
            f"{spec_id} port {port.name!r} would open its line for "
            f"{t.timing[port.reward_dur_idx]} ms; the spec declares "
            f"{want_id}={declared_ms[want_id]} ms"
        )
        assert t.timing_ids[port.reward_dur_idx] == want_id, (
            f"{spec_id} port {port.name!r} resolves to {t.timing_ids[port.reward_dur_idx]!r}, "
            f"not the declared {want_id!r} — same value today, wrong entry tomorrow"
        )
        del i


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_the_reward_pulse_is_resolved_per_trial(spec_id):
    """It must be the trial-bound duration, not a fixed timing index.

    A PULSE that read its width from the timing vector would deliver the same
    volume to both wells — correct today for the two-sided tasks, where both are
    100 ms, and silently wrong the moment anyone sets them apart.
    """
    t = compile_spec(spec(spec_id)).table
    pulses = [n for n in t.nodes if n.type is NodeType.PULSE]
    if not pulses:
        return  # go/no-go's withhold path has no reward state at all
    for n in pulses:
        assert n.dur_idx == DUR_FROM_TRIAL, (
            f"{spec_id}: PULSE {n.label!r} takes its width from timing entry "
            f"{n.dur_idx}, so every port would deliver the same volume"
        )


# --------------------------------------------------------------------------- #
# The waveform, at runtime
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def gate_d(tmp_path_factory):
    r = compile_spec(grgl_equivalent())
    assert r.ok, r.bag.render()
    (HOST_TEST / "grgl_table.h").write_text(emit(r.table))
    binary = tmp_path_factory.mktemp("gate_d") / "gate_d"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "gate_d.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    return binary


def run(binary, seed: int) -> dict:
    out = subprocess.run(
        [str(binary), str(seed), str(TRIALS)], capture_output=True, text=True
    ).stdout
    got: dict[str, int] = {}
    for key in ("trials", "checked", "diverged", "hangs", "same-instant-reorder",
                "rewards", "wrong", "left-open"):
        m = re.search(rf"\b{re.escape(key)}=(\d+)", out)
        if m:
            got[key] = int(m.group(1))
    got["_raw"] = out
    return got


pytestmark_cpp = pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)


@pytestmark_cpp
@pytest.mark.parametrize("seed", SEEDS)
def test_the_waveforms_are_identical(gate_d, seed):
    """THE GATE.

    Every level transition on every pin — which pin, which direction, and at what
    millisecond — identical between the interpreter and runTrial(), on the same
    scripted animal.

    One class of difference is classified rather than counted: the two clear the
    cue-off actuators in a different ORDER within a single millisecond. Sorting
    each same-timestamp group by pin collapses exactly that and nothing else, so a
    difference the sort cannot explain is a real difference in what the hardware
    was told to do.
    """
    r = run(gate_d, seed)
    assert r["diverged"] == 0, (
        f"seed {seed}: {r['diverged']} of {r['checked']} trials drive the hardware "
        f"differently\n\n{r['_raw']}"
    )
    assert r["checked"] == r["trials"]


@pytestmark_cpp
@pytest.mark.parametrize("seed", SEEDS)
def test_no_actuator_is_left_energised(gate_d, seed):
    """A trial that ends with a valve open is a flooded well or an odor line
    venting into an empty box, and no strobe anywhere reports it."""
    r = run(gate_d, seed)
    assert r["left-open"] == 0, f"seed {seed}\n\n{r['_raw']}"


@pytestmark_cpp
@pytest.mark.parametrize("seed", SEEDS)
def test_every_delivered_reward_is_the_declared_volume(gate_d, seed):
    """The runtime half of the volume check: measured open-time against the table,
    on real trials rather than on the compiled numbers."""
    r = run(gate_d, seed)
    assert r["wrong"] == 0, f"seed {seed}: wrong pulse width\n\n{r['_raw']}"
    assert r["rewards"] >= 300, (
        f"seed {seed}: only {r['rewards']} rewards delivered, so the volume check "
        f"barely ran\n\n{r['_raw']}"
    )


@pytestmark_cpp
def test_the_ordering_class_is_real_and_bounded(gate_d):
    """The allowance, asserted so it cannot quietly grow.

    If it ever reached every trial, something would have changed about when the
    cue-off actuators are written rather than merely in what order — and the
    classification would be hiding it.
    """
    r = run(gate_d, SEEDS[0])
    assert 0 < r["same-instant-reorder"] < r["checked"], (
        "the same-instant class is either empty (so the sort is doing nothing) or "
        "universal (so it is hiding something)"
    )
