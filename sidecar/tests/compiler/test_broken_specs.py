"""The battery: every rule must actually reject something.

"A malformed graph must be impossible to upload" is only true if each rule has
been seen to fire. A rule with no negative test is indistinguishable from a
misspelled one -- it contributes nothing and looks like it contributes.

Each fixture in tests/broken/ is `_base.yaml` plus ONE deliberate defect, so the
defect is the only thing a reader has to look at. The fixture declares the code it
should provoke (`_expect`) and why it matters (`_why`); the filename repeats the
code so tests/test_rule_registry.py can check coverage without a second registry
to drift out of sync.

Fixture keys:
    _expect   the rule code this must provoke
    _why      prose for the reader; never asserted on
    _patch    dotted-path -> value, applied over the base
    _delete   dotted paths to remove
    _append   dotted path to a list -> item to append
    _also     codes this defect is EXPECTED to trip as well, declared explicitly
    _raw      a complete document, for defects that cannot survive being patched
              (a file that will not parse has no paths to patch)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from ephymeris_sidecar.taskgraph.context import SpecContext
from ephymeris_sidecar.taskgraph.errors import DiagnosticBag, Severity
from ephymeris_sidecar.taskgraph.lint import Pass, load_all_rules, run_pass
from ephymeris_sidecar.taskgraph.loader import bind, compute_spec_hash
from ephymeris_sidecar.taskgraph.pipeline import compile_text

load_all_rules()

BROKEN = Path(__file__).resolve().parent / "broken"
BASE = BROKEN / "_base.yaml"
FIXTURES = sorted(p for p in BROKEN.glob("TG*.yaml"))


# --------------------------------------------------------------------------- #
# Patch application
# --------------------------------------------------------------------------- #


def _split(path: str) -> list[Any]:
    """`timing[4].ms` -> ['timing', 4, 'ms']"""
    parts: list[Any] = []
    for chunk in path.split("."):
        while "[" in chunk:
            head, _, rest = chunk.partition("[")
            idx, _, chunk = rest.partition("]")
            if head:
                parts.append(head)
            parts.append(int(idx))
        if chunk:
            parts.append(chunk)
    return parts


def _set(doc: Any, path: str, value: Any) -> None:
    parts = _split(path)
    node = doc
    for p in parts[:-1]:
        node = node[p]
    node[parts[-1]] = value


def _delete(doc: Any, path: str) -> None:
    parts = _split(path)
    node = doc
    for p in parts[:-1]:
        node = node[p]
    last = parts[-1]
    if isinstance(node, list):
        node.pop(last)
    else:
        node.pop(last, None)


def build_document(fixture: dict) -> str:
    """Render the fixture to YAML TEXT, not to a dict.

    Text, because a fixture whose whole point is that it will not parse cannot be
    round-tripped through safe_load first -- TG100 would blow up in the harness
    rather than in the loader under test.
    """
    if "_raw" in fixture:
        return fixture["_raw"]
    doc = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    doc["spec_id"] = "fixture_" + fixture["_expect"].lower()
    for path in fixture.get("_delete", ()):
        _delete(doc, path)
    for path, value in (fixture.get("_append") or {}).items():
        node = doc
        for part in _split(path):
            node = node[part]
        node.append(value)
    for path, value in (fixture.get("_patch") or {}).items():
        _set(doc, path, value)
    return yaml.safe_dump(doc, sort_keys=False)


def diagnose(text: str) -> DiagnosticBag:
    """Run the document through every pass a broken document can reach.

    Passes stop at the first that errors, exactly as the real pipeline does: a
    document that fails schema validation must not then be bound, because binding
    indexes required keys directly and would raise where a diagnostic belongs.
    """
    return compile_text(text).bag


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_base_is_valid():
    """If the base ever develops its own errors, every fixture starts passing for
    the wrong reason -- the expected code would fire, but so would noise nobody
    looked at."""
    raw = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    spec = bind(raw, source_path=str(BASE), spec_hash=compute_spec_hash(raw))
    bag = DiagnosticBag()
    bag.extend(run_pass(Pass.BIND, SpecContext(spec=spec)))
    assert not bag.has_errors(), f"tests/broken/_base.yaml is not valid:\n{bag.render()}"


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_provokes_its_rule(path: Path):
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
    expect = fixture["_expect"]

    assert path.name.split("_")[0].rstrip("b") == expect or path.name.startswith(expect + "_"), (
        f"{path.name} declares _expect: {expect}; the filename must start with it so "
        f"the registry coverage check can find it"
    )
    assert fixture.get("_why", "").strip(), f"{path.name} has no _why -- say what the defect means"

    bag = diagnose(build_document(fixture))
    assert expect in bag.codes(), (
        f"{path.name} did not provoke {expect}.\n"
        f"got: {sorted(bag.codes()) or 'nothing at all'}\n{bag.render()}"
    )


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_is_a_single_defect(path: Path):
    """One fixture, one rule.

    A fixture that trips three rules is not a test of any of them: it passes even
    if two of the three regress. The exception is a document that cannot be loaded
    at all (_raw), where schema validation legitimately reports several things
    about the same malformed file.
    """
    fixture = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "_raw" in fixture:
        return
    expect = fixture["_expect"]
    bag = diagnose(build_document(fixture))
    # `_also` declares an overlap rather than hiding it -- several defects are
    # legitimately caught by both the schema and a rule, and that redundancy is
    # wanted. TG231 rides along on the base's deliberate null strobe.
    allowed = {expect, "TG231", *fixture.get("_also", ())}
    # INFO is not a defect. TG901 enumerates watchdog-only states on every compile
    # of every spec, so counting it here would make one fixture per rule impossible.
    seen = {d.code for d in bag if d.severity is not Severity.INFO}
    unexpected = seen - allowed
    assert not unexpected, (
        f"{path.name} provokes {sorted(unexpected)} as well as {expect}.\n"
        f"Narrow the defect so the fixture tests one rule.\n{bag.render()}"
    )
