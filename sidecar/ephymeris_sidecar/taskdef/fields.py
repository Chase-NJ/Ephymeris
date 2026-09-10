"""The parameter surface a task profile can tune, declared once.

This is the presentation half of `BehaviorBox.h`'s `TASK_PARAM_LIST`: the same
wire keys, plus the label, unit, range and prose a form needs to render them.
The firmware owns which keys the `START` grammar accepts; this owns what an
operator is shown when setting one.

WHY IT LIVES HERE AND NOT IN SEVEN `task.json` FILES. It used to be
hand-mirrored into every sketch's profile — forty-odd rows, copied, so retuning
one sketch's help text left six others saying something else. Generating every
profile from one catalogue is the whole point of the task-profile system: two
profiles differ in their VALUES and their trial table, never in what a parameter
means.

> [!CAUTION]
> **This is a cross-repo mirror and nothing enforces it at runtime.** A key here
> that the firmware does not parse is accepted, sent, and silently ignored — the
> session runs on the compiled-in value with nothing reporting a problem. The
> reverse (a firmware key nothing declares) is merely unreachable.
> `tests/test_taskdef_fields.py` pins this catalogue against the shipped
> `GRGL/task.json`, which is the closest thing to a check that exists.

The three count-dependent families — the ramp rows, the pool weights, and the
per-condition reward volumes — are NOT here. A profile's stage count and
trial-type count decide how many of each exist, so `generate.py` emits them.
"""

from __future__ import annotations

from typing import Any

#: Group order on the Task screen, and in the generated profile. It follows the
#: trial rather than the struct: what happens first is declared first. The
#: frontend's `GROUP_ORDER` mirrors it — the stage groups are appended there.
GROUP_ORDER: tuple[str, ...] = (
    "Session",
    "Trial pool",
    "Trial timing",
    "Holds & windows",
    "Correction trials",
    "Abstention penalty",
    "Reward volume",
    "Anti-bias selection",
)


def _f(
    metadata_key: str,
    wire_key: str,
    label: str,
    type_: str,
    default: Any,
    group: str,
    help_: str,
    *,
    unit: str | None = None,
    minimum: Any = None,
    maximum: Any = None,
    step: Any = None,
    advanced: bool = False,
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "metadataKey": metadata_key,
        "wireKey": wire_key,
        "label": label,
        "type": type_,
        "default": default,
        "group": group,
    }
    if unit is not None:
        field["unit"] = unit
    if minimum is not None:
        field["min"] = minimum
    if maximum is not None:
        field["max"] = maximum
    if step is not None:
        field["step"] = step
    field["help"] = help_
    if advanced:
        field["advanced"] = True
    return field


#: Every tunable that exists exactly once, whatever the profile's shape. Ordered
#: by group, and by the order a form should read within one.
SCALAR_FIELDS: tuple[dict[str, Any], ...] = (
    # --- Session ---------------------------------------------------------- #
    _f("num_trials", "NT", "Session trial cap", "int", 1000, "Session",
       "The session ends after this many completed trials.",
       unit="trials", minimum=1, maximum=1000, step=10),
    # --- Trial timing ------------------------------------------------------ #
    _f("error_delay", "ERR", "Error timeout", "int", 20000, "Trial timing",
       "Timeout served after a wrong well or no response.",
       unit="ms", minimum=0, maximum=120000, step=500),
    _f("standard_iti", "ITI", "Correct-trial ITI", "int", 4000, "Trial timing",
       "Intertrial interval after a correct response.",
       unit="ms", minimum=0, maximum=120000, step=500),
    _f("no_poke_hold_timeout", "NPH", "Hold-failure timeout", "int", 10000, "Trial timing",
       "Timeout served when the rat pokes but fails to hold.",
       unit="ms", minimum=0, maximum=120000, step=500),
    _f("nogo_well_poll", "NWP", "No-go withhold window", "int", 2000, "Trial timing",
       "How long a response must be withheld on a no-go trial.",
       unit="ms", minimum=0, maximum=60000, step=250),
    _f("priming_delay", "PRM", "Odor priming delay", "int", 1000, "Trial timing",
       "Odor is primed this long before the trial light comes on.",
       unit="ms", minimum=0, maximum=10000, step=100),
    _f("polling_rate", "POL", "IR polling interval", "int", 5, "Trial timing",
       "How often the beam sensors are read. Lower is finer-grained and busier.",
       unit="ms", minimum=1, maximum=50, step=1, advanced=True),
    # --- Correction trials ------------------------------------------------- #
    _f("correction_left", "CL", "Left correction budget", "int", 0, "Correction trials",
       "Leading correction trials on LEFT-correct trials: an error repeats the "
       "same side until the budget is spent.",
       unit="trials", minimum=0, maximum=500, step=1),
    _f("correction_right", "CR", "Right correction budget", "int", 0, "Correction trials",
       "Leading correction trials on RIGHT-correct trials: an error repeats the "
       "same side until the budget is spent.",
       unit="trials", minimum=0, maximum=500, step=1),
    # --- Abstention penalty ------------------------------------------------ #
    _f("lazy_rat_delay", "LZD", "Failure-to-initiate penalty", "int", 6000, "Abstention penalty",
       "Base timeout when the rat never pokes within the odor-port window.",
       unit="ms", minimum=0, maximum=120000, step=500),
    _f("lazy_escalation", "LAZY", "Escalating lazy penalty", "bool", True, "Abstention penalty",
       "Grow the penalty with each consecutive abstention."),
    _f("lazy_escalate_step", "LZS", "Escalation step", "int", 6000, "Abstention penalty",
       "Added per consecutive abstention while escalation is on.",
       unit="ms", minimum=0, maximum=60000, step=500, advanced=True),
    _f("lazy_delay_max", "LZM", "Escalation ceiling", "int", 30000, "Abstention penalty",
       "Upper bound on the escalated penalty.",
       unit="ms", minimum=0, maximum=300000, step=1000, advanced=True),
    #: `max` is rewritten per profile to the last stage index — see
    #: `generate.py`. A ceiling of 4 on a three-stage task would offer two rows
    #: that cannot engage, and the firmware clamps it back silently.
    _f("lazy_escalation_stage", "LZG", "Escalation starts at stage", "int", 0,
       "Abstention penalty",
       "Escalation stays off until this stage is reached, so an animal still "
       "being eased in is never escalated against.",
       minimum=0, maximum=4, step=1),
    # --- Anti-bias selection ----------------------------------------------- #
    _f("bias_window", "BW", "Bias window", "int", 20, "Anti-bias selection",
       "Sliding window of recent expressed choices the estimate is drawn from.",
       unit="trials", minimum=1, maximum=32, step=1),
    _f("max_consecutive_side", "MCS", "Max same-side run", "int", 10, "Anti-bias selection",
       "Hard cap on consecutive identical correct sides.",
       unit="trials", minimum=1, maximum=50, step=1),
    _f("debias_strength", "DBS", "Debias strength", "float", 0.5, "Anti-bias selection",
       "How hard selection pushes against the rat's recent bias.",
       minimum=0.0, maximum=1.0, step=0.05, advanced=True),
    _f("p_side_min", "PMN", "P(side) floor", "float", 0.02, "Anti-bias selection",
       "Selection never goes fully deterministic, which would itself be a cue.",
       minimum=0.0, maximum=0.5, step=0.01, advanced=True),
    _f("p_side_max", "PMX", "P(side) ceiling", "float", 0.98, "Anti-bias selection",
       "Selection never goes fully deterministic, which would itself be a cue.",
       minimum=0.5, maximum=1.0, step=0.01, advanced=True),
    # --- Trial pool -------------------------------------------------------- #
    #: Declared even on an anti-bias profile. The firmware parses it either way,
    #: and hiding it would make switching selection mode a re-declaration rather
    #: than a toggle. The help text says when it does nothing.
    _f("block_size", "BS", "Pool block size", "int", 30, "Trial pool",
       "Weights are enforced exactly within each block, then the block is "
       "shuffled. Ignored while anti-bias selection is on.",
       unit="trials", minimum=1, maximum=200, step=5, advanced=True),
)

#: The four ramped values, in `StageStep` order. Each becomes one field per
#: stage row, keyed `S<n>P` and so on. Row 0's keys carry the plain names
#: (`odor_poke_hold`) because a one-row profile is the common case and
#: `odor_poke_hold_0` would be noise; later rows are suffixed.
RAMPED_FIELDS: tuple[dict[str, Any], ...] = (
    _f("odor_poke_hold", "P", "Odor poke hold", "int", 500, "Holds & windows",
       "Hold required before odor delivery, and again while sampling.",
       unit="ms", minimum=0, maximum=5000, step=10),
    _f("fluid_well_hold", "H", "Fluid well hold", "int", 200, "Holds & windows",
       "Hold required at the correct well before reward.",
       unit="ms", minimum=0, maximum=5000, step=10),
    _f("fluid_well_poll", "W", "Response window", "int", 2000, "Holds & windows",
       "Window to respond after successful odor sampling.",
       unit="ms", minimum=0, maximum=60000, step=250),
    _f("odor_port_timeout", "O", "Odor port window", "int", 4000, "Holds & windows",
       "Window to poke the odor port after the trial light comes on.",
       unit="ms", minimum=0, maximum=60000, step=250),
)

#: The trial count at which a ramp row engages. Row 0's is never emitted: it is
#: live from trial 0 by construction, and `liveStage()` never reads it.
STAGE_TRIALS_FIELD = _f(
    "stage_trials", "T", "Engages at", "int", 0, "Stage",
    "Completed-trial count at which this row takes over.",
    unit="trials", minimum=0, maximum=32000, step=5,
)

#: Keyed RW1..RW<n>, one per declared GO trial type — the reward volume for
#: that condition. It used to be FL1..FL4, one per fluid line, which forced two
#: conditions paying from one line to pay the same volume.
REWARD_WIRE_KEY = "RW"

#: Keyed PW1..PW<n>, one per declared trial type.
POOL_WIRE_KEY = "PW"

#: Reserved by the protocol, claimable by no profile (`tasks.md` §6.4).
RESERVED_WIRE_KEYS = frozenset({"SEED"})


def scalar_defaults() -> dict[str, Any]:
    """`metadataKey -> default` for the fields that exist on every profile."""
    return {f["metadataKey"]: f["default"] for f in SCALAR_FIELDS}


def by_metadata_key() -> dict[str, dict[str, Any]]:
    return {f["metadataKey"]: f for f in SCALAR_FIELDS}
