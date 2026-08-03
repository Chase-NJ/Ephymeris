"""The four-epoch template, v2.

Every trial is four bands in order -- engagement, stimulus sampling, response,
outcome -- assembled from the six primitives.

-----------------------------------------------------------------------------
WHAT CHANGED FROM v1, AND WHY IT COULD

v1 reproduces what the boxes emit TODAY, quirks included, because firmware was
immovable and the equivalence gate demanded a byte-identical match. It is frozen
and still compiles -- tests/fixtures/grgl_2odor_asbuilt.yaml pins it, and that is
what the 1.5-million-event corpus replay validates against.

Firmware is now developed alongside this compiler, so THE MODEL IS AUTHORITATIVE
AND FIRMWARE CONFORMS (D21). Two accommodations existed only because it could
not, and both are gone:

1.  CUE-OFF ORDER IS NOW CONSISTENT. v1 needed a `cue_off_placement` knob because
    firmware emits LIGHTS_OFF *before* its partner on the three abort paths and
    *after* it on the success path. Here the behavioural strobe always comes
    first and LIGHTS_OFF follows: the behavioural event is what happened, the
    actuator change is a consequence of it. The knob, its designer control and a
    documented divergence all disappear.

2.  AN OMISSION EMITS RESP_OMIT (262). v1 emitted nothing when the response
    window expired, so an omission was inferable only from a 20-second gap before
    END_INCORRECT_ITI -- which is itself reached by three different outcomes,
    making the class recoverable only from the *preceding* strobe. Now all three
    are distinguishable at the moment they occur.

WHAT DID NOT CHANGE. The paired response strobes stay: a wrong poke emits
WATER_POKE_L and then WATER_POKE_ERROR_L, because "a poke happened" is common to
the correct and the wrong path and is worth having on its own.

The three divergences from docs/task_topology.html that v1 records -- the response
branch node, the inter-stimulus gap as a HOLD, and cue-off as its own node -- all
still hold. They were never firmware accommodations; they were the diagram being
wrong.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass

from taskgraph.graph import Band, EpochBuilder, GraphDraft, NodeType, Trigger
from taskgraph.spec import TaskSpec

NAME = "four_epoch"
VERSION = 2


@dataclass(frozen=True)
class Capabilities:
    """What this template produces for a given topology.

    A FUNCTION, not a static JSON file, because the answer depends on the knobs:
    which outcome classes exist is a consequence of response_mode, commit_hold and
    n_sampling_stages together. Expressing that as data would need conditionals and
    a loop -- i.e. a mini-language, which is exactly the trap D14 rejects. The
    linter imports this and compares against what the spec declares.
    """

    outcome_classes: frozenset[str]
    required_timing: tuple[str, ...]
    knobs: tuple[str, ...]


def _sample_hold_id(i: int, n: int) -> str:
    """Stage-indexed timing ids appear only when there is more than one stage.

    A one-stage task keeps the unsuffixed `t_sample_hold`, which is what every
    existing spec declares; a chain gets `t_sample_hold_0`, `_1`, ... so each stage
    is independently rampable. seq2_retention.yaml documents this expectation.
    """
    return "t_sample_hold" if n == 1 else f"t_sample_hold_{i}"


def _gap_id(i: int) -> str:
    return f"t_interstim_gap_{i}"


def capabilities(topology) -> Capabilities:
    n = topology.n_sampling_stages
    gonogo = topology.response_mode == "go_nogo"

    classes = {"correct", "no_engage"}
    if gonogo:
        classes.add("false_alarm")
    else:
        classes |= {"wrong", "omission", "hold_fail"}
    # hold_break needs at least one hold to break: the commitment hold, a sampling
    # hold, or an inter-stimulus gap.
    if topology.commit_hold or n > 0:
        classes.add("hold_break")

    timing = ["t_zero", "t_arm", "t_engage_win", "t_poll_interval"]
    if topology.commit_hold:
        timing.append("t_commit_hold")
    for i in range(n):
        timing.append(_sample_hold_id(i, n))
        if i < n - 1:
            timing.append(_gap_id(i))
    if topology.retention_delay:
        timing.append("t_retention")
    timing.append("t_withhold_win" if gonogo else "t_resp_win")
    if not gonogo:
        timing.append("t_resp_hold")

    return Capabilities(
        outcome_classes=frozenset(classes),
        required_timing=tuple(dict.fromkeys(timing)),
        knobs=(
            "n_sampling_stages",
            "retention_delay",
            "response_mode",
            "response_ports",
            "commit_hold",
        ),
    )


def emit(spec: TaskSpec, engagement: str, cue: str, vacuum: str) -> GraphDraft:
    """Build the node and edge lists.

    `engagement`, `cue` and `vacuum` are resolved BY KIND from the channel registry
    and passed in, because no spec names them -- they are structural facts of the
    epoch model rather than per-task choices (D15).
    """
    t = spec.topology
    om = spec.contingency.outcome_map
    n = t.n_sampling_stages
    gonogo = t.response_mode == "go_nogo"
    last = n - 1

    b = EpochBuilder(
        f"templates/{NAME}/v{VERSION}.py",
        {
            "n_sampling_stages": n,
            "retention_delay": t.retention_delay,
            "response_mode": t.response_mode,
            "commit_hold": t.commit_hold,
        },
    )

    # Which terminal each outcome class routes to, and the delay node that precedes
    # it. Emitted from outcome_map so that scoring is an edge effect and the
    # interpreter never branches on response_mode (D9).
    _entry: dict[str, str] = {}

    def outcome_chain(cls: str, from_node: str, trigger: Trigger, *, guard=None, channel=None,
                      strobe_override: str | None = None,
                      cue_off: tuple = ()) -> None:
        """Wire `from_node` into this outcome and on to its terminal.

        When `cue_off` is given, the branch aborts a trial whose cue is still lit,
        and the chain becomes three nodes:

            mark (reason, t_zero) -> cue off (LIGHTS_OFF, t_zero, clears) -> penalty

        THE REASON COMES FIRST. v1 emitted LIGHTS_OFF before it here and after it
        on the success path, which is why v1 needed a knob to say which. The
        behavioural event is what happened; the actuator change is a consequence,
        so it follows -- everywhere.

        The actuators clear on the node that carries LIGHTS_OFF rather than on the
        mark, keeping each strobe next to the hardware change it reports. Both are
        zero-duration, so they land in the same millisecond either way.
        """
        o = om[cls]
        delay_id = f"out_{cls}"
        if cls not in _entry:
            strobe = strobe_override if strobe_override is not None else o.strobe
            if cue_off:
                mark_id, cue_id = f"mark_{cls}", f"cueoff_{cls}"
                b.node(mark_id, NodeType.DELAY, duration="t_zero", strobe=strobe,
                       label=cls.replace("_", " "))
                b.node(cue_id, NodeType.DELAY, duration="t_zero", strobe="LIGHTS_OFF",
                       actions=cue_off, label="cue off")
                b.node(delay_id, NodeType.DELAY, duration=o.delay, strobe=None,
                       label=cls.replace("_", " ") + " penalty", silent_by_design=True)
                b.edge(mark_id, cue_id, Trigger.TIMEOUT)
                b.edge(cue_id, delay_id, Trigger.TIMEOUT)
                _entry[cls] = mark_id
            else:
                b.node(delay_id, NodeType.DELAY, duration=o.delay, strobe=strobe,
                       label=cls.replace("_", " "),
                       silent_by_design=o.strobe_declared and o.strobe is None)
                _entry[cls] = delay_id
            b.edge(delay_id, _score(o.terminal), Trigger.TIMEOUT, effect=f"score:{cls}")
        b.edge(from_node, _entry[cls], trigger, guard=guard, channel=channel)

    _made: dict[str, str] = {}

    def _sink(kind: str) -> str:
        """A trial ends by ADVANCING or by REPEATING, and those are the only two
        terminals there are.

        NOTHING MAY FOLLOW A TERMINAL. Termination analysis severs terminal
        out-edges before it runs -- they return to trial selection rather than
        continuing the trial -- so a node placed after one is unreachable by
        construction. That is what forced the scoring strobe off the terminal and
        onto its own node below.
        """
        if kind not in _made:
            node_id = f"term_{kind}"
            b.node(
                node_id,
                NodeType.TERMINAL,
                strobe="INVALID_TRIAL" if kind == "repeat" else None,
                label="TRIAL_REPEAT" if kind == "repeat" else "TRIAL_ADVANCE",
                silent_by_design=(kind == "advance"),
            )
            b.edge(node_id, "arm", Trigger.ADVANCE)
            b.edge(node_id, "arm", Trigger.REPEAT)
            _made[kind] = node_id
        return _made[kind]

    def _score(terminal: str) -> str:
        """The zero-duration node carrying the trial's SCORING strobe.

        Separate from the terminal because firmware emits END_INCORRECT_ITI and
        then, only if the trial repeats, INVALID_TRIAL. Two strobes in that order
        means two nodes in that order, and the second has to be the terminal --
        so the first cannot be.

        THIS IS WHY, CONCRETELY. The first version of this template made
        END_INCORRECT_ITI and INVALID_TRIAL alternative terminal strobes, which
        cannot produce one after the other. Replaying real recorded sessions
        against the graph rejected all 52 that had ever run with a correction
        budget -- every one of them, and no others. Found before any firmware
        existed, from data that was already on disk. See docs/decisions.md D20.
        """
        strobe = {
            "TRIAL_CORRECT": "END_CORRECT_ITI",
            "TRIAL_INCORRECT": "END_INCORRECT_ITI",
            "TRIAL_INVALID": None,
        }[terminal]
        node_id = f"score_{terminal.split('_')[1].lower()}"
        if node_id in _made:
            return _made[node_id]

        if strobe is None:
            # An aborted trial has no score of its own: the reason was already
            # reported by the penalty state, and "it did not advance" is reported
            # by the repeat terminal. Route straight there, and memoise the SINK --
            # memoising the unused node id would hand callers a node that was
            # never created.
            _made[node_id] = _sink("repeat")
            return _made[node_id]

        _made[node_id] = node_id
        b.node(node_id, NodeType.DELAY, duration="t_zero", strobe=strobe,
               label=terminal.replace("TRIAL_", "").lower() + " — scored")
        if terminal == "TRIAL_CORRECT":
            # A completed correct trial always advances. Modelling a repeat here
            # would let the graph accept END_CORRECT_ITI followed by INVALID_TRIAL,
            # which no firmware produces.
            #
            # The effect is NOT optional. Scoring is an edge effect (D9), so an
            # edge without one advances nothing -- and a correct trial that does
            # not advance the counter is a session that never ends.
            b.edge(node_id, _sink("advance"), Trigger.TIMEOUT, effect="advance")
        else:
            # An error repeats while its side still has correction budget, and
            # advances once that is spent. Guarded edge first, default last.
            b.edge(node_id, _sink("repeat"), Trigger.TIMEOUT,
                   guard="correction budget", effect="repeat")
            b.edge(node_id, _sink("advance"), Trigger.TIMEOUT, effect="advance")
        return node_id

    # ---------------------------------------------------------------- #
    # Band 1 — engagement
    # ---------------------------------------------------------------- #
    b.band(Band.ENGAGEMENT)

    # Actuators that need lead time are driven here so stimulus onset later is
    # latency-free. No strobe: the trial is not offered yet.
    b.node(
        "arm",
        NodeType.DELAY,
        duration="t_arm",
        actions=(b.set_("@stim[0].emitter"),) if n else (),
        label="arm & pre-load",
    )

    b.node(
        "engage_win",
        NodeType.WAIT_ENTRY,
        duration="t_engage_win",
        strobe="LIGHTS_ON",
        watch=(engagement,),
        actions=(b.set_(cue),),
        label="engagement window",
    )
    b.edge("arm", "engage_win", Trigger.TIMEOUT)

    first_sample = "commit" if t.commit_hold else ("sample_0" if n else "release")
    b.edge("engage_win", first_sample, Trigger.ENTER, channel=engagement)

    # Abstention: the window expired with no entry.
    outcome_chain(
        "no_engage", "engage_win", Trigger.TIMEOUT,
        cue_off=(b.clear(cue),) + ((b.clear("@stim[0].emitter"),) if n else ()),
    )

    # A broken hold, from anywhere in engagement or sampling. One chain serves
    # every site, exactly as firmware shares one ODOR_UNPOKE_EARLY code -- which
    # hold broke is recoverable from the PRECEDING strobe. The chain is built by
    # whichever site edges into it first; outcome_chain memoises on the class.

    if t.commit_hold:
        # Separates an incidental beam-break from a committed initiation. Only
        # after this clears is any stimulus delivered, so a broken hold costs no
        # stimulus presentation.
        b.node(
            "commit",
            NodeType.HOLD,
            duration="t_commit_hold",
            strobe="ODOR_POKE",
            watch=(engagement,),
            label="commitment hold",
        )
        b.edge("commit", "sample_0" if n else "release", Trigger.HELD)
        outcome_chain("hold_break", "commit", Trigger.BROKEN,
                      cue_off=(b.clear(cue), b.clear(vacuum))
                      + ((b.clear("@stim[$stage].emitter"),) if n else ()))

    # ---------------------------------------------------------------- #
    # Band 2 — stimulus sampling
    # ---------------------------------------------------------------- #
    b.band(Band.SAMPLING)

    for i in range(n):
        # The one state whose entry code identifies WHAT was presented, which is
        # why the strobe is a per-trial binding rather than a fixed field.
        b.node(
            f"sample_{i}",
            NodeType.HOLD,
            duration=_sample_hold_id(i, n),
            strobe=f"@stim[{i}].on_code",
            watch=(engagement,),
            actions=(b.set_(vacuum),),
            label=f"present stimulus {i + 1}" if n > 1 else "present stimulus",
        )
        outcome_chain("hold_break", f"sample_{i}", Trigger.BROKEN,
                      cue_off=(b.clear(cue), b.clear(vacuum),
                               b.clear("@stim[$stage].emitter")))

        if i < last:
            # DIVERGENCE 2: a HOLD, not a DELAY. Withdrawal during the gap must
            # abort, or stimulus i+1 is delivered to an empty port.
            b.node(
                f"gap_{i}",
                NodeType.HOLD,
                duration=_gap_id(i),
                strobe="INTERSTIM_GAP_ON",
                watch=(engagement,),
                actions=(b.clear(f"@stim[{i}].emitter"), b.set_(f"@stim[{i + 1}].emitter")),
                label="inter-stimulus gap",
            )
            b.edge(f"sample_{i}", f"gap_{i}", Trigger.HELD)
            b.edge(f"gap_{i}", f"sample_{i + 1}", Trigger.HELD)
            outcome_chain("hold_break", f"gap_{i}", Trigger.BROKEN,
                          cue_off=(b.clear(cue), b.clear(vacuum),
                                   b.clear("@stim[$stage].emitter")))
        else:
            b.edge(f"sample_{i}", "release", Trigger.HELD)

    # Stimuli cleared, then wait -- WITHOUT a timeout -- for withdrawal.
    # Withdrawal is the boundary between sampling and responding, and this node is
    # one of the two whose dwell only the runtime watchdog can bound.
    b.node(
        "release",
        NodeType.WAIT_EXIT,
        strobe="ODOR_OFF",
        watch=(engagement,),
        actions=(b.clear(vacuum),) + ((b.clear(f"@stim[{last}].emitter"),) if n else ()),
        label="sampling release",
    )

    # ---------------------------------------------------------------- #
    # Band 3 — response
    # ---------------------------------------------------------------- #
    b.band(Band.RESPONSE)

    # Withdrawal, then cue-off — ALWAYS this order. See the header.
    b.node("unpoke", NodeType.DELAY, duration="t_zero", strobe="ODOR_UNPOKE",
           label="withdrawal")
    b.node("resp_cue_off", NodeType.DELAY, duration="t_zero", strobe="LIGHTS_OFF",
           actions=(b.clear(cue),), label="cue off")
    b.edge("release", "unpoke", Trigger.EXIT)
    b.edge("unpoke", "resp_cue_off", Trigger.TIMEOUT)
    after_cue = "resp_cue_off"

    if t.retention_delay:
        b.node("retain", NodeType.DELAY, duration="t_retention",
               strobe="RETENTION_ON", label="retention delay")
        b.edge(after_cue, "retain", Trigger.TIMEOUT)
        after_cue = "retain"

    resp_ports = list(t.response_ports)
    b.node(
        "resp_win",
        NodeType.WAIT_ENTRY,
        duration="t_withhold_win" if gonogo else "t_resp_win",
        watch=tuple(resp_ports),
        label="withhold window" if gonogo else "response window",
    )
    b.edge(after_cue, "resp_win", Trigger.TIMEOUT)

    # DIVERGENCE 1: the branch node. Its entry strobe is the per-channel enter
    # code, emitted before correctness is known; the guard lives on its edges.
    # ONE ENTER EDGE PER WATCHED CHANNEL -- a bijection, not merely "has an ENTER
    # edge", because a single edge for two ports silently drops one.
    b.node(
        "resp_branch",
        NodeType.DELAY,
        duration="t_zero",
        strobe="@ports[$ch].enter_code",
        label="response registered",
    )
    for port in resp_ports:
        b.edge("resp_win", "resp_branch", Trigger.ENTER, channel=port)

    if gonogo:
        # The inversion, and it is one edge: TIMEOUT scores CORRECT. No special
        # case anywhere -- the interpreter walks edges and applies effects.
        outcome_chain("correct", "resp_win", Trigger.TIMEOUT)
        outcome_chain("false_alarm", "resp_branch", Trigger.TIMEOUT)
    else:
        outcome_chain("omission", "resp_win", Trigger.TIMEOUT)

        # Confirms the choice was deliberate. No entry strobe: resp_branch already
        # emitted the poke code.
        b.node(
            "resp_hold",
            NodeType.HOLD,
            duration="t_resp_hold",
            watch=("@target",),
            label="response hold",
        )
        b.edge("resp_branch", "resp_hold", Trigger.TIMEOUT, guard="ch == @target")
        # The unguarded default MUST come last: tgResolveEdge is first-match-wins,
        # so a default emitted first would make the guard unreachable.
        outcome_chain("wrong", "resp_branch", Trigger.TIMEOUT,
                      strobe_override="@ports[$ch].error_code")
        outcome_chain("hold_fail", "resp_hold", Trigger.BROKEN,
                      strobe_override="@ports[$ch].break_code")

        # ------------------------------------------------------------ #
        # Band 4 — outcome
        # ------------------------------------------------------------ #
        b.band(Band.OUTCOME)

        correct = om["correct"]
        if correct.reward:
            # Pulse width IS the delivered magnitude. Which line opens and for how
            # long comes from the outcome map, so reward size is a per-response
            # binding rather than a property of the state.
            b.node(
                "reward",
                NodeType.PULSE,
                duration="@target.reward_duration",
                strobe="@target.reward_code",
                actions=(b.set_("@target.reward_line"),),
                label="reward delivery",
            )
            b.edge("resp_hold", "reward", Trigger.HELD)
            # The actuator close and its strobe are colocated here, which is
            # tidier than firmware's bracketing and costs nothing.
            b.node(
                "consume",
                NodeType.WAIT_EXIT,
                strobe="@target.reward_stop_code",
                watch=("@target",),
                actions=(b.clear("@target.reward_line"),),
                label="consumption",
            )
            b.edge("reward", "consume", Trigger.DONE)
            outcome_chain("correct", "consume", Trigger.EXIT)
        else:
            outcome_chain("correct", "resp_hold", Trigger.HELD)

    return b.draft
