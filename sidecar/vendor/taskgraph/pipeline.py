"""compile_spec() — the six passes, in order.

Each pass runs only when the ones before it are clean. That is not politeness: a
pass that ran on a document the previous pass rejected would be analysing garbage,
and its diagnostics would send the reader somewhere that is not the problem.

THE GATE IS STRUCTURAL. `CompileResult.table` is None whenever the bag holds an
ERROR, and the packer refuses a result with no table. There is no code path from a
failing spec to a byte the board could execute -- which is what "a malformed graph
must be impossible to upload" has to mean if it is to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import templates
from taskgraph.context import GraphContext, SpecContext, TableContext
from taskgraph.errors import DiagnosticBag
from taskgraph.graph import GraphDraft, GraphView
from taskgraph.lint import Pass, load_all_rules, run_pass
from taskgraph.loader import load_text
from taskgraph.lower import lower
from taskgraph.registries import channels, limits, vocabulary
from taskgraph.spec import TaskSpec
from taskgraph.table import StateTable

load_all_rules()


@dataclass
class CompileResult:
    bag: DiagnosticBag = field(default_factory=DiagnosticBag)
    spec: TaskSpec | None = None
    draft: GraphDraft | None = None
    view: GraphView | None = None
    table: StateTable | None = None

    @property
    def ok(self) -> bool:
        return self.table is not None and not self.bag.has_errors()

    def raise_if_failed(self) -> StateTable:
        self.bag.raise_if_errors(f"{self.spec.spec_id if self.spec else '?'} did not compile")
        assert self.table is not None
        return self.table


def compile_spec(path: str | Path, *, strict: bool = False) -> CompileResult:
    """Run the pipeline on a file. Never raises for a spec problem; read `result.bag`."""
    path = Path(path)
    return compile_text(
        path.read_text(), source_path=str(path), spec_id=path.stem, strict=strict
    )


def compile_text(
    text: str,
    *,
    source_path: str | None = None,
    spec_id: str | None = None,
    strict: bool = False,
) -> CompileResult:
    """Run the pipeline on an in-memory document.

    This is the entry point a GUI editor calls: it compiles the exact string the
    editor is about to save, so nothing the LOAD pass checks is skipped.
    """
    result = CompileResult()
    bag = result.bag

    # -- P0: load, parse rules, schema ------------------------------------ #
    spec = load_text(text, bag, source_path=source_path, spec_id=spec_id)
    if spec is None:
        return _finish(result, strict)
    result.spec = spec

    ctx = SpecContext(spec=spec, vocab=vocabulary(), channels=channels(), limits=limits())

    # -- P1: resolution --------------------------------------------------- #
    bag.extend(run_pass(Pass.BIND, ctx))

    # -- P2: template agreement ------------------------------------------- #
    bag.extend(run_pass(Pass.TEMPLATE, ctx))
    if bag.has_errors():
        return _finish(result, strict)

    # -- P3: emit + lower -------------------------------------------------- #
    mod = templates.load(spec.topology.template, spec.topology.template_version)
    chans = ctx.channels
    engagement = chans.unique_of_kind("engagement")
    cue = chans.unique_of_kind("cue")
    vac = chans.unique_of_kind("vacuum")
    if engagement is None or cue is None or vac is None:
        # TG225 already reported the engagement case; bail rather than crash.
        return _finish(result, strict)

    draft = mod.emit(spec, engagement.name, cue.name, vac.name)
    result.draft = draft
    result.view = GraphView.from_draft(draft)

    table = lower(spec, draft, ctx.vocab, chans, bag)
    bag.extend(run_pass(Pass.EMIT, ctx))

    # -- P4: graph structure ------------------------------------------------ #
    bag.extend(run_pass(Pass.GRAPH, GraphContext(graph=result.view, spec_id=spec.spec_id)))

    # -- P5: capacity and wire invariants ----------------------------------- #
    bag.extend(run_pass(Pass.PACK, TableContext(table=table, limits=ctx.limits, spec_id=spec.spec_id)))

    table.template_hash = templates.source_hash(
        spec.topology.template, spec.topology.template_version
    )

    # The table is published ONLY if nothing failed. This is the gate.
    if not bag.has_errors():
        result.table = table
    return _finish(result, strict)


def _finish(result: CompileResult, strict: bool) -> CompileResult:
    if strict:
        result.bag.promote_warnings()
        if result.bag.has_errors():
            result.table = None
    return result
