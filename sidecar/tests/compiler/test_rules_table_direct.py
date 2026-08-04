"""Capacity and wire-invariant rules, on hand-built tables.

TG501–TG504 guard against a COMPILER bug, not a spec bug: no YAML document can
produce a table with 200 states or a negative edge offset, because the compiler
would have to be wrong first. That is exactly why they exist -- they are the last
check before bytes reach a board, and the thing they are checking is the layer
everything else has already trusted.

So the tables here are constructed directly, the way a broken lowerer would have
produced them.
"""

from __future__ import annotations

from ephymeris_sidecar.taskgraph.context import TableContext
from ephymeris_sidecar.taskgraph.graph import NodeType, Trigger
from ephymeris_sidecar.taskgraph.lint import load_all_rules
from ephymeris_sidecar.taskgraph.lint.rules_capacity import (
    edge_offsets_not_monotonic,
    index_out_of_range,
    table_too_large,
    watch_mask_overflow,
)
from ephymeris_sidecar.taskgraph.table import Edge, Node, StateTable

load_all_rules()


def node(**kw) -> Node:
    base = dict(
        type=NodeType.DELAY, dur_idx=0, strobe=0xFFFF, watch_mask=0,
        action_idx=0, action_count=0, edge_idx=0,
    )
    base.update(kw)
    return Node(**base)


def table(**kw) -> StateTable:
    t = StateTable(spec_id="hand_built")
    t.timing = [0, 100]
    t.timing_ids = ["t_zero", "t_x"]
    for k, v in kw.items():
        setattr(t, k, v)
    return t


def ctx(t: StateTable) -> TableContext:
    return TableContext(table=t, spec_id="hand_built")


def test_TG501_rejects_a_table_over_the_measured_limit():
    """64 states is not a preference. It comes from a measured sweep on an
    ATmega2560, and the firmware's arrays are statically sized -- an over-large
    table has nowhere to go."""
    t = table(nodes=[node() for _ in range(65)])
    found = list(table_too_large(ctx(t)))
    assert len(found) == 1
    assert found[0].code == "TG501"
    assert "65 states, limit is 64" in found[0].message


def test_TG501_accepts_the_boundary():
    assert not list(table_too_large(ctx(table(nodes=[node() for _ in range(64)]))))


def test_TG502_rejects_a_duration_index_past_the_timing_vector():
    """The trial loop does no bounds checking -- it cannot afford to -- so this
    reads whatever happens to sit next in SRAM."""
    t = table(nodes=[node(dur_idx=9)])
    found = list(index_out_of_range(ctx(t)))
    assert [d.code for d in found] == ["TG502"]
    assert "outside 0..1" in found[0].message


def test_TG502_rejects_an_edge_targeting_a_state_that_does_not_exist():
    t = table(
        nodes=[node()],
        edges=[Edge(trigger=Trigger.TIMEOUT, guard=0, target=7, effect=0)],
    )
    assert any("does not exist" in d.message for d in index_out_of_range(ctx(t)))


def test_TG502_rejects_a_four_digit_strobe():
    """emitStrobe formats %03d and the host regex is ^\\d{1,3}\\t\\d+$, so a
    4-digit code is unparseable on the host and silently dropped."""
    t = table(nodes=[node(strobe=1234)])
    assert any("wire format" in d.message for d in index_out_of_range(ctx(t)))


def test_TG503_rejects_non_monotonic_edge_offsets():
    """THE most dangerous invariant in the table.

    TgNode stores only edgeIdx; the count is implied by the NEXT node's offset. If
    offsets go backwards, every node past the break executes edges belonging to
    some other state -- which is not a crash, it is a box quietly running a task
    nobody wrote.
    """
    t = table(
        nodes=[node(edge_idx=0), node(edge_idx=4), node(edge_idx=2)],
        edges=[Edge(trigger=Trigger.TIMEOUT, guard=0, target=0, effect=0) for _ in range(6)],
    )
    found = list(edge_offsets_not_monotonic(ctx(t)))
    assert [d.code for d in found] == ["TG503"]
    assert found[0].location == "S02"
    assert "another state's edges" in found[0].detail


def test_TG503_rejects_an_offset_past_the_edge_table():
    t = table(nodes=[node(edge_idx=0), node(edge_idx=9)], edges=[])
    assert any("past the" in d.message for d in edge_offsets_not_monotonic(ctx(t)))


def test_TG503_accepts_the_real_layout():
    t = table(
        nodes=[node(edge_idx=0), node(edge_idx=2), node(edge_idx=2), node(edge_idx=3)],
        edges=[Edge(trigger=Trigger.TIMEOUT, guard=0, target=0, effect=0) for _ in range(4)],
    )
    assert not list(edge_offsets_not_monotonic(ctx(t)))


def test_TG504_rejects_a_watch_mask_wider_than_a_byte():
    """task_spec.v1.json permits 8 response ports; the hardware allows 7, because
    the engagement channel takes a bit too."""
    t = table(nodes=[node(watch_mask=0x1FF)])
    found = list(watch_mask_overflow(ctx(t)))
    assert [d.code for d in found] == ["TG504"]


def test_TG504_accepts_a_full_byte():
    assert not list(watch_mask_overflow(ctx(table(nodes=[node(watch_mask=0xFF)]))))
