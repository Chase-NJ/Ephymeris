"""The in-memory entry point, and its equivalence with the file one.

`compile_text` exists so a GUI can compile the exact string it is about to save.
The value of that is entirely in the equivalence: if compiling a document differs
from compiling the file that document becomes, then the editor validated something
other than what it wrote, and the operator's confidence is misplaced.

So `compile_spec` delegates to `compile_text` rather than sitting beside it, and
this file pins that they cannot come apart.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph import templates
from ephymeris_sidecar.taskgraph.emit.canonical import to_json
from ephymeris_sidecar.taskgraph.emit.listing import render
from ephymeris_sidecar.taskgraph.emit.pack import pack
from ephymeris_sidecar.taskgraph.pipeline import compile_spec, compile_text

from tests.compiler.tgpaths import all_specs  # noqa: E402

SPECS = all_specs()


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_compile_text_matches_compile_spec(path: Path):
    from_file = compile_spec(path)
    from_text = compile_text(path.read_text(encoding="utf-8"), source_path=str(path), spec_id=path.stem)

    assert from_file.ok and from_text.ok
    assert to_json(from_text.table) == to_json(from_file.table)
    assert pack(from_text.table) == pack(from_file.table)
    assert render(from_text.table, from_text.bag) == render(from_file.table, from_file.bag)


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_spec_hash_survives_a_yaml_round_trip(path: Path):
    """Saving a spec the editor did not change must not move its hash.

    `compute_spec_hash` covers the parsed document, not the file bytes, so
    reformatting -- which is what safe_dump does to every spec the editor touches --
    is invisible to provenance. A run recorded before an edit and one recorded after
    a no-op save must compare equal, or `spec_hash` means nothing.
    """
    import yaml

    original = compile_spec(path)
    round_tripped = compile_text(
        yaml.safe_dump(yaml.safe_load(path.read_text(encoding="utf-8")), sort_keys=False),
        spec_id=path.stem,
    )
    assert round_tripped.ok, round_tripped.bag.render()
    assert round_tripped.table.spec_hash == original.table.spec_hash


def test_compile_text_needs_no_filesystem():
    """The GUI holds an unsaved document; there is no path to give."""
    result = compile_text("not: a spec")
    assert result.table is None
    assert result.bag.has_errors()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("", id="empty"),
        pytest.param("   \n\n  ", id="whitespace"),
        pytest.param("# just a comment\n", id="comments-only"),
        pytest.param("null\n", id="explicit-null"),
        pytest.param("a plain string", id="scalar"),
        pytest.param("- one\n- two\n", id="sequence"),
        pytest.param("{{{", id="unparseable"),
    ],
)
def test_a_document_that_is_not_a_spec_yields_a_diagnostic_not_a_crash(text: str):
    """Every one of these is a state an editor passes through while typing.

    The empty case is the one that bit: safe_load("") is None with no parse error,
    and every LOAD rule guarded on isinstance(dict) and returned quietly, so the bag
    came back clean and binding crashed on None. It never surfaced from the CLI
    because nobody compiles an empty file -- an editor compiles one the moment a new
    spec is started.
    """
    result = compile_text(text, spec_id="scratch")
    assert result.table is None
    assert result.bag.has_errors(), f"{text!r} produced no diagnostic at all"
    assert "TG100" in result.bag.codes()


def test_available_lists_every_template_on_disk():
    listed = templates.available()
    assert ("four_epoch", 2) in listed
    assert listed == tuple(sorted(listed)), "available() must be deterministic"
    for name, version in listed:
        assert templates.load(name, version).VERSION == version


def test_unknown_template_names_the_available_ones():
    with pytest.raises(templates.TemplateNotFound, match="four_epoch v2"):
        templates.load("four_epoch", 99)
