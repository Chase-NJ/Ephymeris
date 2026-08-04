"""The generated skeletons are the same machines the hand-authored specs were.

THIS TEST HAS A WINDOW AND THEN IT IS GONE. It compares each paradigm's
generated skeleton against the hand-authored spec it replaces, and it can only
do that while both exist. Once the five specs are deleted, the comparison has no
right-hand side and this file goes with them.

It is worth writing for the one window it has, because it is the strongest
evidence available that the generator produces the RIGHT machine rather than
merely a machine that compiles. Goldens over generated skeletons cannot make
this claim: a generator bug changes the skeleton, which changes the golden, and
re-blessing the golden hides it. Goldens over hand-authored specs can, and these
specs were validated against 1.5 million recorded strobe events.

What is compared is STRUCTURE -- node primitives, watch masks, edge offsets,
strobes, the watched pins and the full edge list -- not values. Timing numbers legitimately
differ (shaping starts at a 10 ms hold; the skeleton starts at the full-task
value), and so do ids and labels. The claim is "the same graph", not "the same
document".
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.specs import compiler
from ephymeris_sidecar.taskgraph import paradigms
from ephymeris_sidecar.taskgraph.pipeline import compile_spec
from tests.compiler.tgpaths import SPEC_DIR, spec

#: paradigm id -> the hand-authored spec it was derived from.
PAIRS = [
    ("two_afc", "grgl_2odor"),
    ("go_nogo", "gonogo"),
    ("seq2_retention", "seq2_retention"),
    ("shaping", "shaping_gr"),
]

pytestmark = pytest.mark.skipif(
    not SPEC_DIR.is_dir() or not any(SPEC_DIR.glob("*.yaml")),
    reason="the hand-authored specs are gone; this comparison has no right-hand side",
)


def structure(table):
    """Everything about a table that is the MACHINE rather than the numbers."""
    return {
        "nodes": [
            (n.type, n.watch_mask, n.edge_idx, n.strobe)
            for n in table.nodes
        ],
        "edges": [
            (e.trigger, e.guard, e.target, e.effect) for e in table.edges
        ],
        "watch_pins": list(table.watch_pins),
    }


@pytest.mark.parametrize("paradigm_id,spec_id", PAIRS, ids=lambda v: v)
def test_the_skeleton_is_the_same_machine(paradigm_id: str, spec_id: str):
    p = paradigms.get(paradigm_id)
    generated = compiler.compile(
        paradigms.to_yaml(paradigms.skeleton(p, spec_id=paradigm_id)),
        spec_id=paradigm_id,
    )
    assert generated.ok, generated.bag.render()

    authored = compile_spec(spec(spec_id))
    assert authored.ok, authored.bag.render()

    got, want = structure(generated.table), structure(authored.table)
    assert len(got["nodes"]) == len(want["nodes"]), (
        f"{paradigm_id} emits {len(got['nodes'])} states, {spec_id} has "
        f"{len(want['nodes'])}"
    )
    assert got == want, (
        f"the {paradigm_id} skeleton is not the machine {spec_id} compiles to. "
        "Timing values may differ; primitives, watch masks, strobes and edges "
        "may not."
    )


def test_the_unrewarded_variant_drops_exactly_the_delivery_states():
    """`rewarded: false` is the one layer-2 field that changes the graph.

    Pinned as a COUNT and a kind, not as a golden, so it keeps meaning something
    after the authored specs are gone.
    """
    rewarded = compiler.compile(
        paradigms.to_yaml(paradigms.skeleton(paradigms.get("two_afc"), spec_id="a")),
        spec_id="a",
    )
    plain = compiler.compile(
        paradigms.to_yaml(
            paradigms.skeleton(paradigms.get("two_afc_unrewarded"), spec_id="b")
        ),
        spec_id="b",
    )
    assert rewarded.ok and plain.ok
    dropped = len(rewarded.table.nodes) - len(plain.table.nodes)
    assert dropped == 2, (
        "expected exactly two states to disappear -- the reward PULSE and the "
        f"consumption WAIT_EXIT -- but {dropped} did"
    )
    kinds = {n.type for n in rewarded.table.nodes} - {n.type for n in plain.table.nodes}
    assert kinds == {4}, f"expected the PULSE primitive to be what vanished, got {kinds}"
