"""Per-port state machine — `dashboard.md` §5.

The table is transcribed from the §3.2 diagram, so these tests assert the
diagram rather than the implementation: every legal edge is spelled out
explicitly here, and everything else is required to be rejected.
"""

from __future__ import annotations

import itertools

import pytest

from ephymeris_sidecar.ports.states import (
    TRANSITIONS,
    IllegalTransition,
    PortState,
    assert_transition,
    can_transition,
)

S = PortState

#: The §3.2 diagram, written out independently of `states.TRANSITIONS`.
LEGAL_EDGES = {
    (S.IDLE, S.PASSTHROUGH),
    (S.IDLE, S.FLASHING),
    (S.IDLE, S.UPLOADING),
    (S.IDLE, S.RESETTING),
    (S.IDLE, S.IN_SESSION),
    (S.PASSTHROUGH, S.IDLE),
    (S.PASSTHROUGH, S.FLASHING),
    (S.PASSTHROUGH, S.UPLOADING),
    (S.PASSTHROUGH, S.RESETTING),
    (S.FLASHING, S.IDLE),
    (S.FLASHING, S.PASSTHROUGH),
    # UPLOADING mirrors FLASHING exactly, auto-resume included (`specs.md`).
    (S.UPLOADING, S.IDLE),
    (S.UPLOADING, S.PASSTHROUGH),
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
    """§3.3 — nothing may flash, reset, upload, or open passthrough mid-session."""
    for target in (S.PASSTHROUGH, S.FLASHING, S.UPLOADING, S.RESETTING):
        assert not can_transition(S.IN_SESSION, target)


def test_a_table_upload_cannot_reach_a_session() -> None:
    """A table transfer during a run is nonsense in both directions —
    and the door from a spec to a session stays closed structurally, not
    just by UI (`specs.md`)."""
    assert not can_transition(S.UPLOADING, S.IN_SESSION)
    assert not can_transition(S.IN_SESSION, S.UPLOADING)


def test_a_session_can_only_start_from_idle() -> None:
    for origin in S:
        if origin is S.IDLE:
            continue
        assert not can_transition(origin, S.IN_SESSION)


def test_error_recovers_only_to_idle() -> None:
    assert TRANSITIONS[S.ERROR] == frozenset({S.IDLE})


def test_flashing_and_resetting_can_auto_resume_passthrough() -> None:
    """§3.3 — the auto-resume path back to PASSTHROUGH must exist."""
    assert can_transition(S.FLASHING, S.PASSTHROUGH)
    assert can_transition(S.RESETTING, S.PASSTHROUGH)


def test_every_state_has_a_table_entry() -> None:
    assert set(TRANSITIONS) == set(S)
