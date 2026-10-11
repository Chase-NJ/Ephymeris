"""Per-port state machine — `ARCHITECTURE.md#port-state-machine`.

Each of the six ports has its own independent state machine, and a port can
only be in one state at a time. That single-owner invariant is the core of the
whole hardware layer, because a serial port can only have one owner.

The transition table here is the authority. `ARCHITECTURE.md#port-state-machine` is explicit that enforcement
lives in the sidecar and that the GUI disabling buttons is a UX nicety, never
the source of truth — so every state change goes through `assert_transition`.
"""

from __future__ import annotations

from enum import Enum


class PortState(str, Enum):
    #: Port not open. No owner. A board may or may not be physically connected.
    IDLE = "IDLE"
    #: Port open, raw bidirectional streaming to the GUI. No parsing, no storage.
    PASSTHROUGH = "PASSTHROUGH"
    #: compile + upload in progress; the port belongs to the upload process.
    FLASHING = "FLASHING"
    #: Brief transitional state while the DTR toggle runs.
    RESETTING = "RESETTING"
    #: Owned by the behaviour session runner. Strict strobe-protocol parsing.
    IN_SESSION = "IN_SESSION"
    #: Open failed, board vanished, or an operation failed. Needs acknowledgement.
    ERROR = "ERROR"


#: Legal transitions, transcribed from `ARCHITECTURE.md#transitions`.
#:
#: Note what is deliberately absent: nothing enters `IN_SESSION` except from
#: `IDLE`, and `IN_SESSION` leads only to `IDLE` or `ERROR` — it is exclusive
#: with every other operation (`ARCHITECTURE.md#exclusivity`). `FLASHING`/`RESETTING` may return to
#: `PASSTHROUGH` rather than `IDLE`, which is the auto-resume (`ARCHITECTURE.md#exclusivity`).
TRANSITIONS: dict[PortState, frozenset[PortState]] = {
    PortState.IDLE: frozenset(
        {
            PortState.PASSTHROUGH,
            PortState.FLASHING,
            PortState.RESETTING,
            PortState.IN_SESSION,
            PortState.ERROR,
        }
    ),
    PortState.PASSTHROUGH: frozenset(
        {
            PortState.IDLE,
            # Both auto-release the port before taking ownership (`ARCHITECTURE.md#exclusivity`).
            PortState.FLASHING,
            PortState.RESETTING,
            PortState.ERROR,
        }
    ),
    PortState.FLASHING: frozenset(
        {PortState.IDLE, PortState.PASSTHROUGH, PortState.ERROR}
    ),
    PortState.RESETTING: frozenset(
        {PortState.IDLE, PortState.PASSTHROUGH, PortState.ERROR}
    ),
    PortState.IN_SESSION: frozenset({PortState.IDLE, PortState.ERROR}),
    PortState.ERROR: frozenset({PortState.IDLE}),
}


#: The states each port verb leaves (`ARCHITECTURE.md#port-verbs`). `TRANSITIONS`
#: is every move that is ever legal; it cannot say who is asking, and a move it
#: allows can still be the wrong caller's. `FLASHING → IDLE` is how a flash
#: ends, not something a console close may do, and `ERROR → IDLE` belongs to the
#: acknowledgement alone. Every verb checks both: its own set, then the table.
OPEN_FROM = frozenset({PortState.IDLE})
CLOSE_FROM = frozenset({PortState.PASSTHROUGH})
#: How a flash or reset lands: in `IDLE`, or back in the console it took.
FINISH_FROM = frozenset({PortState.FLASHING, PortState.RESETTING})
RESUME_FROM = FINISH_FROM
ACKNOWLEDGE_FROM = frozenset({PortState.ERROR})
CLAIM_FROM = frozenset({PortState.IDLE})
RELEASE_FROM = frozenset({PortState.IN_SESSION})
#: What a flash or reset may take (`release_for`). A background job, the
#: utility baseline's restore, takes only a port nobody holds; one a person
#: asked for (a session flash, a Debug flash, a reset) may also take a console,
#: which it releases first (`ARCHITECTURE.md#exclusivity`).
IDLE_ONLY = frozenset({PortState.IDLE})
IDLE_OR_CONSOLE = frozenset({PortState.IDLE, PortState.PASSTHROUGH})


class IllegalTransition(Exception):
    """Raised when a caller attempts a transition the table, or the verb, forbids."""

    def __init__(self, current: PortState, requested: PortState) -> None:
        super().__init__(f"cannot move from {current.value} to {requested.value}")
        self.current = current
        self.requested = requested


def can_transition(current: PortState, requested: PortState) -> bool:
    return requested in TRANSITIONS[current]


def assert_transition(current: PortState, requested: PortState) -> None:
    if not can_transition(current, requested):
        raise IllegalTransition(current, requested)


def assert_leaves(
    current: PortState, from_: frozenset[PortState], requested: PortState
) -> None:
    """A verb that leaves only `from_` asks to move `current` to `requested`.
    Raises `IllegalTransition` unless both the verb and the table allow it."""
    if current not in from_:
        raise IllegalTransition(current, requested)
    assert_transition(current, requested)
