"""P3 — lower a symbolic GraphDraft into a StateTable.

Two jobs: resolve every symbolic reference to a number, and lay the records out so
the firmware's implicit conventions hold.

THE EDGE LAYOUT IS THE SUBTLE PART. TgNode stores only `edgeIdx`; the count is
implied by the NEXT node's offset. So edges must be sorted by owning node and the
offsets must be non-decreasing across the whole table. Violate that and every node
past the break reads someone else's edges -- which is not a crash, it is a box
running a different task than the one that was uploaded.

@binding resolution happens here rather than in P1 because a binding is only
meaningful once a node holds it: `@ports[$ch].error_code` is resolvable only when
you know the node is the wrong-port branch and `$ch` ranges over the response
ports.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.errors import Diagnostic, DiagnosticBag, Severity
from ephymeris_sidecar.taskgraph.graph import (
    BOUNDED,
    ActionDraft,
    BindingRef,
    GraphDraft,
    NodeType,
    StrobeRef,
)
from ephymeris_sidecar.taskgraph.registries import ChannelMap, Vocabulary
from ephymeris_sidecar.taskgraph.spec import TaskSpec
from ephymeris_sidecar.taskgraph.table import (
    BINDINGS,
    CH_BIND_ALL_EMITTERS,
    CH_BIND_STIM_EMITTER_0,
    CH_BIND_TARGET_REWARD_LINE,
    DUR_FROM_TRIAL,
    EFFECT_ADVANCE,
    EFFECT_NONE,
    EFFECT_REPEAT,
    GUARD_CORRECTION,
    GUARD_IS_TARGET,
    GUARD_NONE,
    NO_STROBE,
    NO_TARGET,
    Action,
    Edge,
    Node,
    Port,
    StageRowOut,
    StateTable,
    Stimulus,
    TimingSet,
    TrialTypeRow,
)

#: Guard and effect opcodes. Small closed sets: the interpreter switches on them,
#: so they are numbers on the wire and names in the listing.
#: Stable opcodes, shared with the C++ interpreter through TaskTable.h. A
#: dict that grew on demand would renumber itself as specs changed, which is
#: fine in Python and catastrophic on the wire.
GUARDS = {None: GUARD_NONE, "ch == @target": GUARD_IS_TARGET,
          "correction budget": GUARD_CORRECTION}


def _effect_code(text: str | None) -> int:
    if text == "advance":
        return EFFECT_ADVANCE
    if text == "repeat":
        return EFFECT_REPEAT
    return EFFECT_NONE


class Lowerer:
    def __init__(
        self,
        spec: TaskSpec,
        vocab: Vocabulary,
        channels: ChannelMap,
        bag: DiagnosticBag,
    ) -> None:
        self.spec = spec
        self.vocab = vocab
        self.channels = channels
        self.bag = bag

    # -- resolution ------------------------------------------------------- #

    def _unresolved(self, what: str, expr: str, node: str) -> None:
        self.bag.add(
            Diagnostic(
                code="TG250",
                severity=Severity.ERROR,
                spec_id=self.spec.spec_id,
                location=node,
                message=f"{what} {expr!r} does not resolve against the contingency table",
                help=(
                    "The template asked for a binding this spec does not provide. Either the "
                    "spec is missing a port/stimulus field, or the template needs a new version."
                ),
            )
        )

    def strobe_code(self, ref, node_id: str) -> tuple[int, str]:
        """Resolve a node's entry strobe to a code, or NO_STROBE.

        A binding that varies per trial (`@ports[$ch].enter_code`) cannot be a
        single number: the firmware resolves it at runtime from the trial binding.
        It is emitted as NO_STROBE with the expression kept for the listing, and
        the interpreter substitutes. Recording the expression rather than dropping
        it is what keeps the listing honest about what will actually be emitted.
        """
        if ref is None:
            return NO_STROBE, ""
        if isinstance(ref, StrobeRef):
            entry = self.vocab.get(ref.name)
            if entry is None:
                self._unresolved("strobe", ref.name, node_id)
                return NO_STROBE, ref.name
            return entry.code, ref.name
        if isinstance(ref, BindingRef):
            sel = self._selector(ref.expr)
            if sel is None:
                self._unresolved("strobe binding", ref.expr, node_id)
                return NO_STROBE, ref.expr
            from ephymeris_sidecar.taskgraph.table import bind_code

            return bind_code(sel), ref.expr
        return NO_STROBE, ""

    @staticmethod
    def _selector(expr: str) -> int | None:
        """`@ports[$ch].enter_code` -> BIND_PORT_ENTER.

        The index part is dropped: which port or stage is a RUNTIME question, and
        answering it here would bake one trial's answer into a table meant to serve
        every trial.
        """
        head, _, field_name = expr.partition(".")
        base = head.split("[")[0]
        if base == "@stim":
            # The stage rides in the selector, because the unroll is static.
            inner = head[head.index("[") + 1 : head.index("]")] if "[" in head else "0"
            return int(inner) if inner.isdigit() else 0
        return BINDINGS.get(f"{base}.{field_name}")

    def channel_index(self, ref, node_id: str) -> tuple[int, str]:
        name = str(ref)
        if name.startswith("@"):
            # Runtime-resolved. Encoded the same way as a bound strobe: pins are
            # <= 53, so the high byte is free to carry a selector.
            if name.startswith("@stim"):
                inner = name[name.index("[") + 1 : name.index("]")]
                if not inner.isdigit():
                    # "@stim[$stage].emitter" on an abort path: clear whatever is
                    # on rather than tracking which stage put it there.
                    return CH_BIND_ALL_EMITTERS, name
                return CH_BIND_STIM_EMITTER_0 + int(inner), name
            if name.startswith("@target"):
                return CH_BIND_TARGET_REWARD_LINE, name
            return NO_TARGET, name
        ch = self.channels.get(name)
        if ch is None:
            self._unresolved("channel", name, node_id)
            return NO_TARGET, name
        return ch.index, name

    def watch_mask(self, watches, node_id: str) -> int:
        mask = 0
        for w in watches:
            name = str(w)
            if name.startswith("@"):
                # A runtime-bound watch (the chosen port). Firmware ORs in the
                # bound channel; statically there is nothing to set.
                continue
            ch = self.channels.get(name)
            if ch is None or ch.watch_bit is None:
                self._unresolved("watched channel", name, node_id)
                continue
            mask |= 1 << ch.watch_bit
        return mask

    def timing_index(self, ref, node_id: str) -> int:
        if ref is None:
            return 0  # t_zero by convention; WAIT_EXIT and TERMINAL have no duration
        name = str(ref)
        if name.startswith("@"):
            # @target.reward_duration -- resolved per trial from the trial-type
            # row, NOT from the timing vector. Must not collapse to index 0.
            return DUR_FROM_TRIAL
        by_id = self.spec.timing_by_id()
        entry = by_id.get(name)
        if entry is None:
            self.bag.add(
                Diagnostic(
                    code="TG251",
                    severity=Severity.ERROR,
                    spec_id=self.spec.spec_id,
                    location=node_id,
                    message=f"the template needs timing id {name!r}, which this spec does not declare",
                    help=(
                        "Add the entry to `timing:`. The template's required set is a function "
                        "of the topology knobs -- see its capabilities()."
                    ),
                )
            )
            return 0
        return entry.index

    def action(self, a: ActionDraft, node_id: str) -> Action:
        idx, name = self.channel_index(a.channel, node_id)
        return Action(channel=idx, op=1 if a.on else 0, channel_name=name)

    # -- lowering --------------------------------------------------------- #

    def run(self, draft: GraphDraft) -> StateTable:
        t = StateTable(
            spec_id=self.spec.spec_id,
            spec_hash=self.spec.spec_hash,
            spec_version=self.spec.spec_version,
            vocab_version=self.spec.vocab_version,
            template=self.spec.topology.template,
            template_version=self.spec.topology.template_version,
            # Stamped HERE because this is the method that turns channel names
            # into pin bytes -- `channel_index`, the port and stimulus loops and
            # `watch_pins` below. The wiring that answered those lookups is the
            # one thing about this table that the spec does not record.
            pinout_id=self.channels.pinout_id,
            pinout_hash=self.channels.content_hash(),
        )

        t.timing = [e.ms for e in self.spec.timing]
        t.timing_ids = [e.id for e in self.spec.timing]

        order = {n.id: i for i, n in enumerate(draft.nodes)}

        # Edges FIRST, grouped by owning node in node order. TgNode carries only an
        # offset, so this grouping is what makes the implied counts correct.
        edges_by_node: dict[int, list] = {i: [] for i in range(len(draft.nodes))}
        for e in draft.edges:
            edges_by_node[order[e.src]].append(e)

        for i in range(len(draft.nodes)):
            for e in edges_by_node[i]:
                t.edges.append(
                    Edge(
                        trigger=e.trigger,
                        guard=GUARDS.get(e.guard, 0),
                        target=order[e.dst],
                        effect=_effect_code(e.effect),
                        guard_text=e.guard or "",
                        effect_text=e.effect or "",
                        channel=e.channel,
                    )
                )

        edge_offset = 0
        for i, nd in enumerate(draft.nodes):
            action_idx = len(t.actions)
            for a in nd.entry_actions:
                t.actions.append(self.action(a, nd.id))

            code, name = self.strobe_code(nd.strobe, nd.id)
            t.nodes.append(
                Node(
                    type=nd.type,
                    dur_idx=self.timing_index(nd.duration, nd.id),
                    strobe=code,
                    watch_mask=self.watch_mask(nd.watch, nd.id),
                    action_idx=action_idx,
                    action_count=len(nd.entry_actions),
                    edge_idx=edge_offset,
                    label=nd.label,
                    symbol=nd.id,
                    band=int(nd.band),
                    strobe_name=name,
                    silent_by_design=nd.silent_by_design,
                    watch_text=tuple(str(w) for w in nd.watch),
                )
            )
            edge_offset += len(edges_by_node[i])

        # Ports and stimuli: what a runtime binding resolves against.
        vocab = self.vocab

        def code(name):
            return vocab.code_of(name) if name and name in vocab else NO_STROBE

        ports = list(self.spec.contingency.ports)
        for pname in ports:
            pb = self.spec.contingency.ports[pname]
            ch = self.channels.get(pb.channel)
            line = self.channels.get(pb.reward_line) if pb.reward_line else None
            rdur = (
                self.spec.timing_by_id().get(pb.reward_duration)
                if pb.reward_duration else None
            )
            t.ports.append(
                Port(
                    channel=ch.index if ch else NO_TARGET,
                    enter_code=code(pb.enter_code),
                    error_code=code(pb.error_code),
                    break_code=code(pb.break_code),
                    exit_code=code(pb.exit_code),
                    reward_code=code(pb.reward_code),
                    reward_stop_code=code(pb.reward_stop_code),
                    reward_line=line.index if line else NO_TARGET,
                    reward_dur_idx=rdur.index if rdur else 0,
                    name=pname,
                )
            )

        # Watch-bit -> pin, and watch-bit -> port index.
        by_port = {self.spec.contingency.ports[n].channel: i for i, n in enumerate(ports)}
        for ch in self.channels.watchable:
            t.watch_pins.append(ch.index)
            t.watch_ports.append(by_port.get(ch.name, NO_TARGET))

        stim_index = {}
        for s in self.spec.contingency.stimuli:
            em = self.channels.get(s.emitter)
            stim_index[s.id] = len(t.stimuli)
            t.stimuli.append(
                Stimulus(
                    emitter=em.index if em else NO_TARGET,
                    on_code=code(s.on_code),
                    name=s.id,
                )
            )

        # Trial types.
        for tt in self.spec.contingency.trial_types:
            stim_idx = [stim_index.get(s, NO_TARGET) for s in tt.stages]
            port = self.spec.contingency.ports.get(tt.target) if tt.target else None
            reward_line = self.channels.get(port.reward_line) if port and port.reward_line else None
            rdur = (
                self.spec.timing_by_id().get(port.reward_duration)
                if port and port.reward_duration
                else None
            )
            t.trial_types.append(
                TrialTypeRow(
                    stimulus=tuple(stim_idx),
                    target=ports.index(tt.target) if tt.target in ports else NO_TARGET,
                    weight=tt.weight,
                    reward_line=reward_line.index if reward_line else NO_TARGET,
                    reward_dur_idx=rdur.index if rdur else 0,
                    label=tt.id,
                )
            )

        # Stage schedule -> rows plus a flat pool of rewrites, addressed by index.
        # This is applyStage() generalised from four fixed fields to N.
        for row in self.spec.policy.stage_schedule:
            first = len(t.timing_sets)
            by_id = self.spec.timing_by_id()
            for tid, ms in row.set.items():
                entry = by_id.get(tid)
                if entry is not None:
                    t.timing_sets.append(TimingSet(idx=entry.index, ms=ms))
            t.stage_rows.append(
                StageRowOut(at_trial=row.at_trial, count=len(t.timing_sets) - first, first_idx=first)
            )

        t.max_dwell = self._max_dwell(t)
        return t

    def _peak_timing(self, t: StateTable) -> list[int]:
        """The largest value each timing entry EVER takes.

        THE STAGE RAMP REWRITES THE TIMING VECTOR AT RUNTIME, so the compiled
        default is not the worst case -- it is merely the first case. In
        `shaping_gr`, `t_commit_hold` is compiled at 10 ms and reaches 500 ms by
        the last stage row, and the same is true of `t_sample_hold` and
        `t_resp_hold`.

        A watchdog budget taken from the compiled value would therefore be 50x too
        small on three nodes, and would fire on essentially every trial past the
        fourth stage -- ending healthy sessions on a false alarm, which is a worse
        outcome than the hang it exists to prevent. The budget has to cover every
        value the entry can hold.
        """
        peak = list(t.timing)
        for s in t.timing_sets:
            if s.idx < len(peak):
                peak[s.idx] = max(peak[s.idx], s.ms)
        return peak

    def _max_dwell(self, t: StateTable) -> list[int | None]:
        """Worst-case dwell per node, for the Phase 4 watchdog.

        None where only the watchdog's own ceiling can bound it -- the two
        WAIT_EXIT states, which wait on the subject rather than on a clock.
        Computing this is the concrete handoff that turns "the linter cannot prove
        this state terminates" into a number the firmware can act on.

        Measured against the PEAK timing vector, not the compiled one. See
        `_peak_timing`.
        """
        out: list[int | None] = []
        peak = self._peak_timing(t)
        # The worst case for a trial-bound duration is the longest reward any
        # trial type can deliver -- the watchdog has to cover every binding.
        trial_bound = max((peak[r.reward_dur_idx] for r in t.trial_types
                           if r.reward_dur_idx < len(peak)), default=0)
        for n in t.nodes:
            if n.dur_idx == DUR_FROM_TRIAL:
                out.append(trial_bound)
            elif n.type in BOUNDED:
                out.append(peak[n.dur_idx] if n.dur_idx < len(peak) else None)
            elif n.type is NodeType.TERMINAL:
                out.append(0)
            else:
                out.append(None)
        return out


def lower(
    spec: TaskSpec,
    draft: GraphDraft,
    vocab: Vocabulary,
    channels: ChannelMap,
    bag: DiagnosticBag,
) -> StateTable:
    return Lowerer(spec, vocab, channels, bag).run(draft)
