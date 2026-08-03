"""Frozen dataclasses for a task spec.

A thin, typed mirror of schema/task_spec.v1.json. The schema is the authority on
what is *valid*; this is what the rest of the compiler reads, so that a typo in a
field name is an AttributeError at import rather than a KeyError three passes
later on a dict nobody validated.

Everything is frozen. The spec is the input artifact and its hash is session
provenance (D7); a pass that mutated it would make the recorded hash a lie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The six outcome classes an n-alternative task can produce, plus go/no-go's
#: false_alarm. Which SUBSET a spec must declare is a function of its topology and
#: is checked against the template's capabilities, not against this list.
OUTCOME_CLASSES = (
    "correct",
    "wrong",
    "omission",
    "hold_fail",
    "no_engage",
    "hold_break",
    "false_alarm",
)


@dataclass(frozen=True)
class Meta:
    label: str | None = None
    description: str | None = None
    #: Set when this spec must reproduce a firmware sketch bit-identically. Its
    #: presence changes the severity of several rules -- most importantly the
    #: null-strobe warning (D4) and the ANY_ENGAGEMENT escalation check -- because
    #: "matches runTrial()" and "is well designed" are different goals and this
    #: field says which one applies.
    reproduces_sketch: str | None = None
    derived_from: str | None = None


@dataclass(frozen=True)
class Topology:
    template: str
    n_sampling_stages: int
    response_mode: str
    response_ports: tuple[str, ...]
    template_version: int = 1
    retention_delay: bool = False
    commit_hold: bool = True
    cue_off_placement: str = "before_partner"


@dataclass(frozen=True)
class TimingEntry:
    id: str
    ms: int
    wire_key: str | None = None
    note: str | None = None
    #: Position in the compiled timing vector. Assigned during binding, because
    #: ORDER IS LOAD-BEARING: the index is what firmware holds, and a stage ramp
    #: rewrites entries in place by index.
    index: int = -1


@dataclass(frozen=True)
class Stimulus:
    id: str
    emitter: str
    on_code: str | None
    note: str | None = None


@dataclass(frozen=True)
class PortBinding:
    name: str
    channel: str
    enter_code: str | None = None
    error_code: str | None = None
    break_code: str | None = None
    exit_code: str | None = None
    reward_line: str | None = None
    reward_duration: str | None = None
    reward_code: str | None = None
    reward_stop_code: str | None = None
    note: str | None = None

    @property
    def rewards(self) -> bool:
        """Whether this port can deliver reward.

        The template emits the PULSE and consumption WAIT_EXIT only for ports that
        do. Absence of a reward_line removes those states -- absence, never a
        suppressing flag (D9)."""
        return self.reward_line is not None


@dataclass(frozen=True)
class TrialType:
    id: str
    stages: tuple[str, ...]
    target: str | None = None
    weight: int = 1
    note: str | None = None

    @property
    def is_withhold(self) -> bool:
        """target: null IS the withhold declaration. No correct port exists, so the
        `port == @target` guard can never be satisfied and every ENTER falls to the
        false-alarm branch."""
        return self.target is None


@dataclass(frozen=True)
class Outcome:
    name: str
    terminal: str
    delay: str
    reward: str | None = None
    strobe: str | None = None
    trigger: str | None = None
    note: str | None = None
    #: Distinguishes "strobe: null was written" from "strobe was never mentioned".
    #: D4 makes the first deliberate and the second an oversight, and the linter
    #: must be able to tell them apart.
    strobe_declared: bool = False


@dataclass(frozen=True)
class ContextRow:
    at_trial: int
    targets: dict[str, str | None]
    context: str | None = None


@dataclass(frozen=True)
class Contingency:
    ports: dict[str, PortBinding]
    trial_types: tuple[TrialType, ...]
    outcome_map: dict[str, Outcome]
    stimuli: tuple[Stimulus, ...] = ()
    context_schedule: tuple[ContextRow, ...] = ()


@dataclass(frozen=True)
class Selection:
    mode: str
    block_size: int | None = None
    bias_window: int | None = None
    debias_strength: float | None = None
    p_min: float | None = None
    p_max: float | None = None
    max_run: int | None = None


@dataclass(frozen=True)
class PenaltyEscalation:
    applies_to: str
    clears_on: str
    step_ms: int | None = None
    ceiling_ms: int | None = None
    arm_after_stage: int | None = None


@dataclass(frozen=True)
class StageRow:
    at_trial: int
    set: dict[str, int]


@dataclass(frozen=True)
class Policy:
    """Layer 4. An absent block means defined default behaviour, never an error --
    mirroring firmware's TrialPolicy, where a nullptr means legacy semantics."""

    selection: Selection | None = None
    correction: dict[str, int] = field(default_factory=dict)
    penalty_escalation: PenaltyEscalation | None = None
    stage_schedule: tuple[StageRow, ...] = ()
    n_trials: int | None = None
    seed: Any = "host"


@dataclass(frozen=True)
class TaskSpec:
    spec_version: int
    spec_id: str
    vocab_version: int
    topology: Topology
    timing: tuple[TimingEntry, ...]
    contingency: Contingency
    policy: Policy
    meta: Meta = field(default_factory=Meta)
    source_path: str | None = None
    #: SHA-256 over the canonical spec, truncated. Recorded alongside
    #: profile_hash and params_hash so a session is exactly reconstructable (D7).
    spec_hash: str = ""

    def timing_by_id(self) -> dict[str, TimingEntry]:
        return {t.id: t for t in self.timing}

    def timing_index(self, timing_id: str) -> int:
        return self.timing_by_id()[timing_id].index

    def trial_type(self, tt_id: str) -> TrialType | None:
        return next((t for t in self.contingency.trial_types if t.id == tt_id), None)

    def stimulus(self, stim_id: str) -> Stimulus | None:
        return next((s for s in self.contingency.stimuli if s.id == stim_id), None)
