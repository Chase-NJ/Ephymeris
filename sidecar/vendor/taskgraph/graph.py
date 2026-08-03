"""The graph model: symbolic drafts, the builder that emits them, and the
structure-only view the graph linter sees.

Three things here are load-bearing.

DRAFTS ARE SYMBOLIC. A template emits StrobeRef("LIGHTS_OFF") and
TimingRef("t_zero"), never a number. Resolution happens in one place afterwards,
which keeps templates unit-testable without a vocabulary and stops every future
template version from growing its own copy of the lookup rules.

EVERY NODE AND EDGE CARRIES PROVENANCE. Nobody authored these nodes -- they came
out of a template -- so a diagnostic saying "state S12 has no path to a terminal"
is unactionable: the reader's spec contains no S12. Provenance is what lets the
message name the template line, the epoch band, and the topology knobs that
selected that branch.

GraphView IS STRUCTURE ONLY. It carries node types, watch masks and edges, and
nothing else. The graph rules fire on TEMPLATE bugs rather than spec bugs, so they
have to be testable by hand-constructing a broken graph with no spec in sight.
Handing them a TaskSpec would make most of the linter untestable, because most
malformed graphs are simply not reachable from a valid YAML file.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeType(enum.IntEnum):
    """The six primitives. Nothing else is representable, which is what keeps the
    interpreter fixed and the graph tractable.

    Ordinals go on the wire (TgNodeType in TaskTable.h), so they are stable.
    """

    DELAY = 0
    WAIT_ENTRY = 1
    HOLD = 2
    WAIT_EXIT = 3
    PULSE = 4
    TERMINAL = 5

    def __str__(self) -> str:
        return self.name


class Trigger(enum.IntEnum):
    TIMEOUT = 0
    ENTER = 1
    HELD = 2
    BROKEN = 3
    EXIT = 4
    DONE = 5
    ADVANCE = 6
    REPEAT = 7

    def __str__(self) -> str:
        return self.name


#: Which triggers each primitive can emit. THE authority for trigger totality --
#: the linter checks emitted edges against this and nothing else.
#:
#: WAIT_EXIT deliberately has no TIMEOUT. It is unbounded by definition: both GRGL
#: instances (sampling release, consumption) wait indefinitely for the animal to
#: withdraw, and firmware has no timeout there either. That is the Phase 4
#: watchdog's job, not the linter's -- see docs/spikes/avr-ram.md.
TRIGGERS_FOR: dict[NodeType, frozenset[Trigger]] = {
    NodeType.DELAY: frozenset({Trigger.TIMEOUT}),
    NodeType.WAIT_ENTRY: frozenset({Trigger.ENTER, Trigger.TIMEOUT}),
    NodeType.HOLD: frozenset({Trigger.HELD, Trigger.BROKEN}),
    NodeType.WAIT_EXIT: frozenset({Trigger.EXIT}),
    NodeType.PULSE: frozenset({Trigger.DONE}),
    NodeType.TERMINAL: frozenset({Trigger.ADVANCE, Trigger.REPEAT}),
}

#: Node types whose dwell is bounded by their duration. Everything else is bounded
#: only by the runtime watchdog, and the compiler enumerates those for Phase 4.
BOUNDED = frozenset({NodeType.DELAY, NodeType.WAIT_ENTRY, NodeType.HOLD, NodeType.PULSE})


class Band(enum.IntEnum):
    """The four epoch bands, in order. Purely descriptive -- it drives the listing
    and the diagnostics, never the semantics."""

    ENGAGEMENT = 1
    SAMPLING = 2
    RESPONSE = 3
    OUTCOME = 4

    def __str__(self) -> str:
        return self.name.lower()


# --------------------------------------------------------------------------- #
# Symbolic references
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TimingRef:
    """A timing id. Resolved to a vector index during lowering, never earlier."""

    id: str

    def __str__(self) -> str:
        return self.id


@dataclass(frozen=True)
class StrobeRef:
    """A strobe name from the append-only vocabulary."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class BindingRef:
    """A `@`-prefixed reference resolved from the trial binding at selection time,
    or from the runtime event.

    `@target`             the correct port for this trial
    `@stim[$stage]`       the stimulus bound to the sampling stage being entered
    `@ports[$ch]`         the port whose channel fired the triggering event

    `$ch` is what lets ONE branch node serve every response port instead of one
    node per port; `$stage` is what makes a sampling chain an unroll rather than a
    rewrite.
    """

    expr: str

    def __str__(self) -> str:
        return self.expr


StrobeSpec = StrobeRef | BindingRef | None


@dataclass(frozen=True)
class ChannelRef:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class ActionDraft:
    """An actuator set/clear applied the instant a node is entered."""

    channel: ChannelRef | BindingRef
    on: bool

    def __str__(self) -> str:
        return f"{'set' if self.on else 'clear'} {self.channel}"


@dataclass(frozen=True)
class Provenance:
    """Where a node or edge came from, and why.

    `knobs` records the topology values that selected this branch, which is what
    turns "S12 has no path to a terminal" into "S12 exists because
    n_sampling_stages=2 and retention_delay=true".
    """

    template: str
    line: int
    band: Band
    knobs: tuple[tuple[str, object], ...] = ()

    def describe(self) -> str:
        knobs = ", ".join(f"{k}={v}" for k, v in self.knobs)
        where = f"{self.template}:{self.line} (band {int(self.band)}, {self.band})"
        return f"{where}\nselected by: {knobs}" if knobs else where


# --------------------------------------------------------------------------- #
# Drafts
# --------------------------------------------------------------------------- #


@dataclass
class NodeDraft:
    id: str                      # symbolic, e.g. "resp_branch"
    type: NodeType
    band: Band
    duration: TimingRef | None = None
    strobe: StrobeSpec = None
    watch: tuple[ChannelRef | BindingRef, ...] = ()
    entry_actions: tuple[ActionDraft, ...] = ()
    label: str = ""
    provenance: Provenance | None = None
    #: True when the strobe was deliberately omitted rather than forgotten. The
    #: linter reports silence differently depending on which it is.
    silent_by_design: bool = False


@dataclass
class EdgeDraft:
    src: str
    dst: str
    trigger: Trigger
    guard: str | None = None      # None == the unguarded default
    effect: str | None = None
    #: Which channel an ENTER edge is for. Trigger totality on a WAIT_ENTRY is a
    #: BIJECTION between watched channels and ENTER edges, so this is required
    #: there: one ENTER edge for two watched ports silently drops a port.
    channel: str | None = None
    provenance: Provenance | None = None


@dataclass
class GraphDraft:
    nodes: list[NodeDraft] = field(default_factory=list)
    edges: list[EdgeDraft] = field(default_factory=list)
    entry: str = ""

    def node(self, node_id: str) -> NodeDraft:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def out_edges(self, node_id: str) -> list[EdgeDraft]:
        return [e for e in self.edges if e.src == node_id]


# --------------------------------------------------------------------------- #
# The structure-only view
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ViewEdge:
    index: int          # emission order -- guard precedence is first-match-wins
    src: int
    dst: int
    trigger: Trigger
    guard: str | None
    channel: str | None


@dataclass(frozen=True)
class GraphView:
    """What the TG4xx rules see: shape, and nothing else.

    Constructible by hand in a test. That is the entire point -- a WAIT_ENTRY
    missing its TIMEOUT edge cannot be produced by any valid spec, so if the graph
    rules needed a spec they could never be tested at all.
    """

    types: tuple[NodeType, ...]
    watch_masks: tuple[tuple[str, ...], ...]
    edges: tuple[ViewEdge, ...]
    entry: int = 0
    labels: tuple[str, ...] = ()

    @property
    def n(self) -> int:
        return len(self.types)

    def out_edges(self, node: int) -> list[ViewEdge]:
        return [e for e in self.edges if e.src == node]

    def label(self, node: int) -> str:
        if node < len(self.labels) and self.labels[node]:
            return f'S{node:02d} {self.types[node]} "{self.labels[node]}"'
        return f"S{node:02d} {self.types[node]}"

    @classmethod
    def from_draft(cls, draft: GraphDraft) -> GraphView:
        order = {n.id: i for i, n in enumerate(draft.nodes)}
        edges = tuple(
            ViewEdge(
                index=i,
                src=order[e.src],
                dst=order[e.dst],
                trigger=e.trigger,
                guard=e.guard,
                channel=e.channel,
            )
            for i, e in enumerate(draft.edges)
        )
        return cls(
            types=tuple(n.type for n in draft.nodes),
            watch_masks=tuple(tuple(str(w) for w in n.watch) for n in draft.nodes),
            edges=edges,
            entry=order[draft.entry] if draft.entry else 0,
            labels=tuple(n.label or n.id for n in draft.nodes),
        )


# --------------------------------------------------------------------------- #
# Builder
# --------------------------------------------------------------------------- #


class EpochBuilder:
    """What a template writes against.

    Owns node id allocation, band tagging and provenance capture, so a template
    body reads as a description of the epoch structure rather than as bookkeeping.
    """

    def __init__(self, template: str, knobs: dict[str, object]) -> None:
        self._template = template
        self._knobs = tuple(sorted(knobs.items(), key=lambda kv: kv[0]))
        self.draft = GraphDraft()
        self._band = Band.ENGAGEMENT

    def band(self, band: Band) -> None:
        self._band = band

    def _prov(self, depth: int = 2) -> Provenance:
        import inspect

        frame = inspect.stack()[depth]
        return Provenance(
            template=self._template, line=frame.lineno, band=self._band, knobs=self._knobs
        )

    def node(
        self,
        node_id: str,
        node_type: NodeType,
        *,
        duration: str | None = None,
        strobe: str | None = None,
        watch: tuple[str, ...] = (),
        actions: tuple[ActionDraft, ...] = (),
        label: str = "",
        silent_by_design: bool = False,
    ) -> str:
        def as_strobe(s: str | None) -> StrobeSpec:
            if s is None:
                return None
            return BindingRef(s) if s.startswith("@") else StrobeRef(s)

        def as_channel(c: str) -> ChannelRef | BindingRef:
            return BindingRef(c) if c.startswith("@") else ChannelRef(c)

        self.draft.nodes.append(
            NodeDraft(
                id=node_id,
                type=node_type,
                band=self._band,
                duration=TimingRef(duration) if duration else None,
                strobe=as_strobe(strobe),
                watch=tuple(as_channel(c) for c in watch),
                entry_actions=actions,
                label=label or node_id,
                provenance=self._prov(),
                silent_by_design=silent_by_design,
            )
        )
        if not self.draft.entry:
            self.draft.entry = node_id
        return node_id

    def edge(
        self,
        src: str,
        dst: str,
        trigger: Trigger,
        *,
        guard: str | None = None,
        effect: str | None = None,
        channel: str | None = None,
    ) -> None:
        self.draft.edges.append(
            EdgeDraft(
                src=src,
                dst=dst,
                trigger=trigger,
                guard=guard,
                effect=effect,
                channel=channel,
                provenance=self._prov(),
            )
        )

    def set_(self, channel: str) -> ActionDraft:
        return ActionDraft(
            ChannelRef(channel) if not channel.startswith("@") else BindingRef(channel), True
        )

    def clear(self, channel: str) -> ActionDraft:
        return ActionDraft(
            ChannelRef(channel) if not channel.startswith("@") else BindingRef(channel), False
        )
