"""The vendored compiler must import once, from the right place, and never raise.

Three separate claims, and the first two are the ones that fail silently:

1. `taskgraph` resolves out of `sidecar/vendor/`, not out of a Task-Graph checkout
   that happens to be on the developer's PYTHONPATH. Getting this wrong looks
   perfect on the machine that has both and breaks only in the packaged build.

2. There is exactly ONE `taskgraph` module object. `pipeline.py` calls
   `load_all_rules()` at module scope and `registries` is `lru_cache`d, so a second
   copy means two rule registries and two strobe vocabularies that agree until they
   don't.

3. `compile()` never raises for a spec problem. It runs on every keystroke; an
   exception there is an error dialog while someone is mid-word.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from ephymeris_sidecar.specs import compiler

VENDOR = Path(__file__).resolve().parent.parent / "vendor"
SPECS = sorted((VENDOR / "specs").glob("*.yaml"))

pytestmark = pytest.mark.skipif(
    not compiler.available()[0],
    reason=f"vendored compiler unavailable: {compiler.available()[1]}",
)


def test_the_compiler_is_available():
    ok, why = compiler.available()
    assert ok, why


def test_taskgraph_resolves_out_of_the_vendor_tree():
    import taskgraph
    import templates

    for module in (taskgraph, templates):
        assert Path(module.__file__).resolve().is_relative_to(VENDOR), (
            f"{module.__name__} imported from {module.__file__}, not from {VENDOR}. "
            "A Task-Graph checkout on PYTHONPATH will shadow the vendored copy on a "
            "dev machine and be absent in the packaged build."
        )


def test_there_is_exactly_one_copy_of_the_compiler():
    doubled = [
        name
        for name in sys.modules
        if name.startswith("ephymeris_sidecar.") and ".taskgraph" in name
    ]
    assert not doubled, (
        "the vendor tree was imported by a dotted path as well as through sys.path, "
        f"so these modules exist twice: {doubled}. See specs/_vendor.py."
    )


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_every_bundled_spec_compiles_clean(path: Path):
    result = compiler.compile(path.read_text(), spec_id=path.stem)
    assert result.ok, result.bag.render()
    assert result.table is not None
    blob, crc = compiler.table_bytes(result)
    assert blob and crc


@pytest.mark.parametrize("path", SPECS, ids=lambda p: p.stem)
def test_the_listing_matches_the_checked_in_artifact(path: Path):
    """The diff baseline must be the artifact Task-Graph reviews, byte for byte.

    A topology editor diffs against `specs/<id>.table.txt`. If the sidecar rendered
    a listing that differed from the committed one — different registry, different
    template — every diff would open with spurious hunks and the review artifact
    would stop meaning anything.
    """
    result = compiler.compile(path.read_text(), spec_id=path.stem)
    golden = path.with_suffix(".table.txt")
    assert golden.is_file(), f"{golden.name} is missing from the vendored specs"
    assert compiler.render_listing(result) == golden.read_text()


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


def test_capabilities_agrees_with_what_each_bundled_spec_declares():
    """The gate the form relies on must match the compiler's own view."""
    for path in SPECS:
        raw = yaml.safe_load(path.read_text())
        caps = compiler.capabilities_for(raw["topology"])
        declared = set(raw["contingency"]["outcome_map"])
        assert declared == set(caps.outcome_classes), path.stem
        assert set(caps.required_timing) <= {t["id"] for t in raw["timing"]}, path.stem


def test_registries_carry_everything_a_form_needs():
    reg = compiler.registries()
    assert set(reg) == {"schema", "overlay", "strobes", "channels", "limits", "templates"}
    assert reg["overlay"]["fields"], "the presentation overlay is empty"
    assert any(t["name"] == "four_epoch" for t in reg["templates"])
    assert all(t["sourceHash"] for t in reg["templates"])
