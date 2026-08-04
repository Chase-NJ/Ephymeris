"""Diagnostics — the compiler's only way of reporting anything.

Nothing in the pipeline raises an ad-hoc exception for a spec problem. Every rule
appends a `Diagnostic` to a bag, the bag is checked at pass boundaries, and
`pack()` refuses to run while the bag holds an ERROR. That structure is what makes
"a malformed graph is impossible to upload" a property of the code rather than a
convention someone has to remember.

RULE CODES ARE APPEND-ONLY, exactly like the strobe vocabulary. A code is never
renumbered and never reused for a different rule. People will paste `TG403` into
issues and commit messages, and a code that silently changes meaning between
releases turns that history into misinformation.

Codes are banded by the pass that can first detect them:

    TG1xx  parse / schema
    TG2xx  resolution: timing ids, @bindings, strobes, ports, channels
    TG3xx  template and topology agreement
    TG4xx  graph structure
    TG5xx  capacity, packing, wire invariants
    TG9xx  informational
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field


class Severity(enum.IntEnum):
    """Three levels, deliberately.

    A fourth level is always tempting and always makes the set less meaningful:
    the moment there are two flavours of "probably fine" nobody learns which one
    to care about.

    INFO never reaches the console. It exists for facts the listing should carry
    -- the unbounded-dwell node list, the worst-case trial duration -- which are
    genuinely useful to read and genuinely useless to be told about on every
    compile. A diagnostic that always fires trains people to skip diagnostics,
    which costs you the one that matters.
    """

    INFO = 10
    WARN = 20
    ERROR = 30

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Diagnostic:
    """One finding, at one place, with a way out.

    `help` and `decision` are what separate a diagnostic somebody can act on from
    a puzzle. Six months from now the person reading this will not have been in
    the room when the rule was written; `decision` points them at the entry in
    docs/decisions.md that says why the rule exists and what was rejected.
    """

    code: str
    severity: Severity
    message: str
    spec_id: str | None = None
    #: Either a YAML path (`contingency.outcome_map.omission.strobe`) or a node
    #: id (`S12`). Both are locations; which kind it is depends on the pass.
    location: str | None = None
    #: Multi-line supporting evidence: the offending cycle, the emitting template
    #: line, the topology knobs that selected the branch.
    detail: str | None = None
    #: Permanent, rule-level. What to do about it.
    help: str | None = None
    #: e.g. "D4" -- an entry in docs/decisions.md.
    decision: str | None = None

    def format(self, *, color: bool = False) -> str:
        head = f"{self.severity} {self.code}"
        where = self.spec_id or ""
        if self.location:
            where = f"{where}:{self.location}" if where else self.location
        if where:
            head = f"{head} {where}"
        out = [f"{head} — {self.message}"]
        if self.detail:
            out.extend(f"    {line}" for line in self.detail.rstrip().splitlines())
        if self.help:
            out.append(f"    help: {self.help}")
        if self.decision:
            out.append(f"    see:  docs/decisions.md {self.decision}")
        return "\n".join(out)

    def __str__(self) -> str:
        return self.format()


class CompileError(Exception):
    """Raised when a caller asks for output that the diagnostics forbid.

    Carries the bag rather than a string: a caller that wants to render all the
    errors can, and a caller that just wants to fail gets a sensible message.
    """

    def __init__(self, bag: DiagnosticBag, what: str = "compilation failed") -> None:
        self.bag = bag
        errors = bag.errors()
        detail = "\n".join(d.format() for d in errors)
        super().__init__(f"{what}: {len(errors)} error(s)\n{detail}")


@dataclass
class DiagnosticBag:
    """Accumulates diagnostics across every pass.

    Deliberately NOT fail-fast. A spec with six unresolved timing ids should
    report six, not the first one and then six more compiles. The pipeline stops
    at pass boundaries instead: a pass that would crash on bad input checks
    `has_errors()` before running.
    """

    items: list[Diagnostic] = field(default_factory=list)

    def add(self, diagnostic: Diagnostic) -> Diagnostic:
        self.items.append(diagnostic)
        return diagnostic

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self.items.extend(diagnostics)

    def errors(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.ERROR]

    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.WARN]

    def infos(self) -> list[Diagnostic]:
        return [d for d in self.items if d.severity is Severity.INFO]

    def has_errors(self) -> bool:
        return any(d.severity is Severity.ERROR for d in self.items)

    def codes(self) -> set[str]:
        return {d.code for d in self.items}

    def raise_if_errors(self, what: str = "compilation failed") -> None:
        if self.has_errors():
            raise CompileError(self, what)

    def promote_warnings(self) -> None:
        """`--strict`: treat every WARN as an ERROR.

        For CI. A warning baseline (specs/<id>.lint.txt) is what keeps day-to-day
        warnings honest; --strict is for the pipeline that must not merge one.
        """
        self.items = [
            Diagnostic(
                code=d.code,
                severity=Severity.ERROR if d.severity is Severity.WARN else d.severity,
                message=d.message,
                spec_id=d.spec_id,
                location=d.location,
                detail=d.detail,
                help=d.help,
                decision=d.decision,
            )
            for d in self.items
        ]

    def render(self, *, include_info: bool = False) -> str:
        """Console rendering. INFO is listing-only unless explicitly asked for."""
        shown = [
            d for d in self.items if include_info or d.severity is not Severity.INFO
        ]
        return "\n".join(d.format() for d in shown)

    def summary(self) -> str:
        e, w, i = len(self.errors()), len(self.warnings()), len(self.infos())
        return f"{e} error(s), {w} warning(s), {i} info"

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        # An empty bag is falsy; a bag with only INFO is still truthy, because it
        # has content. Use has_errors() for gating, never truthiness.
        return bool(self.items)
