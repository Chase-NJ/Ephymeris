"""The rule registry.

The linter is the deliverable of Phase 1, not the compiler. The failure mode being
designed against is a box that hangs mid-session with an animal in it, and every
rule here is the only thing standing between a typo and that outcome.

Rules are registered by decorator into one ordered table keyed by code. That
central table is what lets tests assert properties of the RULE SET rather than of
the code that implements it:

  * every code is unique, and banded by the pass that can first detect it
  * every code carries non-empty help text
  * every registered code is exercised by at least one deliberately-broken fixture

The third is the roadmap's "linter rejects a battery of deliberately broken specs"
made mechanical. It measures coverage of *rules* rather than of lines, which is
the thing that actually matters here: a rule with no negative test is a rule
nobody has ever seen fire, and an unfired rule is indistinguishable from a
misspelled one.

A rule's `check` is a plain function taking a pass-specific context and yielding
Diagnostics. It never raises for a spec problem and never mutates its input.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from taskgraph.errors import Diagnostic, Severity


class Pass(enum.IntEnum):
    """Pipeline stage. Each rule runs at the earliest point it has enough
    information -- and, just as importantly, before any later pass could crash or
    silently compute a wrong index from the bad input."""

    LOAD = 0      # TG1xx  YAML + JSON Schema
    BIND = 1      # TG2xx  resolution against vocab / channels / timing
    TEMPLATE = 2  # TG3xx  template and topology agreement
    EMIT = 3      # TG2xx continued: @binding resolution, which needs the graph
    GRAPH = 4     # TG4xx  structure -- reachability, totality, termination
    PACK = 5      # TG5xx  capacity and wire invariants


#: Which code band belongs to which pass. Enforced by the registry at import
#: time, so a misfiled rule is a startup error rather than a silent oddity.
_BAND_FOR_PASS = {
    Pass.LOAD: "1",
    Pass.BIND: "2",
    Pass.TEMPLATE: "3",
    Pass.EMIT: "2",
    Pass.GRAPH: "4",
    Pass.PACK: "5",
}


@dataclass(frozen=True)
class Rule:
    code: str
    name: str
    severity: Severity
    pass_: Pass
    help: str
    check: Callable[..., Iterable[Diagnostic]]
    decision: str | None = None
    #: Set when a rule is genuinely unreachable from a YAML fixture -- graph rules
    #: fire on TEMPLATE bugs, so they are exercised by hand-built GraphViews in
    #: tests/test_rules_graph.py instead. The coverage test accepts either, but
    #: something must exercise every rule.
    fixture_kind: str = "spec"


class _Registry:
    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def register(
        self,
        code: str,
        *,
        name: str,
        severity: Severity,
        pass_: Pass,
        help: str,
        decision: str | None = None,
        fixture_kind: str = "spec",
    ) -> Callable[[Callable[..., Iterable[Diagnostic]]], Callable[..., Iterable[Diagnostic]]]:
        def wrap(fn: Callable[..., Iterable[Diagnostic]]):
            if code in self._rules:
                # Import-time, not test-time: a duplicate code means two rules
                # would report as one another, and the append-only guarantee is
                # broken the moment it ships.
                raise AssertionError(
                    f"duplicate rule code {code}: already registered as "
                    f"{self._rules[code].name}. Codes are append-only -- pick the "
                    f"next free number in the {_BAND_FOR_PASS[pass_]}xx band."
                )
            if not code.startswith("TG") or not code[2:].isdigit():
                raise AssertionError(f"rule code {code!r} must look like TG###")
            band = code[2]
            # 9xx is the informational band and is deliberately pass-agnostic: an
            # INFO finding is about the artifact, not about a stage of checking it,
            # and forcing TG901 into the 4xx band would imply it were a structural
            # error like its neighbours.
            if band != "9" and band != _BAND_FOR_PASS[pass_]:
                raise AssertionError(
                    f"rule {code} runs in pass {pass_.name}, which owns the "
                    f"{_BAND_FOR_PASS[pass_]}xx band, but its code is in {band}xx"
                )
            if band == "9" and severity is not Severity.INFO:
                raise AssertionError(
                    f"rule {code} is in the 9xx informational band but has severity "
                    f"{severity}. Use a pass band for anything that can fail a build."
                )
            if not help.strip():
                raise AssertionError(f"rule {code} has empty help text")
            self._rules[code] = Rule(
                code=code,
                name=name,
                severity=severity,
                pass_=pass_,
                help=help,
                check=fn,
                decision=decision,
                fixture_kind=fixture_kind,
            )
            return fn

        return wrap

    def all(self) -> list[Rule]:
        return sorted(self._rules.values(), key=lambda r: r.code)

    def for_pass(self, pass_: Pass) -> list[Rule]:
        return [r for r in self.all() if r.pass_ is pass_]

    def get(self, code: str) -> Rule:
        return self._rules[code]

    def codes(self) -> set[str]:
        return set(self._rules)

    def __iter__(self) -> Iterator[Rule]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._rules)


REGISTRY = _Registry()
rule = REGISTRY.register


def run_pass(pass_: Pass, context: object) -> list[Diagnostic]:
    """Run every rule registered for `pass_` against `context`.

    Rules receive the pass's context object and yield Diagnostics. Order within a
    pass is by code, so output is stable and diffable -- which matters because the
    per-spec lint baseline (specs/<id>.lint.txt) is checked into version control
    and reviewed as a diff.
    """
    out: list[Diagnostic] = []
    for r in REGISTRY.for_pass(pass_):
        out.extend(r.check(context))
    return out


def load_all_rules() -> None:
    """Import every rule module so the registry is populated.

    Called by the CLI and by tests. Explicit rather than implicit because a rule
    module that is never imported is a rule that never runs, and that failure is
    completely silent -- the compiler simply stops checking something.
    """
    from taskgraph.lint import (  # noqa: F401
        rules_capacity,
        rules_graph,
        rules_load,
        rules_spec,
        rules_topology,
    )


__all__ = ["Pass", "Rule", "REGISTRY", "rule", "run_pass", "load_all_rules"]
