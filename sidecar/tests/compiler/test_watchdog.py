"""The watchdog — and the compiler bug that would have made it useless.

Two halves, and the second is the one that is easy to get wrong.

A watchdog that never fires is dead code that reads as safety. A watchdog that
fires on a HEALTHY trial ends real sessions, which is a worse outcome than the
hang it exists to prevent — a hang is at least obviously broken, whereas a box
that quietly abandons every fifth trial looks like a subject having a bad day.

THE BUG THIS FOUND. `max_dwell_ms` was computed from the COMPILED timing vector.
The stage ramp rewrites that vector at runtime, so in `shaping_gr` three nodes
carried a 10 ms budget against a live duration reaching 500 ms — 50x too small,
by the fourth stage row, on every trial. A watchdog built on those numbers would
have ended essentially every healthy shaping session. The budgets are now taken
from the PEAK value each timing entry can hold.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.c_table import emit
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.registries import limits, vocabulary
from ephymeris_sidecar.taskgraph.table import DUR_FROM_TRIAL

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, all_specs, shaping_ramped, spec,
)

LIB = FIRMWARE_LIB

SPECS = all_specs()


# --------------------------------------------------------------------------- #
# The compiler's budgets
# --------------------------------------------------------------------------- #


def peak_timing(table) -> list[int]:
    """The largest value each timing entry ever takes, computed here rather than
    imported — so this checks the compiler's answer against an independent one
    instead of comparing it with itself."""
    peak = list(table.timing)
    for s in table.timing_sets:
        peak[s.idx] = max(peak[s.idx], s.ms)
    return peak


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_no_budget_is_smaller_than_the_state_it_bounds(spec_id):
    """THE INVARIANT THE WATCHDOG RESTS ON.

    A budget below the state's own live duration is a guaranteed false trip. This
    is stated over the PEAK vector, because the stage ramp can raise any entry it
    addresses at any point in a session.
    """
    t = compile_spec(spec(spec_id)).table
    peak = peak_timing(t)
    for i, n in enumerate(t.nodes):
        budget = t.max_dwell[i]
        if budget is None or n.dur_idx == DUR_FROM_TRIAL or n.dur_idx >= len(peak):
            continue
        assert budget >= peak[n.dur_idx], (
            f"S{i:02d} {n.label!r}: budget {budget} ms is below the {peak[n.dur_idx]} ms "
            f"its duration {t.timing_ids[n.dur_idx]!r} reaches on the stage ramp — "
            f"the watchdog would end healthy sessions"
        )


def test_the_ramp_actually_raises_something():
    """The test above is vacuous on a task whose timings never move.

    A generated skeleton ships no ramp -- the paradigm names which ids ramp, not
    how far -- so this builds the lab's actual shaping schedule, which is what
    the wizard's ramp step produces. These are the three nodes that were wrong.
    """
    t = compile_spec(shaping_ramped()).table
    ramped = {t.timing_ids[s.idx] for s in t.timing_sets}
    assert {"t_commit_hold", "t_sample_hold", "t_resp_hold"} <= ramped

    by_label = {n.label: i for i, n in enumerate(t.nodes)}
    for label in ("commitment hold", "present stimulus", "response hold"):
        i = by_label[label]
        compiled = t.timing[t.nodes[i].dur_idx]
        assert t.max_dwell[i] > compiled, (
            f"{label}: budget {t.max_dwell[i]} equals the compiled {compiled}, so it "
            f"was taken before the ramp rather than across it"
        )
        assert t.max_dwell[i] == 500


@pytest.mark.parametrize("spec_id", [s.stem for s in SPECS])
def test_exactly_the_wait_exits_are_unbounded(spec_id):
    """The compiler's enumeration of what only the runtime can bound. If this ever
    grew a third member, the ceiling would be covering something nobody measured
    it against."""
    t = compile_spec(spec(spec_id)).table
    unbounded = {t.nodes[i].type.name for i in t.unbounded_nodes()}
    assert unbounded <= {"WAIT_EXIT"}, f"{spec_id}: also unbounded: {unbounded}"


def test_the_ceiling_clears_every_dwell_the_corpus_recorded():
    """30 s against a longest recorded sampling release of 21.1 s.

    The number is measured, and the margin is the design: this is a net for a box
    that has stopped, not a behavioural criterion.
    """
    assert limits().TG_WATCHDOG_CEILING_MS == 30000
    assert limits().TG_WATCHDOG_CEILING_MS > 21139  # the longest ever recorded
    assert limits().TG_WATCHDOG_GRACE_MS < limits().TG_WATCHDOG_CEILING_MS / 50


def test_the_fault_code_is_allocated_not_invented():
    v = vocabulary()
    assert v.code_of("WATCHDOG_FAULT") == 263
    assert all(
        not (lo <= 263 <= hi) for lo, hi in v.free_ranges
    ), "263 is still advertised as free, so it could be handed out twice"


# --------------------------------------------------------------------------- #
# The firmware
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    shutil.which("clang++") is None or not (BEHAVIORBOX / "BehaviorBox.h").is_file(),
    reason="needs clang++ and the reference BehaviorBox.h",
)
def test_it_fires_when_it_must_and_stays_silent_when_it_must_not(tmp_path):
    """The off-target battery: `extras/host_test/watchdog.cpp`.

    A scripted animal that takes its reward and never leaves the well — the exact
    shape of the hang the shipping firmware still has (docs/firmware-changes.md
    #0) — must fault rather than hang. 4000 healthy animals across the whole stage
    ramp must not fault at all. And safing must leave every actuator the table can
    drive LOW.
    """
    r = compile_spec(spec("two_afc"))
    (HOST_TEST / "grgl_table.h").write_text(emit(r.table), encoding="utf-8")
    binary = tmp_path / "watchdog"
    subprocess.run(
        ["clang++", "-std=c++17", "-Wall", "-I", str(HOST_TEST), "-I", str(LIB),
         "-I", str(BEHAVIORBOX), str(HOST_TEST / "watchdog.cpp"), "-o", str(binary)],
        check=True, capture_output=True,
    )
    out = subprocess.run([str(binary)], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
    assert "FAIL" not in out.stdout, out.stdout
    assert out.stdout.rstrip().endswith("PASS"), out.stdout
