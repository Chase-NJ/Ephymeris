"""Negative tests for the graph rules, on hand-built graphs.

These graphs are NOT reachable from any valid spec. That is the whole reason the
graph rules take a GraphView rather than a TaskSpec: a WAIT_ENTRY missing its
TIMEOUT edge is a TEMPLATE bug, and if the rules needed a spec to run, the checks
that matter most would be the ones that could never be tested.

Each test constructs the smallest graph that exhibits one defect, and asserts the
rule fires with the right code at the right node.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.context import GraphContext
from ephymeris_sidecar.taskgraph.graph import GraphView, NodeType, Trigger, ViewEdge
from ephymeris_sidecar.taskgraph.lint import Pass, load_all_rules, run_pass

load_all_rules()

T = NodeType
G = Trigger


def graph(types, edges, *, watch=None, entry=0, labels=None) -> GraphView:
    """Build a GraphView from terse tuples.

    edges: (src, dst, trigger[, guard[, channel]])
    """
    view_edges = []
    for i, e in enumerate(edges):
        src, dst, trig = e[0], e[1], e[2]
        guard = e[3] if len(e) > 3 else None
        channel = e[4] if len(e) > 4 else None
        view_edges.append(
            ViewEdge(index=i, src=src, dst=dst, trigger=trig, guard=guard, channel=channel)
        )
    n = len(types)
    return GraphView(
        types=tuple(types),
        watch_masks=tuple(tuple(w) for w in (watch or [()] * n)),
        edges=tuple(view_edges),
        entry=entry,
        labels=tuple(labels or [f"n{i}" for i in range(n)]),
    )


def codes(g: GraphView) -> list[str]:
    return [d.code for d in run_pass(Pass.GRAPH, GraphContext(graph=g, spec_id="hand_built"))]


def diags(g: GraphView, code: str):
    return [
        d
        for d in run_pass(Pass.GRAPH, GraphContext(graph=g, spec_id="hand_built"))
        if d.code == code
    ]


# --------------------------------------------------------------------------- #
# TG401 — trigger totality
# --------------------------------------------------------------------------- #


def test_TG401_wait_entry_without_timeout_is_a_hung_box():
    """The canonical hang. The animal never pokes, the window never closes, and the
    box sits there with an animal in it until someone walks past."""
    g = graph(
        [T.WAIT_ENTRY, T.TERMINAL],
        [(0, 1, G.ENTER, None, "left_well"), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
        watch=[("left_well",), ()],
    )
    found = diags(g, "TG401")
    assert len(found) == 1
    assert "TIMEOUT" in found[0].message
    assert found[0].location == "S00"


def test_TG401_enter_is_per_channel_not_per_state():
    """THE case the roadmap's one-line check misses.

    A response window watching two ports with ONE ENTER edge passes "has an outgoing
    edge for every trigger" and silently drops a port: the animal pokes right,
    nothing matches, and the trial waits out a window it can never exit correctly.
    """
    g = graph(
        [T.WAIT_ENTRY, T.TERMINAL],
        [
            (0, 1, G.ENTER, None, "left_well"),   # right_well has no edge
            (0, 1, G.TIMEOUT),
            (1, 0, G.ADVANCE),
            (1, 0, G.REPEAT),
        ],
        watch=[("left_well", "right_well"), ()],
    )
    found = diags(g, "TG401")
    assert len(found) == 1
    assert "right_well" in found[0].message
    assert "no ENTER edge" in found[0].message


def test_TG401_enter_edge_for_an_unwatched_channel():
    """The mirror image: an edge that can never fire because nothing polls it."""
    g = graph(
        [T.WAIT_ENTRY, T.TERMINAL],
        [
            (0, 1, G.ENTER, None, "left_well"),
            (0, 1, G.ENTER, None, "centre_well"),
            (0, 1, G.TIMEOUT),
            (1, 0, G.ADVANCE),
            (1, 0, G.REPEAT),
        ],
        watch=[("left_well",), ()],
    )
    found = diags(g, "TG401")
    assert len(found) == 1
    assert "centre_well" in found[0].message


def test_TG401_hold_needs_both_held_and_broken():
    g = graph(
        [T.HOLD, T.TERMINAL],
        [(0, 1, G.HELD), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
        watch=[("odor_port",), ()],
    )
    found = diags(g, "TG401")
    assert [d.message.count("BROKEN") for d in found] == [1]


def test_TG401_terminal_needs_advance_and_repeat():
    g = graph([T.TERMINAL], [(0, 0, G.ADVANCE)])
    assert any("REPEAT" in d.message for d in diags(g, "TG401"))


# --------------------------------------------------------------------------- #
# TG404 — dead edges
# --------------------------------------------------------------------------- #


def test_TG404_wait_exit_with_a_timeout_edge():
    """WAIT_EXIT has no timeout by design. An edge for one never fires, so the graph
    LOOKS total while the path it was meant to provide is absent -- which reads as
    handled and is therefore worse than an obviously missing edge."""
    g = graph(
        [T.WAIT_EXIT, T.TERMINAL],
        [(0, 1, G.EXIT), (0, 1, G.TIMEOUT), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
        watch=[("left_well",), ()],
    )
    found = diags(g, "TG404")
    assert len(found) == 1
    assert "TIMEOUT" in found[0].message and "WAIT_EXIT" in found[0].message


def test_TG404_pulse_with_a_broken_edge():
    g = graph(
        [T.PULSE, T.TERMINAL],
        [(0, 1, G.DONE), (0, 1, G.BROKEN), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
    )
    assert len(diags(g, "TG404")) == 1


# --------------------------------------------------------------------------- #
# TG405 — guard exhaustiveness and precedence
# --------------------------------------------------------------------------- #


def test_TG405_guarded_only_fan_out_has_no_default():
    """If the guard does not match, the state has no exit at all."""
    g = graph(
        [T.DELAY, T.TERMINAL, T.TERMINAL],
        [
            (0, 1, G.TIMEOUT, "ch == @target"),
            (1, 0, G.ADVANCE),
            (1, 0, G.REPEAT),
            (2, 0, G.ADVANCE),
            (2, 0, G.REPEAT),
        ],
    )
    found = diags(g, "TG405")
    assert len(found) == 1
    assert "no default" in found[0].message


def test_TG405_default_before_guard_silently_misscores():
    """The nastier failure: not a hang, a WRONG ANSWER.

    Edge resolution is first-match-wins, so an unguarded default emitted before a
    guarded edge always matches and the guarded path never fires. Every correct
    trial would be scored as whatever the default leads to, and nothing would look
    broken.
    """
    g = graph(
        [T.DELAY, T.TERMINAL, T.TERMINAL],
        [
            (0, 1, G.TIMEOUT),                    # default FIRST -- shadows the guard
            (0, 2, G.TIMEOUT, "ch == @target"),
            (1, 0, G.ADVANCE), (1, 0, G.REPEAT),
            (2, 0, G.ADVANCE), (2, 0, G.REPEAT),
        ],
    )
    found = diags(g, "TG405")
    assert len(found) == 1
    assert "not last" in found[0].message
    assert "mis-scores" in found[0].detail


def test_TG405_accepts_the_real_branch_shape():
    """D3's response branch must be legal: guarded first, default last."""
    g = graph(
        [T.DELAY, T.TERMINAL, T.TERMINAL],
        [
            (0, 1, G.TIMEOUT, "ch == @target"),
            (0, 2, G.TIMEOUT),                    # default last -- correct
            (1, 0, G.ADVANCE), (1, 0, G.REPEAT),
            (2, 0, G.ADVANCE), (2, 0, G.REPEAT),
        ],
    )
    assert "TG405" not in codes(g)


# --------------------------------------------------------------------------- #
# TG406 — watch masks
# --------------------------------------------------------------------------- #


def test_TG406_delay_that_watches_a_channel():
    g = graph(
        [T.DELAY, T.TERMINAL],
        [(0, 1, G.TIMEOUT), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
        watch=[("odor_port",), ()],
    )
    assert len(diags(g, "TG406")) == 1


def test_TG406_hold_that_watches_nothing():
    g = graph(
        [T.HOLD, T.TERMINAL],
        [(0, 1, G.HELD), (0, 1, G.BROKEN), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
        watch=[(), ()],
    )
    assert len(diags(g, "TG406")) == 1


# --------------------------------------------------------------------------- #
# TG402 / TG403 — reachability and termination
# --------------------------------------------------------------------------- #


def test_TG402_unreachable_state():
    g = graph(
        [T.DELAY, T.TERMINAL, T.DELAY],
        [(0, 1, G.TIMEOUT), (1, 0, G.ADVANCE), (1, 0, G.REPEAT), (2, 1, G.TIMEOUT)],
    )
    found = diags(g, "TG402")
    assert [d.location for d in found] == ["S02"]


def test_TG403_dead_end_with_no_outgoing_edges():
    """A state with no exits is not a cycle, so a cycle check would miss it -- and
    it hangs exactly as hard as a loop does."""
    g = graph(
        [T.DELAY, T.WAIT_EXIT, T.TERMINAL],
        [(0, 1, G.TIMEOUT), (2, 0, G.ADVANCE), (2, 0, G.REPEAT)],
        watch=[(), ("left_well",), ()],
    )
    found = diags(g, "TG403")
    assert len(found) == 1
    assert found[0].location == "S01"
    assert "no outgoing edges" in found[0].detail


def test_TG403_loop_that_never_reaches_a_terminal():
    """Two sampling states passing control back and forth. The message must print
    the actual cycle, because nobody authored these nodes and a bare node id is
    unactionable."""
    g = graph(
        [T.DELAY, T.HOLD, T.HOLD, T.TERMINAL],
        [
            (0, 1, G.TIMEOUT),
            (1, 2, G.HELD), (1, 2, G.BROKEN),
            (2, 1, G.HELD), (2, 1, G.BROKEN),
            (3, 0, G.ADVANCE), (3, 0, G.REPEAT),
        ],
        watch=[(), ("odor_port",), ("odor_port",), ()],
        labels=["arm", "present stimulus 2", "inter-stimulus gap", "correct"],
    )
    found = diags(g, "TG403")
    assert len(found) == 1
    assert "2 states form a loop" in found[0].message
    assert "present stimulus 2" in found[0].detail
    assert "No edge leaves this group" in found[0].detail


def test_TG403_tolerates_the_intentional_return_cycle():
    """Terminals wire back to entry. That is trial selection returning, not a trap,
    and a naive cycle check would flag the entire task."""
    g = graph(
        [T.DELAY, T.TERMINAL],
        [(0, 1, G.TIMEOUT), (1, 0, G.ADVANCE), (1, 0, G.REPEAT)],
    )
    assert "TG403" not in codes(g)


# --------------------------------------------------------------------------- #
# TG901 — informational
# --------------------------------------------------------------------------- #


def test_TG901_enumerates_watchdog_only_states():
    """Not an error and not a warning -- see the rule's docstring. The point is to
    hand Phase 4 the exact list of states only tgWatchdogExpired() can bound."""
    g = graph(
        [T.DELAY, T.WAIT_EXIT, T.TERMINAL],
        [(0, 1, G.TIMEOUT), (1, 2, G.EXIT), (2, 0, G.ADVANCE), (2, 0, G.REPEAT)],
        watch=[(), ("left_well",), ()],
    )
    found = diags(g, "TG901")
    assert [d.location for d in found] == ["S01"]
    assert found[0].severity.name == "INFO"


def test_a_well_formed_graph_produces_no_errors():
    """The floor: if this ever fails, every negative test above is suspect."""
    g = graph(
        [T.DELAY, T.WAIT_ENTRY, T.HOLD, T.TERMINAL],
        [
            (0, 1, G.TIMEOUT),
            (1, 2, G.ENTER, None, "odor_port"),
            (1, 3, G.TIMEOUT),
            (2, 3, G.HELD),
            (2, 3, G.BROKEN),
            (3, 0, G.ADVANCE),
            (3, 0, G.REPEAT),
        ],
        watch=[(), ("odor_port",), ("odor_port",), ()],
    )
    assert [c for c in codes(g) if not c.startswith("TG9")] == []
