"""The compiler must import from the package, exactly once, and never raise.

Three claims, and the first two are the ones that fail silently:

1. `taskgraph` is reached ONLY as `ephymeris_sidecar.taskgraph`. A bare top-level
   `taskgraph` module can now only exist if someone re-adds a `sys.path` insert --
   which is precisely the arrangement the fold removed, and precisely the one that
   looks perfect on a machine with a Task-Graph checkout and breaks in the frozen
   build. Asserting its ABSENCE is the inverted form of the old vendor test.

2. There is exactly ONE module object per module. `pipeline.py` calls
   `load_all_rules()` at module scope and `registries` is `lru_cache`d, so a second
   copy means two rule registries and two strobe vocabularies that agree until they
   don't. A dotted import cannot produce a second copy; a `sys.path` one can.

3. `compile()` never raises for a spec problem. It runs on every keystroke; an
   exception there is an error dialog while someone is mid-word.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from ephymeris_sidecar.specs import compiler

PACKAGE = Path(__file__).resolve().parent.parent / "ephymeris_sidecar" / "taskgraph"

pytestmark = pytest.mark.skipif(
    not compiler.available()[0],
    reason=f"task-spec compiler unavailable: {compiler.available()[1]}",
)


def test_the_compiler_is_available():
    ok, why = compiler.available()
    assert ok, why


def test_self_check_proves_a_real_compile_not_just_an_import():
    """`available()` says the import worked; `self_check()` says the thing works.

    The gap between those is not theoretical — it is what a packaged build gets
    wrong. The compiler ships as PyInstaller data files, so its own dependencies
    have to be named by hand in the freeze; naming `yaml` and forgetting
    `jsonschema`'s metaschema data gives an import that succeeds and a compile that
    fails on every document. `available()` reported ready for exactly that build.
    """
    ok, why = compiler.self_check()
    assert ok, why
    # The probe is GENERATED now, so a green self_check also proves the paradigm
    # registry, the composed pinout and the vocabulary are all present -- which
    # a shipped example could never prove about a freeze that dropped them.
    from ephymeris_sidecar.taskgraph import paradigms

    assert paradigms.load_all(), "no paradigms shipped"


def test_the_compiler_resolves_inside_the_package():
    from ephymeris_sidecar.taskgraph import pipeline, registries, templates

    for module in (pipeline, registries, templates):
        assert Path(module.__file__).resolve().is_relative_to(PACKAGE), (
            f"{module.__name__} imported from {module.__file__}, not from {PACKAGE}."
        )


def test_no_bare_taskgraph_module_exists():
    """The inverted vendor guard.

    While the compiler was vendored, `taskgraph` was a TOP-LEVEL module put on
    `sys.path` by hand, and the danger was a Task-Graph checkout shadowing it.
    There is no checkout and no `sys.path` insert now, so a bare `taskgraph` can
    only reappear if someone reintroduces one -- which would resurrect the
    two-module-objects hazard (two rule registries, two vocabularies) that the
    fold made structurally impossible. Absence is the assertion.
    """
    bare = [n for n in sys.modules if n == "taskgraph" or n.startswith("taskgraph.")]
    assert not bare, (
        f"a top-level `taskgraph` module is importable: {bare}. The compiler is "
        "`ephymeris_sidecar.taskgraph`; a bare one means a sys.path insert came "
        "back, and with it two copies of the rule registry."
    )
    assert "templates" not in sys.modules, (
        "a top-level `templates` module is importable -- same cause, same risk."
    )


def _skeletons():
    from ephymeris_sidecar.taskgraph import paradigms

    return [
        (p.id, paradigms.to_yaml(paradigms.skeleton(p, spec_id=p.id)))
        for p in paradigms.load_all()
    ]


def test_every_paradigm_skeleton_compiles_clean():
    """What ships is the ability to MAKE a task, so that is what is checked.

    The listing-matches-the-checked-in-artifact test that used to live beside
    this one moved to the compiler suite's paradigm goldens, where the artifact
    now lives.
    """
    for spec_id, text in _skeletons():
        result = compiler.compile(text, spec_id=spec_id)
        assert result.ok, f"{spec_id}: {result.bag.render()}"
        assert result.table is not None
        blob, crc = compiler.table_bytes(result)
        assert blob and crc


def test_compile_never_raises_on_a_malformed_document():
    for text in ("", "not a mapping", "spec_id: [1,2]", "{{{", "spec_version: 1\ntiming: 3"):
        result = compiler.compile(text, spec_id="scratch")
        assert result.table is None
        assert result.bag.has_errors() or not result.ok


def test_capabilities_answers_a_half_built_topology():
    """The form calls this before a spec is complete, on every knob change."""
    caps = compiler.capabilities_for({"n_sampling_stages": 0, "commit_hold": False})
    assert "hold_break" not in caps.outcome_classes, (
        "with no commitment hold and no sampling stage there is no hold to break"
    )
    caps = compiler.capabilities_for({"n_sampling_stages": 2, "response_mode": "go_nogo"})
    assert "false_alarm" in caps.outcome_classes
    assert "wrong" not in caps.outcome_classes


def test_capabilities_agrees_with_what_each_skeleton_declares():
    """The gate the form relies on must match the compiler's own view."""
    for spec_id, text in _skeletons():
        raw = yaml.safe_load(text)
        caps = compiler.capabilities_for(raw["topology"])
        declared = set(raw["contingency"]["outcome_map"])
        assert declared == set(caps.outcome_classes), spec_id
        assert set(caps.required_timing) <= {t["id"] for t in raw["timing"]}, spec_id


def test_registries_carry_everything_a_form_needs():
    reg = compiler.registries()
    assert set(reg) == {"schema", "overlay", "strobes", "channels", "limits", "templates"}
    assert reg["overlay"]["fields"], "the presentation overlay is empty"
    assert any(t["name"] == "four_epoch" for t in reg["templates"])
    assert all(t["sourceHash"] for t in reg["templates"])


# --------------------------------------------------------------------------- #
# An answer re-derives the fields it invalidates (paradigms._reconcile)
# --------------------------------------------------------------------------- #

from ephymeris_sidecar.taskgraph import paradigms  # noqa: E402


def test_an_answered_emitter_carries_its_onset_code():
    """The gate-B failure, pinned: `emitter` and `on_code` are one fact.

    Answering "which odor line" and leaving the code alone produces a document
    claiming line 3 announces itself as ODOR_1_ON. Both halves are individually
    legal, so it compiles — and the way it surfaces is real firmware disagreeing
    about which odor was presented.
    """
    p = paradigms.get("two_afc")
    doc = paradigms.skeleton(
        p, spec_id="probe", answers={"stim_a_emitter": "odor_line_3"}
    )
    first = doc["contingency"]["stimuli"][0]
    assert (first["emitter"], first["on_code"]) == ("odor_line_3", "ODOR_3_ON")


def test_an_answered_target_renames_the_trial_type_it_describes():
    """Shaping-L came out of the wizard carrying `tt_odor1_right_well`
    targeting the LEFT well. An id is only a label, so it compiled — and a
    listing that names one side while scoring the other is exactly the kind of
    thing nobody catches at the bench."""
    p = paradigms.get("shaping")
    left = paradigms.skeleton(p, spec_id="probe", answers={"rewarded_arm": "left_well"})

    weighted = [t for t in left["contingency"]["trial_types"] if t.get("weight") == 1]
    assert len(weighted) == 1
    assert weighted[0]["target"] == "left_well"
    assert weighted[0]["id"] == "tt_odor1_left_well"

    # The unweighted rows keep the names they were generated with — only the
    # row whose target the answer moved is re-derived.
    others = {t["id"]: t["target"] for t in left["contingency"]["trial_types"][1:]}
    assert all(tid.endswith(target) for tid, target in others.items())


def test_shaping_left_and_right_are_the_same_machine():
    """The paradigm/spec split, stated as a test.

    Shaping-R and Shaping-L differ by ONE answer, so they must compile to the
    same nodes, the same edges and the same timing — differing only in which
    trial type carries the weight. If this ever fails, widening a shaping task
    to both wells has become a reshape rather than a policy edit, and the
    animal's history splits at that boundary in Analytics.
    """
    p = paradigms.get("shaping")
    tables = {}
    for side in ("right_well", "left_well"):
        text = paradigms.to_yaml(
            paradigms.skeleton(p, spec_id=f"probe_{side}", answers={"rewarded_arm": side})
        )
        result = compiler.compile(text, spec_id=f"probe_{side}")
        assert result.ok
        tables[side] = result.table

    r, l = tables["right_well"], tables["left_well"]
    prims = lambda t: [(n.type, n.watch_mask, n.edge_idx, n.strobe) for n in t.nodes]
    edges = lambda t: [(e.trigger, e.guard, e.target, e.effect) for e in t.edges]

    assert prims(r) == prims(l)
    assert edges(r) == edges(l)
    assert list(r.timing) == list(l.timing)
    assert [(p_.channel, p_.reward_line) for p_ in r.ports] == [
        (p_.channel, p_.reward_line) for p_ in l.ports
    ]
    # ...and the one thing that does differ.
    assert [(t.target, t.weight) for t in r.trial_types] != [
        (t.target, t.weight) for t in l.trial_types
    ]
