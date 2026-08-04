"""Golden-file tests: all five specs compile, and their listings stay current.

The listings in specs/*.table.txt are the review surface. If the compiler's output
drifts from what is checked in, the artifact everyone reviews stops describing the
graph that actually ships -- so the drift has to fail a build, not merely be
noticed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.emit.canonical import to_dict, to_json
from ephymeris_sidecar.taskgraph.emit.listing import render, render_lint
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from ephymeris_sidecar.taskgraph.table import NO_TARGET

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, SPEC_DIR, all_specs, spec,
)
SPECS = all_specs()


@pytest.fixture(scope="module")
def compiled():
    return {p.stem: compile_spec(p) for p in SPECS}


def test_all_five_target_tasks_are_present():
    assert {p.stem for p in SPECS} == {
        "grgl_2odor", "shaping_gr", "shaping_gr_ez", "gonogo", "seq2_retention"
    }


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_compiles_without_errors(path, compiled):
    r = compiled[path.stem]
    assert r.ok, f"{path.stem} did not compile:\n{r.bag.render()}"


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_listing_golden_is_current(path, compiled):
    r = compiled[path.stem]
    golden = path.with_suffix(".table.txt")
    assert golden.exists(), f"missing golden {golden.name} -- run `taskgraph compile`"
    assert golden.read_text() == render(r.table, r.bag), (
        f"{golden.name} is stale. Run:\n  taskgraph compile specs/{path.name}\n"
        "and review the diff -- it shows exactly which states moved."
    )


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_lint_baseline_is_current(path, compiled):
    """The accepted warning set is explicit, versioned and reviewed.

    A new warning anywhere becomes a failing diff. That is the only warning
    discipline that survives a working lab -- the alternative is a slowly growing
    pile nobody reads.
    """
    r = compiled[path.stem]
    golden = path.with_suffix(".lint.txt")
    assert golden.exists(), f"missing {golden.name}"
    assert golden.read_text() == render_lint(r.bag, r.table.spec_id)


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_fits_the_measured_hardware_budget(path, compiled):
    """Against the limit measured on a real ATmega2560, not a guess."""
    from ephymeris_sidecar.taskgraph.registries import limits

    r, lim = compiled[path.stem], limits()
    t = r.table
    assert len(t.nodes) <= lim.TG_MAX_STATES
    assert len(t.edges) <= lim.TG_MAX_EDGES
    # 1440 bytes is what the sweep measured at the enforced limit; every real task
    # should be far below it. If one is not, the spike needs re-running.
    assert t.size_bytes() < 1440


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_canonical_json_is_deterministic(path, compiled):
    """Two renders of one table must be byte-identical.

    Phase 4's whole-table CRC is taken over this data. A hash that moves when
    nothing moved is worthless as provenance.
    """
    r = compiled[path.stem]
    assert to_json(r.table) == to_json(r.table)


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_every_node_has_a_dwell_verdict(path, compiled):
    """The Phase 4 handoff. Either a state has a static bound or it is explicitly
    listed as watchdog-only; there is no third answer, and a missing one would mean
    a state nothing is responsible for bounding."""
    r = compiled[path.stem]
    assert len(r.table.max_dwell) == len(r.table.nodes)


def test_ez_variant_is_a_pure_timing_delta_in_the_compiled_table(compiled):
    """THE layer-3 claim, verified against the COMPILED output rather than the spec.

    Two specs can look like a pure timing delta and still compile to different
    graphs if the template branches on something subtle. Comparing the tables is
    what actually proves the claim.
    """
    base = compiled["shaping_gr"].table
    ez = compiled["shaping_gr_ez"].table

    assert len(base.nodes) == len(ez.nodes)
    assert len(base.edges) == len(ez.edges)

    for a, b in zip(base.nodes, ez.nodes, strict=True):
        assert (a.type, a.dur_idx, a.strobe, a.watch_mask, a.edge_idx) == (
            b.type, b.dur_idx, b.strobe, b.watch_mask, b.edge_idx
        ), f"node {a.symbol} differs structurally between a task and its eased variant"

    for a, b in zip(base.edges, ez.edges, strict=True):
        assert (a.trigger, a.guard, a.target, a.effect) == (b.trigger, b.guard, b.target, b.effect)

    # ...and it must actually differ somewhere in layer 3, or it is not a variant.
    assert base.timing != ez.timing


def test_gonogo_inverts_timeout_in_the_compiled_graph(compiled):
    """The go/no-go inversion, verified on the emitted edges.

    On an n-alternative task the response window's TIMEOUT leads to an omission
    scored TRIAL_INCORRECT. On go/no-go the SAME trigger on the SAME node type
    leads to TRIAL_CORRECT. Nothing about the interpreter changes -- which is the
    entire claim of D9.
    """
    gng = compiled["gonogo"].table
    grgl = compiled["grgl_2odor"].table

    def timeout_target_label(table, node_symbol):
        i = next(k for k, n in enumerate(table.nodes) if n.symbol == node_symbol)
        end = table.nodes[i + 1].edge_idx if i + 1 < len(table.nodes) else len(table.edges)
        edge = next(e for e in table.edges[table.nodes[i].edge_idx : end]
                    if str(e.trigger) == "TIMEOUT")
        return table.nodes[edge.target].label

    assert timeout_target_label(gng, "resp_win") == "correct"
    assert timeout_target_label(grgl, "resp_win") == "omission"

    # A withhold trial has no correct port, and rewards nothing.
    assert all(r.target == NO_TARGET for r in gng.trial_types)
    assert all(r.reward_line == NO_TARGET for r in gng.trial_types)
    # No reward PULSE and no consumption WAIT_EXIT in the spine -- removed by the
    # ABSENCE of a reward binding, not by a suppressing flag.
    assert not any(n.symbol in ("reward", "consume") for n in gng.nodes)


def test_seq2_unrolls_the_sampling_chain(compiled):
    """n_sampling_stages: 2 is a loop bound, not a rewrite.

    The extra stage and its gap appear; the response and outcome bands do not move.
    That containment is the reason epochs are separate blocks.
    """
    seq2 = compiled["seq2_retention"].table
    grgl = compiled["grgl_2odor"].table

    symbols = [n.symbol for n in seq2.nodes]
    assert "sample_0" in symbols and "sample_1" in symbols and "gap_0" in symbols
    assert "retain" in symbols
    assert [n.symbol for n in grgl.nodes if n.symbol.startswith("sample_")] == ["sample_0"]

    # Per-stage holds are distinct timing indices, so a ramp can lengthen the
    # second stimulus without touching the first.
    s0 = next(n for n in seq2.nodes if n.symbol == "sample_0")
    s1 = next(n for n in seq2.nodes if n.symbol == "sample_1")
    assert s0.dur_idx != s1.dur_idx
    assert seq2.timing_ids[s0.dur_idx] == "t_sample_hold_0"
    assert seq2.timing_ids[s1.dur_idx] == "t_sample_hold_1"

    # The outcome band is byte-identical in shape to GRGL's.
    assert [n.type for n in seq2.nodes if n.band == 4] == [n.type for n in grgl.nodes if n.band == 4]


def test_omission_announces_itself(compiled):
    """Firmware conforms to the model, so an omission emits RESP_OMIT.

    It used to emit nothing, which meant an omission was inferable only from a
    ~20-second gap before END_INCORRECT_ITI -- and that terminal is reached by
    three different outcomes, so the class was recoverable only from the
    *preceding* strobe. All three are now distinguishable where they occur.
    """
    for name in ("grgl_2odor", "shaping_gr", "seq2_retention"):
        node = next(n for n in compiled[name].table.nodes if n.symbol == "out_omission")
        assert node.strobe_name == "RESP_OMIT", f"{name} should announce its omissions"
        assert node.strobe == 262


def test_as_built_fixture_keeps_the_silence():
    """The as-built graph must NOT be quietly modernised.

    It pins template v1 and reproduces what the boxes emit today, quirks included.
    It is what 1.5 million recorded events were validated against, and it is the
    Phase 3 baseline until firmware ships the changes in docs/firmware-changes.md.
    Updating it to match the model would silently discard that evidence.
    """
    from ephymeris_sidecar.taskgraph.table import NO_STROBE

    r = compile_spec(AS_BUILT)
    assert r.ok
    assert r.table.template_version == 1

    node = next(n for n in r.table.nodes if n.symbol == "out_omission")
    assert node.strobe == NO_STROBE and node.silent_by_design

    # ...and it keeps v1's inconsistent cue-off order, which is the other reason
    # it exists. On the abort path LIGHTS_OFF precedes its partner.
    syms = [n.symbol for n in r.table.nodes]
    assert "noeng_cue_off" in syms, "v1 puts the cue-off node before the reason"


def test_response_branch_node_exists_with_its_guard(compiled):
    """D3: the strobe is emitted BEFORE correctness is known, so it sits on a
    zero-duration branch node whose edges carry the guard."""
    grgl = compiled["grgl_2odor"].table
    i = next(k for k, n in enumerate(grgl.nodes) if n.symbol == "resp_branch")
    node = grgl.nodes[i]

    assert node.strobe_name == "@ports[$ch].enter_code"
    assert grgl.timing[node.dur_idx] == 0

    end = grgl.nodes[i + 1].edge_idx
    edges = grgl.edges[node.edge_idx : end]
    assert len(edges) == 2
    assert edges[0].guard_text == "ch == @target"
    # The unguarded default MUST be last -- resolution is first-match-wins.
    assert edges[1].guard_text == ""


def test_canonical_json_names_the_unbounded_nodes(compiled):
    """Phase 4 reads this to know what the watchdog is solely responsible for."""
    d = to_dict(compiled["grgl_2odor"].table)
    assert d["unbounded_nodes"]
    for i in d["unbounded_nodes"]:
        assert d["nodes"][i]["max_dwell_ms"] is None
        assert d["nodes"][i]["type"] == "WAIT_EXIT"
