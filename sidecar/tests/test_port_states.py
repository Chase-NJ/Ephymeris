"""Per-port state machine — `ARCHITECTURE.md#port-state-machine`.

The table is transcribed from `ARCHITECTURE.md#transitions`, so these tests
assert the documented table rather than the implementation: every legal edge
is spelled out explicitly here, and everything else is required to be rejected.
"""

from __future__ import annotations

import itertools

import pytest

from ephymeris_sidecar.ports import states
from ephymeris_sidecar.ports.states import (
    TRANSITIONS,
    IllegalTransition,
    PortState,
    assert_leaves,
    assert_transition,
    can_transition,
)

S = PortState

#: The documented table (`ARCHITECTURE.md#transitions`), written out independently of `states.TRANSITIONS`.
LEGAL_EDGES = {
    (S.IDLE, S.PASSTHROUGH),
    (S.IDLE, S.FLASHING),
    (S.IDLE, S.RESETTING),
    (S.IDLE, S.IN_SESSION),
    (S.PASSTHROUGH, S.IDLE),
    (S.PASSTHROUGH, S.FLASHING),
    (S.PASSTHROUGH, S.RESETTING),
    (S.FLASHING, S.IDLE),
    (S.FLASHING, S.PASSTHROUGH),
    (S.RESETTING, S.IDLE),
    (S.RESETTING, S.PASSTHROUGH),
    (S.IN_SESSION, S.IDLE),
    (S.ERROR, S.IDLE),
    # "any state -> ERROR"
    *((state, S.ERROR) for state in S if state is not S.ERROR),
}


@pytest.mark.parametrize("edge", sorted(LEGAL_EDGES, key=lambda e: (e[0].value, e[1].value)))
def test_every_documented_edge_is_permitted(edge: tuple[PortState, PortState]) -> None:
    assert can_transition(*edge), f"{edge[0].value} -> {edge[1].value} should be legal"


@pytest.mark.parametrize(
    "edge",
    sorted(
        (e for e in itertools.product(S, S) if e[0] != e[1] and e not in LEGAL_EDGES),
        key=lambda e: (e[0].value, e[1].value),
    ),
)
def test_every_undocumented_edge_is_rejected(edge: tuple[PortState, PortState]) -> None:
    assert not can_transition(*edge), f"{edge[0].value} -> {edge[1].value} should be illegal"
    with pytest.raises(IllegalTransition):
        assert_transition(*edge)


def test_in_session_is_exclusive_with_every_other_operation() -> None:
    """`ARCHITECTURE.md#exclusivity` — nothing may flash, reset, or open passthrough mid-session."""
    for target in (S.PASSTHROUGH, S.FLASHING, S.RESETTING):
        assert not can_transition(S.IN_SESSION, target)


def test_a_session_can_only_start_from_idle() -> None:
    for origin in S:
        if origin is S.IDLE:
            continue
        assert not can_transition(origin, S.IN_SESSION)


def test_error_recovers_only_to_idle() -> None:
    assert TRANSITIONS[S.ERROR] == frozenset({S.IDLE})


def test_flashing_and_resetting_can_auto_resume_passthrough() -> None:
    """`ARCHITECTURE.md#exclusivity` — the auto-resume path back to PASSTHROUGH must exist."""
    assert can_transition(S.FLASHING, S.PASSTHROUGH)
    assert can_transition(S.RESETTING, S.PASSTHROUGH)


def test_every_state_has_a_table_entry() -> None:
    assert set(TRANSITIONS) == set(S)


# --- port verbs (`ARCHITECTURE.md#port-verbs`) -------------------------------

#: Each verb's from-set and where it goes. Every edge must be in the table:
#: the verbs narrow `TRANSITIONS`, never widen it.
VERBS = {
    "open_passthrough": (states.OPEN_FROM, S.PASSTHROUGH),
    "resume_passthrough": (states.RESUME_FROM, S.PASSTHROUGH),
    "close_passthrough": (states.CLOSE_FROM, S.IDLE),
    "finish_to_idle": (states.FINISH_FROM, S.IDLE),
    "acknowledge_error": (states.ACKNOWLEDGE_FROM, S.IDLE),
    "claim_session": (states.CLAIM_FROM, S.IN_SESSION),
    "release": (states.RELEASE_FROM, S.IDLE),
    "release_for(FLASHING)": (states.IDLE_OR_CONSOLE, S.FLASHING),
    "release_for(RESETTING)": (states.IDLE_OR_CONSOLE, S.RESETTING),
}


@pytest.mark.parametrize("verb", sorted(VERBS))
def test_every_verb_edge_is_in_the_table(verb: str) -> None:
    from_, to = VERBS[verb]
    for state in from_:
        assert can_transition(state, to), f"{verb}: {state.value} -> {to.value}"


def test_no_verb_but_the_acknowledgement_starts_from_error() -> None:
    assert [verb for verb, (from_, _to) in VERBS.items() if S.ERROR in from_] == [
        "acknowledge_error"
    ]


def test_a_baseline_take_never_includes_a_console() -> None:
    assert states.IDLE_ONLY < states.IDLE_OR_CONSOLE
    assert S.PASSTHROUGH not in states.IDLE_ONLY


def test_assert_leaves_checks_the_verb_and_then_the_table() -> None:
    assert_leaves(S.PASSTHROUGH, states.CLOSE_FROM, S.IDLE)
    with pytest.raises(IllegalTransition) as refused:
        assert_leaves(S.FLASHING, states.CLOSE_FROM, S.IDLE)
    assert (refused.value.current, refused.value.requested) == (S.FLASHING, S.IDLE)
    # A from-set wider than the table is still held to the table.
    with pytest.raises(IllegalTransition):
        assert_leaves(S.IN_SESSION, frozenset(S), S.FLASHING)
