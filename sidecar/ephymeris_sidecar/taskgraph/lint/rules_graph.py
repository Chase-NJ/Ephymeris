"""TG4xx — graph structure. The heart of the linter.

The failure mode every rule here is designed against is a box that hangs
mid-session with an animal in it. Nothing downstream can recover from a graph with
a missing exit: the interpreter walks edges, finds none, and sits there.

THESE RULES SEE A GraphView AND NOTHING ELSE. No spec, no vocabulary, no channel
map. They fire on TEMPLATE bugs rather than spec bugs, so almost none of them are
reachable from a valid YAML file -- which means the only way to test them is to
hand-construct the broken graph. Handing them a TaskSpec would leave most of the
linter permanently untested.

Where the roadmap's one-line description of a check turns out to be insufficient,
the rule implements the stronger version and says why.
"""

from __future__ import annotations

from collections.abc import Iterator

from ephymeris_sidecar.taskgraph.context import GraphContext
from ephymeris_sidecar.taskgraph.errors import Diagnostic, Severity
from ephymeris_sidecar.taskgraph.graph import BOUNDED, TRIGGERS_FOR, GraphView, NodeType, Trigger
from ephymeris_sidecar.taskgraph.lint import Pass, rule


def _d(ctx: GraphContext, code: str, sev: Severity, node: int, msg: str, **kw) -> Diagnostic:
    return Diagnostic(
        code=code, severity=sev, spec_id=ctx.spec_id, location=f"S{node:02d}", message=msg, **kw
    )


def _trigger_list(triggers) -> str:
    return ", ".join(str(t) for t in sorted(triggers, key=lambda t: t.value))


# --------------------------------------------------------------------------- #
# Totality
# --------------------------------------------------------------------------- #


@rule(
    "TG401",
    name="incomplete-trigger-coverage",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Give the state an outgoing edge for every trigger its type can emit. A WAIT_ENTRY "
        "needs one ENTER edge PER WATCHED CHANNEL, plus a TIMEOUT."
    ),
)
def incomplete_trigger_coverage(ctx: GraphContext) -> Iterator[Diagnostic]:
    """A state that can emit a trigger it has no edge for.

    STRONGER THAN "has an outgoing edge for every trigger". ENTER is parameterized
    by channel: a response window watching [left_well, right_well] with a single
    ENTER edge satisfies the naive check and drops one port on the floor -- the
    animal pokes left, nothing matches, and the box waits out a window it can never
    exit correctly. The rule is a BIJECTION between watched channels and ENTER
    edges.
    """
    g = ctx.graph
    for i, ntype in enumerate(g.types):
        outs = g.out_edges(i)
        present = {e.trigger for e in outs}
        required = TRIGGERS_FOR[ntype]

        for trig in sorted(required - present, key=lambda t: t.value):
            yield _d(
                ctx, "TG401", Severity.ERROR, i,
                f"{g.label(i)} can emit {trig} but has no edge for it",
                detail=f"a {ntype} state must handle: {_trigger_list(required)}",
            )

        if ntype is NodeType.WAIT_ENTRY:
            watched = set(g.watch_masks[i])
            entered = {e.channel for e in outs if e.trigger is Trigger.ENTER and e.channel}
            for ch in sorted(watched - entered):
                yield _d(
                    ctx, "TG401", Severity.ERROR, i,
                    f"{g.label(i)} watches {ch!r} but has no ENTER edge for it",
                    detail=(
                        "ENTER is per-channel. Without an edge for this channel the state\n"
                        "never reacts to it, and the trial waits out a window it cannot exit."
                    ),
                )
            for ch in sorted(entered - watched):
                yield _d(
                    ctx, "TG401", Severity.ERROR, i,
                    f"{g.label(i)} has an ENTER edge for {ch!r}, which it does not watch",
                    detail="The edge can never fire, because the channel is never polled.",
                )


@rule(
    "TG404",
    name="dead-edge",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Remove the edge, or change the state's type. An edge whose trigger the state "
        "cannot emit never fires."
    ),
)
def dead_edge(ctx: GraphContext) -> Iterator[Diagnostic]:
    """An edge for a trigger this node type cannot produce.

    A WAIT_EXIT with a TIMEOUT edge, or a PULSE with a BROKEN edge. The graph LOOKS
    total -- every trigger has an edge -- while the path that edge was meant to
    provide is effectively absent. That is worse than an obviously missing edge,
    because it reads as handled.
    """
    g = ctx.graph
    for i, ntype in enumerate(g.types):
        allowed = TRIGGERS_FOR[ntype]
        for e in g.out_edges(i):
            if e.trigger not in allowed:
                yield _d(
                    ctx, "TG404", Severity.ERROR, i,
                    f"{g.label(i)} has a {e.trigger} edge, which a {ntype} state never emits",
                    detail=(
                        f"edge {e.index}: S{e.src:02d} --{e.trigger}--> S{e.dst:02d}\n"
                        f"a {ntype} state emits only: {_trigger_list(allowed)}"
                    ),
                )


@rule(
    "TG405",
    name="guard-not-exhaustive",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Every (state, trigger) group needs exactly one unguarded default, emitted last -- "
        "edge resolution is first-match-wins."
    ),
    decision="D3",
)
def guard_not_exhaustive(ctx: GraphContext) -> Iterator[Diagnostic]:
    """Guarded fan-out that can fall through, or that shadows itself.

    A trigger group is not one edge. D3's response branch is a DELAY with TWO
    TIMEOUT edges: `ch == @target` to the response hold, and an unguarded default
    to the wrong-port penalty. So the model's "DELAY -- exactly one exit" means one
    TRIGGER, N edges.

    Two failures live here, and the second is the nastier:

      * guarded-only with no default -- the guard fails, nothing matches, the state
        has no exit: a hang.
      * a default emitted BEFORE a guarded edge -- the default always matches
        first, so the guarded path is unreachable. That is a silent MIS-SCORE
        rather than a hang, which makes it harder to notice and worse to have.
    """
    g = ctx.graph
    for i in range(g.n):
        groups: dict[tuple, list] = {}
        for e in g.out_edges(i):
            groups.setdefault((e.trigger, e.channel), []).append(e)

        for (trig, channel), edges in groups.items():
            where = f"{trig}" + (f"({channel})" if channel else "")
            defaults = [e for e in edges if e.guard is None]

            if not defaults:
                guards = ", ".join(repr(e.guard) for e in edges)
                yield _d(
                    ctx, "TG405", Severity.ERROR, i,
                    f"{g.label(i)} — every {where} edge is guarded, with no default",
                    detail=f"guards: {guards}\nIf none matches, the state has no exit.",
                )
                continue

            if len(defaults) > 1:
                yield _d(
                    ctx, "TG405", Severity.ERROR, i,
                    f"{g.label(i)} — {len(defaults)} unguarded {where} edges",
                    detail="Only the first can ever fire; the rest are unreachable.",
                )

            shadowed = [e for e in edges if e.guard is not None and e.index > defaults[0].index]
            if shadowed:
                yield _d(
                    ctx, "TG405", Severity.ERROR, i,
                    f"{g.label(i)} — the unguarded {where} edge is not last",
                    detail=(
                        "Edge resolution is first-match-wins, so the default matches before\n"
                        f"{len(shadowed)} guarded edge(s), which can never fire:\n"
                        + "\n".join(
                            f"  edge {e.index}: guard {e.guard!r} -> S{e.dst:02d}" for e in shadowed
                        )
                        + "\nThis mis-scores trials silently rather than hanging."
                    ),
                )


@rule(
    "TG406",
    name="watch-mask-mismatch",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Only WAIT_ENTRY, HOLD and WAIT_EXIT watch channels. A DELAY, PULSE or TERMINAL that "
        "watches one would poll and never react."
    ),
)
def watch_mask_mismatch(ctx: GraphContext) -> Iterator[Diagnostic]:
    g = ctx.graph
    watching = {NodeType.WAIT_ENTRY, NodeType.HOLD, NodeType.WAIT_EXIT}
    for i, ntype in enumerate(g.types):
        mask = g.watch_masks[i]
        if ntype not in watching and mask:
            yield _d(
                ctx, "TG406", Severity.ERROR, i,
                f"{g.label(i)} watches {list(mask)}, but a {ntype} state polls nothing",
            )
        elif ntype in watching and not mask:
            yield _d(
                ctx, "TG406", Severity.ERROR, i,
                f"{g.label(i)} watches nothing, but a {ntype} state exists to react to a channel",
            )


# --------------------------------------------------------------------------- #
# Reachability and termination
# --------------------------------------------------------------------------- #


def _sever_terminals(g: GraphView) -> dict[int, list[int]]:
    """Successors, with TERMINAL out-edges removed.

    Terminals wire back to the entry node -- that is trial selection returning, not
    intra-trial control flow. Leaving those edges in makes the whole task one giant
    strongly-connected component and defeats both analyses below.
    """
    succ: dict[int, list[int]] = {i: [] for i in range(g.n)}
    for e in g.edges:
        if g.types[e.src] is not NodeType.TERMINAL:
            succ[e.src].append(e.dst)
    return succ


def _reachable(g: GraphView, succ: dict[int, list[int]]) -> set[int]:
    seen, stack = {g.entry}, [g.entry]
    while stack:
        for nxt in succ[stack.pop()]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


@rule(
    "TG402",
    name="unreachable-state",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Wire an edge to the state, or stop emitting it. An unreachable state is dead weight "
        "in a table with a hard size limit."
    ),
)
def unreachable_state(ctx: GraphContext) -> Iterator[Diagnostic]:
    g = ctx.graph
    reach = _reachable(g, _sever_terminals(g))
    for i in sorted(set(range(g.n)) - reach):
        yield _d(
            ctx, "TG402", Severity.ERROR, i,
            f"{g.label(i)} is unreachable from the entry state",
            detail=f"entry is S{g.entry:02d}; nothing routes here.",
        )


@rule(
    "TG403",
    name="no-path-to-terminal",
    severity=Severity.ERROR,
    pass_=Pass.GRAPH,
    help=(
        "Every reachable state must be able to reach a TERMINAL. A trial entering one of these "
        "runs until the watchdog fires."
    ),
)
def no_path_to_terminal(ctx: GraphContext) -> Iterator[Diagnostic]:
    """"Every path terminates" — reformulated, because cycle detection is the
    wrong frame.

    Cycle-freedom is neither necessary nor sufficient:

      * NOT NECESSARY — the graph is intentionally cyclic. Terminals wire back to
        `arm` on ADVANCE/REPEAT, so a plain cycle check flags the entire task as
        one component.
      * NOT SUFFICIENT — a reachable, acyclic state with no outgoing edge hangs
        exactly as hard as a loop, and passes any cycle check.

    TERMINAL co-reachability subsumes both, and catches guard-starved fan-outs
    too. Three linear passes: sever the terminals, forward BFS from entry, reverse
    BFS from the terminals. Anything reachable but not co-reachable is a trap.

    Tarjan then runs over ONLY the trapped set, purely so the message can print the
    actual loop rather than an unordered list of node ids.
    """
    g = ctx.graph
    succ = _sever_terminals(g)
    reach = _reachable(g, succ)

    pred: dict[int, list[int]] = {i: [] for i in range(g.n)}
    for src, dsts in succ.items():
        for dst in dsts:
            pred[dst].append(src)

    terminals = [i for i, t in enumerate(g.types) if t is NodeType.TERMINAL]
    co, stack = set(terminals), list(terminals)
    while stack:
        for prv in pred[stack.pop()]:
            if prv not in co:
                co.add(prv)
                stack.append(prv)

    trapped = reach - co
    if not trapped:
        return

    # Report only the SINKS of the trapped subgraph.
    #
    # Every state upstream of a trap is itself trapped, so a naive report names
    # the whole approach path -- on a real task that is most of the trial, and the
    # one node that is actually broken is buried. The condensation's sink
    # components are the traps proper; everything else is a consequence, and is
    # named as a count instead.
    groups = _sccs(trapped, succ)
    owner = {node: i for i, grp in enumerate(groups) for node in grp}
    has_exit = set()
    for i, grp in enumerate(groups):
        for src in grp:
            for dst in succ[src]:
                if dst in trapped and owner[dst] != i:
                    has_exit.add(i)

    for gi, group in enumerate(groups):
        if gi in has_exit:
            continue
        upstream = len(trapped) - len(group)
        if len(group) == 1:
            i = next(iter(group))
            outs = g.out_edges(i)
            reason = (
                "It has no outgoing edges at all."
                if not outs
                else "Every edge leaving it lands back inside the trapped set."
            )
            yield _d(
                ctx, "TG403", Severity.ERROR, i,
                f"{g.label(i)} can never reach a TERMINAL",
                detail=f"{reason}\nA trial entering it runs until the watchdog fires."
                + (f"\n{upstream} further state(s) lead here and are stuck too." if upstream else ""),
            )
        else:
            ordered = sorted(group)
            lines = [
                f"  {g.label(src)} --{e.trigger}--> S{e.dst:02d}"
                for src in ordered
                for e in g.out_edges(src)
                if e.dst in group
            ]
            yield _d(
                ctx, "TG403", Severity.ERROR, min(ordered),
                f"{len(group)} states form a loop with no path to a TERMINAL",
                detail="\n".join(lines)
                + "\nNo edge leaves this group."
                + (f"\n{upstream} further state(s) lead here and are stuck too." if upstream else ""),
            )


def _sccs(nodes: set[int], succ: dict[int, list[int]]) -> list[set[int]]:
    """Tarjan, restricted to `nodes`.

    Iterative rather than recursive: a table is allowed 64 states, and a deep chain
    would be an unpleasant way to discover Python's recursion limit.
    """
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on_stack: set[int] = set()
    stack: list[int] = []
    out: list[set[int]] = []
    counter = 0

    for root in sorted(nodes):
        if root in index:
            continue
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)
        work = [(root, iter(succ[root]))]

        while work:
            node, it = work[-1]
            advanced = False
            for nxt in it:
                if nxt not in nodes:
                    continue
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(succ[nxt])))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = set()
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.add(w)
                    if w == node:
                        break
                out.append(comp)
    return out


# --------------------------------------------------------------------------- #
# Informational
# --------------------------------------------------------------------------- #


@rule(
    "TG901",
    name="unbounded-dwell",
    severity=Severity.INFO,
    pass_=Pass.GRAPH,
    help=(
        "Listing-only. These states have no duration and are bounded solely by the Phase 4 "
        "runtime watchdog."
    ),
)
def unbounded_dwell(ctx: GraphContext) -> Iterator[Diagnostic]:
    """WAIT_EXIT has no timeout, by definition.

    NOT an error: both GRGL instances -- sampling release and consumption -- are
    legitimate, and firmware has no timeout there either, so erroring would reject
    every valid task. NOT a warning either: it would fire on every compile of every
    spec, and a warning that is always present trains people to skip warnings,
    which costs the one that matters (TG231).

    So: INFO, listing-only, and the compiler hands Phase 4 the exact enumeration
    instead. tgWatchdogExpired() already takes a maxDwellMs; this is what tells it
    which states it is the only thing standing behind.
    """
    g = ctx.graph
    for i, ntype in enumerate(g.types):
        if ntype not in BOUNDED and ntype is not NodeType.TERMINAL:
            yield _d(
                ctx, "TG901", Severity.INFO, i,
                f"{g.label(i)} is bounded only by the runtime watchdog",
            )
