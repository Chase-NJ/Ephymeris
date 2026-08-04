"""Properties of the RULE SET itself, not of any rule's implementation.

The roadmap's exit criterion is "linter rejects a battery of deliberately broken
specs." Asserting that mechanically means asserting it about the registry: every
rule that exists must have something that makes it fire. A rule with no negative
test has never been seen to work and is indistinguishable from a misspelled one.

This measures coverage of RULES, not of lines. A line-coverage number would be
satisfied by a rule module that is imported and never triggered.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ephymeris_sidecar.taskgraph.errors import Severity
from ephymeris_sidecar.taskgraph.lint import REGISTRY, Pass, load_all_rules

from tests.compiler.tgpaths import (  # noqa: E402
    AS_BUILT, BEHAVIORBOX, FIRMWARE, FIRMWARE_LIB, HOST_TEST, REPO_ROOT,
    SCHEMA_DIR, TESTS_DIR, all_specs, spec,
)
BROKEN_DIR = TESTS_DIR / "broken"

load_all_rules()

CODE_RE = re.compile(r"^TG\d{3}$")


def test_rules_are_registered():
    """A registry that silently ends up empty would make every other test here
    vacuously pass."""
    assert len(REGISTRY) > 0, "no rules registered -- did load_all_rules() lose a module?"


@pytest.mark.parametrize("r", REGISTRY.all(), ids=lambda r: r.code)
def test_code_is_well_formed(r):
    assert CODE_RE.match(r.code), f"{r.code} must look like TG###"


@pytest.mark.parametrize("r", REGISTRY.all(), ids=lambda r: r.code)
def test_has_actionable_help(r):
    """Every diagnostic must tell someone what to do about it.

    Six months from now the reader was not in the room when the rule was written.
    Help text is the whole difference between a diagnostic and a puzzle."""
    assert r.help and r.help.strip(), f"{r.code} has no help text"
    assert len(r.help) > 20, f"{r.code} help is too terse to act on: {r.help!r}"


def test_codes_are_unique():
    """Codes are append-only, exactly like the strobe vocabulary. People paste
    them into issues; a code that changes meaning turns that history into
    misinformation. The registry enforces this at import time too -- this is the
    belt to that's braces."""
    codes = [r.code for r in REGISTRY.all()]
    assert len(codes) == len(set(codes))


@pytest.mark.parametrize("r", REGISTRY.all(), ids=lambda r: r.code)
def test_code_band_matches_pass(r):
    """A rule filed in the wrong band runs at the wrong time -- typically meaning
    it reads a field that has not been resolved yet."""
    band = {
        Pass.LOAD: "1",
        Pass.BIND: "2",
        Pass.TEMPLATE: "3",
        Pass.EMIT: "2",
        Pass.GRAPH: "4",
        Pass.PACK: "5",
    }[r.pass_]
    # 9xx is the pass-agnostic informational band; see the registry's note.
    if r.code[2] == "9":
        assert r.severity is Severity.INFO, f"{r.code} is 9xx but not INFO"
        return
    assert r.code[2] == band, f"{r.code} runs in {r.pass_.name} but sits in the {r.code[2]}xx band"


def _fixture_codes() -> set[str]:
    """Codes claimed by a broken-spec fixture.

    Fixtures are named for the rule they provoke: tests/broken/TG403_gap_loops_back.yaml.
    Encoding the code in the filename means the mapping needs no registry of its
    own to drift out of sync with.
    """
    if not BROKEN_DIR.is_dir():
        return set()
    found = set()
    for p in BROKEN_DIR.glob("*.yaml"):
        m = re.match(r"^(TG\d{3})[a-z]?_", p.name)
        if m:
            found.add(m.group(1))
    return found


def _direct_test_codes() -> set[str]:
    """Codes exercised by a test that calls the rule directly.

    Some rules cannot be reached from a YAML file at all:

      * graph rules fire on TEMPLATE bugs, not spec bugs -- which is exactly why
        they take a GraphView rather than a TaskSpec;
      * a few spec rules are shadowed by the JSON Schema, which rejects the
        document before binding runs, so the rule never sees it. TG204 is the
        clear case: the schema caps `ms` at 65535, so an over-range duration
        never reaches the linter. The rule is still wanted -- it owns the
        semantic, and relying on the schema for a safety-critical bound is how
        that bound quietly disappears when the schema is relaxed -- but its
        negative test has to construct the spec in memory;
      * the wiring rules (TG226-229) fire on a DIFFERENT DOCUMENT. The spec is
        fine and the rig is wrong, and a spec cannot express a duplicate pin
        because a spec never mentions a pin. Their cases are in
        tests/compiler/test_rules_wiring.py.

    Any tests/test_rules_*.py counts.
    """
    found: set[str] = set()
    for f in TESTS_DIR.glob("test_rules_*.py"):
        found |= set(re.findall(r"TG\d{3}", f.read_text(encoding="utf-8")))
    return found


@pytest.mark.parametrize("r", REGISTRY.all(), ids=lambda r: r.code)
def test_every_rule_has_a_negative_test(r):
    """THE exit criterion, mechanised.

    Either a broken YAML fixture or a hand-built GraphView must provoke this rule.
    """
    covered = _fixture_codes() | _direct_test_codes()
    assert r.code in covered, (
        f"{r.code} ({r.name}) has nothing that makes it fire. Add "
        f"tests/broken/{r.code}_<what>.yaml, or a case in a tests/test_rules_*.py "
        f"file if it is unreachable from a YAML document."
    )


def test_no_orphan_fixtures():
    """A fixture naming a code that no longer exists is a test that silently
    stopped testing anything."""
    orphans = _fixture_codes() - REGISTRY.codes()
    assert not orphans, f"fixtures name unregistered rules: {sorted(orphans)}"
