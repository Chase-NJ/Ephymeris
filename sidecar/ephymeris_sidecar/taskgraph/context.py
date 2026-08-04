"""Pass contexts — what each band of rules is allowed to see.

These are deliberately narrow. `GraphContext` in particular carries a GraphView
and nothing else: the graph rules fire on TEMPLATE bugs, not spec bugs, so they
must be testable by hand-constructing a broken graph without a spec anywhere in
sight. Handing them the TaskSpec would make half the linter untestable, because
most malformed graphs are simply not reachable from a valid YAML file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ephymeris_sidecar.taskgraph.registries import ChannelMap, Limits, Vocabulary, channels, limits, vocabulary
from ephymeris_sidecar.taskgraph.spec import TaskSpec

if TYPE_CHECKING:
    from ephymeris_sidecar.taskgraph.graph import GraphView


@dataclass
class SpecContext:
    """P1/P2 — a bound spec plus the three frozen registries."""

    spec: TaskSpec
    vocab: Vocabulary = field(default_factory=vocabulary)
    channels: ChannelMap = field(default_factory=channels)
    limits: Limits = field(default_factory=limits)
    #: Set in P2 once the template is resolved.
    capabilities: dict[str, Any] | None = None

    @property
    def spec_id(self) -> str:
        return self.spec.spec_id


@dataclass
class GraphContext:
    """P4 — structure only.

    No spec, no vocabulary, no channel map. If a graph rule needs one of those,
    the rule is misfiled: it is checking a resolution question in a pass that
    exists to check shape.
    """

    graph: GraphView
    spec_id: str | None = None


@dataclass
class TableContext:
    """P5 — the lowered table plus the limits it must fit inside."""

    table: Any  # StateTable; typed loosely to avoid an import cycle
    limits: Limits = field(default_factory=limits)
    spec_id: str | None = None
