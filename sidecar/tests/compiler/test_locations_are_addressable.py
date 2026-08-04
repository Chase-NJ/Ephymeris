"""Every diagnostic must land somewhere a reader will look.

A `Diagnostic.location` is the only thing that can put an error next to the field
that caused it. This test pins the four shapes the rules actually emit and asserts
each one is classifiable, so a new rule cannot invent a fifth spelling that a form
would silently drop on the floor.

That "silently" is the point. A diagnostic that matches no field and no section
does not error -- it just does not appear, and the operator sees a spec that will
not compile with nothing marked. This is the test that makes that impossible.

The five shapes, all confirmed against what the rules produce over the whole broken
corpus rather than read off the source:

    contingency.ports.left_well.enter_code   a field     -> inline on the field
    contingency.outcome_map.correct          a row       -> on that row's header
    timing / contingency.outcome_map         a section   -> on the section header
    S17                                      a node id   -> in the graph pane
    (root) / stage_schedule[at_trial=20]     neither     -> document-level panel

The row shape is the one that was missed on the first pass, and it is why this test
exists rather than a reading of the rule sources.
"""

from __future__ import annotations

import yaml

from ephymeris_sidecar.taskgraph.pipeline import compile_text
from ephymeris_sidecar.taskgraph.presentation import placement
from tests.compiler.test_broken_specs import FIXTURES, build_document
from tests.compiler.tgpaths import spec

VALID_KINDS = frozenset({"field", "row", "section", "node", "document"})


def _diagnostics():
    for path in FIXTURES:
        fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = compile_text(build_document(fixture), spec_id=path.stem)
        for diagnostic in result.bag:
            yield path.name, diagnostic


def test_every_diagnostic_location_is_addressable():
    orphans = [
        f"{name}: {d.code} location={d.location!r} -> {placement(d.location)[0]}"
        for name, d in _diagnostics()
        if placement(d.location)[0] not in VALID_KINDS
    ]
    assert not orphans, (
        "these diagnostics carry a location placement() cannot classify, so a form "
        "would show the error nowhere:\n  " + "\n  ".join(orphans)
    )


def test_most_diagnostics_reach_a_field_or_a_row():
    """`document` is never wrong, only unhelpful -- so watch how often it is used.

    Without this, a regression that collapsed every location to `(root)` would leave
    the test above green while destroying the feature it protects.
    """
    kinds = [placement(d.location)[0] for _, d in _diagnostics()]
    precise = sum(k in ("field", "row", "section") for k in kinds)
    assert precise / len(kinds) > 0.5, (
        f"only {precise}/{len(kinds)} diagnostics land on a field, row or section"
    )


def test_the_corpus_exercises_every_placement_kind():
    kinds = {placement(d.location)[0] for _, d in _diagnostics()}
    for expected in ("field", "row", "section", "node", "document"):
        assert expected in kinds, f"no fixture produces a {expected!r} placement; got {kinds}"


def test_compile_text_never_raises_on_a_broken_document():
    """The GUI calls compile_text on every keystroke. It must always return a bag."""
    for path in FIXTURES:
        fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
        result = compile_text(build_document(fixture), spec_id=path.stem)
        assert result.table is None or not result.bag.has_errors()


def test_a_schema_violation_inside_an_array_element_lands_on_its_field():
    """TG102's locations must use the same grammar as every hand-written rule.

    jsonschema reports an error path as a sequence of keys and integer indices;
    a naive dot-join renders `timing.5.ms` — a spelling nothing else emits and
    the overlay cannot key. The broken corpus never caught it because none of
    its schema-violation fixtures fail INSIDE an array element; this is the case
    that does (found by the Ephymeris service tests, fixed at the rule).
    """
    from pathlib import Path

    text = spec("go_nogo").read_text(encoding="utf-8")
    broken = text.replace("  ms: 2000\n  wire_key: NWP", "  ms: 2000000\n  wire_key: NWP")
    assert broken != text
    result = compile_text(broken, spec_id="gonogo")
    tg102 = [d for d in result.bag if d.code == "TG102"]
    assert tg102, result.bag.render()
    kinds = {placement(d.location) for d in tg102}
    assert ("field", "timing[].ms") in kinds, kinds
