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
SPECS = sorted((PACKAGE / "specs").glob("*.yaml"))

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
    assert compiler.bundled_specs_dir().is_dir()
    assert sorted(p.name for p in compiler.bundled_specs_dir().glob("*.yaml"))


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
