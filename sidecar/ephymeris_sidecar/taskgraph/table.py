"""The compiled state table — the artifact the firmware walks.

Mirrors the records in Arduino/libraries/TaskInterpreter/TaskTable.h field for
field. That header and this module are the contract between the compiler and the
interpreter: if a field moves in one, it must move in the other or every uploaded
table is silently misread. They live in one repo so that is a single commit.

Resolution happens HERE and nowhere else. A template emits symbolic drafts
(StrobeRef("LIGHTS_OFF"), TimingRef("t_zero")); lowering turns them into indices
and codes. Keeping that in one place is what stops each future template version
from growing its own copy of the lookup rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ephymeris_sidecar.taskgraph.graph import NodeType, Trigger

#: Sentinels, mirroring TaskTable.h. Out of band on purpose: TG_NO_STROBE is above
#: the 999 wire ceiling, so it can never collide with a real code -- unlike the
#: 32767 sentinel in firmware's StageStep, which sits one step from a legal
#: duration.
NO_STROBE = 0xFFFF
NO_TARGET = 0xFF
NO_NODE = 0xFF

#: A duration resolved per trial rather than from the timing vector -- the reward
#: PULSE, whose width comes from the chosen port's reward_duration via the
#: trial-type row's rewardDurIdx.
#:
#: Out of band because TG_MAX_TIMING is 64: 0xFF can never be a real index. The
#: first version of the lowerer collapsed runtime-bound durations to index 0,
#: which is t_zero by convention -- so every reward pulse compiled to a 0 ms valve
#: opening that delivered nothing. TG505 caught it, which is the linter earning
#: its keep against the compiler rather than against a spec.
DUR_FROM_TRIAL = 0xFF

# --------------------------------------------------------------------------- #
# Runtime bindings
# --------------------------------------------------------------------------- #
#
# Seven states emit a strobe that depends on the TRIAL, not on the graph: which
# stimulus was presented, which port was poked, which line rewarded. The listing
# shows those as `@ports[$ch].enter_code`, but that string never reaches the board
# -- so without an encoding the firmware sees NO_STROBE and emits nothing.
#
# The selector rides in the strobe field itself. Real codes are capped at 999 by
# the wire format, so anything at or above TG_BIND_BASE is unambiguously a
# binding rather than a code, and no new field is needed.
GUARD_NONE = 0
GUARD_IS_TARGET = 1
GUARD_CORRECTION = 2

EFFECT_NONE = 0
EFFECT_ADVANCE = 1
EFFECT_REPEAT = 2

BIND_BASE = 0xFF00

# The sampling stage is known at COMPILE time -- the unroll is static -- so the
# selector carries it and the interpreter needs no stage counter. A counter would
# be state the graph already encodes, and the one thing it could do is drift.
BIND_STIM_ON_0 = 0          # stimulus bound to sampling stage 0
BIND_STIM_ON_1 = 1
BIND_STIM_ON_2 = 2
BIND_STIM_ON_3 = 3
BIND_PORT_ENTER = 4         # indexed by the channel that fired ($ch)
BIND_PORT_ERROR = 5
BIND_PORT_BREAK = 6
BIND_PORT_EXIT = 7
BIND_TARGET_REWARD = 8      # indexed by the trial's target port
BIND_TARGET_REWARD_STOP = 9
BIND_TARGET_EXIT = 10

#: Expression -> selector. `$ch` bindings resolve against the port in play;
#: `@target` bindings against the trial's correct port. On the correct path those
#: coincide, but keeping them distinct is what makes the wrong-port path -- where
#: they do NOT coincide -- resolve correctly.
BINDINGS = {
    "@ports.enter_code": BIND_PORT_ENTER,
    "@ports.error_code": BIND_PORT_ERROR,
    "@ports.break_code": BIND_PORT_BREAK,
    "@ports.exit_code": BIND_PORT_EXIT,
    "@target.reward_code": BIND_TARGET_REWARD,
    "@target.reward_stop_code": BIND_TARGET_REWARD_STOP,
    "@target.exit_code": BIND_TARGET_EXIT,
}

#: Actuator channels can be trial-bound too. Pins are <= 53, so the high byte is
#: free for the same trick.
CH_BIND_BASE = 0xF0
CH_BIND_STIM_EMITTER_0 = 0xF0   # the emitter for a specific sampling stage
CH_BIND_TARGET_REWARD_LINE = 0xF4
#: "every stimulus emitter". Used on the abort paths, where the right thing is to
#: clear whatever is on without needing to know which stage got there.
CH_BIND_ALL_EMITTERS = 0xF5


def bind_code(selector: int) -> int:
    return BIND_BASE | selector


def is_bound(strobe: int) -> bool:
    return strobe >= BIND_BASE and strobe != NO_STROBE


def selector_of(strobe: int) -> int:
    return strobe & 0xFF


@dataclass(frozen=True)
class Node:
    """8 bytes on the wire. See TaskTable.h TgNode."""

    type: NodeType
    dur_idx: int
    strobe: int          # uint16 -- five real codes exceed a byte
    watch_mask: int
    action_idx: int
    action_count: int
    edge_idx: int
    # Not on the wire: kept for the listing and for diagnostics.
    label: str = ""
    symbol: str = ""
    band: int = 0
    strobe_name: str = ""
    silent_by_design: bool = False
    #: The symbolic watch list, for the listing. A runtime-bound watch (@target)
    #: contributes no static mask bit -- the interpreter ORs in the bound channel
    #: -- so without this the listing would show "watches nothing" for a state
    #: whose whole job is watching the chosen port.
    watch_text: tuple[str, ...] = ()


@dataclass(frozen=True)
class Edge:
    """4 bytes. See TaskTable.h TgEdge."""

    trigger: Trigger
    guard: int
    target: int
    effect: int
    guard_text: str = ""
    effect_text: str = ""
    channel: str | None = None


@dataclass(frozen=True)
class Action:
    channel: int
    op: int              # 0 = clear, 1 = set
    channel_name: str = ""


@dataclass(frozen=True)
class Port:
    """Per-port strobe codes and reward wiring. 12 bytes.

    This is what a `@ports[$ch]` binding resolves against. Without it the board
    knows a poke happened but not which code to emit for it.
    """

    channel: int
    enter_code: int
    error_code: int
    break_code: int
    exit_code: int
    reward_code: int
    reward_stop_code: int
    reward_line: int
    reward_dur_idx: int
    name: str = ""


@dataclass(frozen=True)
class Stimulus:
    """Emitter channel and identity code. 4 bytes."""

    emitter: int
    on_code: int
    name: str = ""


@dataclass(frozen=True)
class TrialTypeRow:
    stimulus: tuple[int, ...]
    target: int
    weight: int
    reward_line: int
    reward_dur_idx: int
    label: str = ""


@dataclass(frozen=True)
class StageRowOut:
    at_trial: int
    count: int
    first_idx: int


@dataclass(frozen=True)
class TimingSet:
    idx: int
    ms: int


@dataclass
class StateTable:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    timing: list[int] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    trial_types: list[TrialTypeRow] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    #: Pin per watch-mask BIT, and the port index that bit belongs to (or
    #: NO_TARGET for the engagement channel, which is not a response port). The
    #: mask indexes watchable channels, so the interpreter needs this to turn a
    #: set bit back into something it can digitalRead().
    watch_pins: list[int] = field(default_factory=list)
    watch_ports: list[int] = field(default_factory=list)
    stimuli: list[Stimulus] = field(default_factory=list)
    stage_rows: list[StageRowOut] = field(default_factory=list)
    timing_sets: list[TimingSet] = field(default_factory=list)

    # Provenance. Travels with the table so a recorded session is exactly
    # reconstructable (docs/decisions.md D7).
    spec_id: str = ""
    spec_hash: str = ""
    spec_version: int = 1
    vocab_version: int = 1
    template: str = ""
    template_version: int = 1
    template_hash: str = ""

    #: WHICH WIRING PRODUCED THESE BYTES. Recorded beside `spec_hash`, never
    #: folded into it (D22): a spec is identified by what it says, and it says
    #: channel names. So re-pinning a box changes every table and moves no
    #: spec_hash -- correct, and invisible without this pair, because the
    #: listing prints channel NAMES and the listing is what specs.diff reviews.
    pinout_id: str = ""
    pinout_hash: str = ""

    # Names, for the listing only.
    timing_ids: list[str] = field(default_factory=list)

    #: Per-node worst-case dwell in ms, or None where only the runtime watchdog
    #: can bound it. Handed to Phase 4 so tgWatchdogExpired() has a number to use
    #: rather than a guess -- see docs/spikes/avr-ram.md.
    max_dwell: list[int | None] = field(default_factory=list)

    def unbounded_nodes(self) -> list[int]:
        return [i for i, d in enumerate(self.max_dwell) if d is None]

    def size_bytes(self) -> int:
        """Exactly the arithmetic in docs/spikes/avr-ram.md, plus the timing_sets
        term that document's formula omits (the probe never allocated them)."""
        return (
            8 * len(self.nodes)
            + 4 * len(self.edges)
            + 2 * len(self.timing)
            + 2 * len(self.actions)
            + 8 * len(self.trial_types)
            + 4 * len(self.stage_rows)
            + 4 * len(self.timing_sets)
            + 16 * len(self.ports)
            + 4 * len(self.stimuli)
        )
