"""Replay: does the compiled graph accept a strobe stream a real box produced?

THE CHEAPEST CONFIDENCE IN THE PROJECT. The data already exists — hundreds of
recorded sessions — so this checks a hand-written spec against reality before a
single line of firmware is written, at no risk to anything.

-----------------------------------------------------------------------------
THE FORMULATION

Every strobe is a state-ENTRY code; nothing is emitted on an edge. So a recorded
session is exactly the sequence of entry codes along one path through the graph,
and "does the graph accept this session?" is asking whether such a path exists.

That makes the graph an NFA over strobe codes:

  * a state that emits a code is a labelled transition;
  * a state that emits nothing is an EPSILON transition — and those are not
    hypothetical, because current firmware is deliberately silent on the omission
    path;
  * a state whose strobe is a @binding can emit any of several codes depending on
    the trial, so it is a transition labelled with that SET.

Acceptance is reachability in the product of the graph and the observed sequence:
a frontier walk, linear in (states x events).

WHY NOT SIMULATE AND DIFF. The obvious alternative is to run the forward
interpreter and compare its output to the recording. That needs the subject's
exact behaviour and the exact trial sequence, and the recording determines
neither — a single ambiguity makes the comparison fail for reasons that have
nothing to do with the graph. Acceptance asks the weaker question the data can
actually answer, which is the whole reason this check is cheap.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass, field

from taskgraph.registries import vocabulary
from taskgraph.spec import TaskSpec
from taskgraph.table import NO_STROBE, StateTable, is_bound

#: Emitted by the sketch's session wrapper, not by any trial state. The graph
#: models a TRIAL, so matching these against a node would reject every session on
#: its first event.
#:
#: START_SESSION additionally RESETS the walk. It means "recording start,
#: timestamp 0", so a file containing two of them holds two runs — one box was
#: restarted without a new file being opened. Skipping it instead would leave the
#: walk mid-trial when the next run's first LIGHTS_ON arrived, and reject a
#: session for something that is not a modelling error at all.
SESSION_SCOPE = ("START_SESSION", "END_SESSION")
RESET_ON = "START_SESSION"

#: Per-port strobe fields a @binding may name.
PORT_FIELDS = ("enter_code", "error_code", "break_code", "exit_code",
               "reward_code", "reward_stop_code")


@dataclass(frozen=True)
class Divergence:
    """Where a stream stopped being explainable, and what the graph expected."""

    index: int
    code: int
    name: str
    timestamp: int
    expected: tuple[str, ...]
    context: tuple[str, ...]

    def format(self) -> str:
        exp = ", ".join(self.expected) if self.expected else "(nothing — the walk is stuck)"
        ctx = " → ".join(self.context) if self.context else "(start of session)"
        return (
            f"event {self.index} at t={self.timestamp} ms: observed "
            f"{self.name}({self.code}), which no reachable state emits\n"
            f"    preceding:  {ctx}\n"
            f"    acceptable: {exp}"
        )


@dataclass
class ReplayResult:
    accepted: bool
    events: int
    consumed: int
    divergence: Divergence | None = None
    #: Codes the vocabulary does not declare at all. Reported SEPARATELY from a
    #: divergence, because the two are different findings: an unknown code is a gap
    #: in the vocabulary (or a session from firmware that predates it), while a
    #: known code in an impossible place is a gap in the GRAPH. Conflating them
    #: hides every graph result for any session that contains one.
    unknown: dict[int, int] = field(default_factory=dict)
    #: Codes from firmware this repo no longer contains, recognised by name. Kept
    #: apart from `unknown` because one is explained and the other is a question.
    retired: dict[str, int] = field(default_factory=dict)
    #: Nodes the walk actually entered. A state never reached across a whole
    #: corpus is one no animal has ever driven the box into — worth knowing
    #: whether or not the session was accepted.
    visited: set[int] = field(default_factory=set)

    @property
    def progress(self) -> float:
        return self.consumed / self.events if self.events else 1.0


class GraphAcceptor:
    """An NFA over strobe codes, built once per compiled spec."""

    def __init__(self, spec: TaskSpec, table: StateTable) -> None:
        self.spec = spec
        self.table = table
        self.vocab = vocabulary()
        self._session_codes = {
            self.vocab.code_of(n) for n in SESSION_SCOPE if n in self.vocab
        }
        self._reset_code = self.vocab.code_of(RESET_ON) if RESET_ON in self.vocab else None
        self._emits = [self._codes_for(n) for n in table.nodes]
        self._succ = self._successors()

    # -- construction ------------------------------------------------------ #

    def _codes_for(self, node) -> frozenset[int]:
        """Every code this state entry could emit.

        A literal name is one code; a @binding is the SET the contingency table can
        resolve it to — `@ports[$ch].enter_code` is {248, 249} on a two-port task.
        Silence is the empty set, which is what makes the state an epsilon
        transition.
        """
        # A bound strobe carries a SELECTOR, not a code. Resolve it to the set of
        # codes it can take -- treating the selector as a literal would look for
        # code 65281 in the stream and match nothing, ever.
        if not is_bound(node.strobe) and node.strobe != NO_STROBE:
            return frozenset({node.strobe})
        if not node.strobe_name:
            return frozenset()
        return self._resolve_binding(node.strobe_name)

    def _resolve_binding(self, expr: str) -> frozenset[int]:
        """The range a @binding can take over every trial the spec permits.

        Deliberately over-approximate. Replay asks whether SOME trial explains the
        stream; pinning the exact one would mean reconstructing the selection RNG,
        which the recording does not determine. The linter has already proved every
        binding resolves — this only needs the range.
        """
        c = self.spec.contingency
        out: set[int] = set()

        if expr.startswith("@stim"):
            for s in c.stimuli:
                if s.on_code and s.on_code in self.vocab:
                    out.add(self.vocab.code_of(s.on_code))
            return frozenset(out)

        field_name = expr.rsplit(".", 1)[-1]
        if field_name not in PORT_FIELDS:
            return frozenset()
        for port in c.ports.values():
            name = getattr(port, field_name, None)
            if name and name in self.vocab:
                out.add(self.vocab.code_of(name))
        return frozenset(out)

    def _successors(self) -> list[tuple[int, ...]]:
        t = self.table
        out = []
        for i in range(len(t.nodes)):
            end = t.nodes[i + 1].edge_idx if i + 1 < len(t.nodes) else len(t.edges)
            out.append(tuple(e.target for e in t.edges[t.nodes[i].edge_idx : end]))
        return out

    # -- the walk ---------------------------------------------------------- #

    def _closure(self, frontier: set[int]) -> set[int]:
        """Follow silent states.

        Bounded by node count rather than path length. A cycle of silent states
        would otherwise spin forever, and the linter permits silent states, so that
        cannot be assumed away.
        """
        seen = set(frontier)
        stack = [n for n in frontier]
        while stack:
            for nxt in self._succ[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    if not self._emits[nxt]:
                        stack.append(nxt)
        return seen

    def accept(self, stream: list[tuple[int, int]]) -> ReplayResult:
        """Walk a recorded `(code, timestamp)` stream through the graph."""
        frontier = self._closure({0})
        visited = set(frontier)
        names = [
            self.vocab.name_of(c) or self.vocab.retired_name(c) or f"UNKNOWN_{c}"
            for c, _ in stream
        ]

        unknown: dict[int, int] = {}
        retired: dict[str, int] = {}
        for i, (code, ts) in enumerate(stream):
            if code == self._reset_code:
                frontier = self._closure({0})
                visited |= frontier
                continue
            if code in self._session_codes:
                continue
            retired_as = self.vocab.retired_name(code)
            if retired_as is not None:
                # A code whose emitter is gone. Stepped over, and named -- a legacy
                # session should report "retired code" rather than "unknown code".
                retired[retired_as] = retired.get(retired_as, 0) + 1
                continue
            if self.vocab.name_of(code) is None:
                # Not in the vocabulary at all. Counted and stepped over, so the
                # rest of the session is still checked against the graph.
                unknown[code] = unknown.get(code, 0) + 1
                continue

            landed = {n for n in frontier if code in self._emits[n]}
            if not landed:
                return ReplayResult(
                    accepted=False,
                    events=len(stream),
                    consumed=i,
                    visited=visited,
                    divergence=Divergence(
                        index=i,
                        code=code,
                        name=names[i],
                        timestamp=ts,
                        expected=self._expected(frontier),
                        context=tuple(names[max(0, i - 4) : i]),
                    ),
                    unknown=unknown,
                    retired=retired,
                )
            visited |= landed

            nxt: set[int] = set()
            for n in landed:
                nxt.update(self._succ[n])
            frontier = self._closure(nxt)
            visited |= frontier

        return ReplayResult(
            accepted=True, events=len(stream), consumed=len(stream),
            visited=visited, unknown=unknown, retired=retired,
        )

    def _expected(self, frontier: set[int]) -> tuple[str, ...]:
        codes: set[int] = set()
        for n in frontier:
            codes |= self._emits[n]
        return tuple(sorted(self.vocab.name_of(c) or f"UNKNOWN_{c}" for c in codes))

    def label(self, i: int) -> str:
        n = self.table.nodes[i]
        return f"S{i:02d} {n.type} \"{n.label}\""

    def unreached(self, visited: set[int]) -> list[int]:
        return [i for i in range(len(self.table.nodes)) if i not in visited]
