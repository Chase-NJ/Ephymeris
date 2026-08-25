"""The five tasks the lab was running, as starting points.

Each was a separate `.ino` until the firmware was unified. They differed by one
substantive line apiece — which bare-START defaults they applied, and which pool
weight they set — so what they really were is five sets of NUMBERS over one task.
That is exactly what a preset is, and it is why deleting the sketches cost
nothing: every value below is transcribed from the sketch it replaces.

A PRESET IS NOT A TASK. It is instantiated into a definition the operator then
owns and edits; nothing here is ever flashed, and editing a preset in a later
build does not reach back into a task somebody already made. The alternative —
shipping tasks — would mean an app update silently retuning a running study.

`legacyNames` rides on the preset rather than being added afterward, because the
name a historical run recorded is a fact about THAT task: `Shape - R` belongs to
the go-right shaping preset and nowhere else. Attaching them all to one task
would make Analytics adopt a shaping run into a discrimination profile.

> [!CAUTION]
> **The channel names here are the shipped wiring's.** A rig that renamed
> `odor_line_1` gets a preset that will not validate — which is correct and
> visible (`TSK101` names the missing channel), rather than a preset that
> silently binds something else.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .model import StageRow, TaskDefinition, TrialTypeDef

#: The two trial types every shipped task presents: odor line 1 means go-right,
#: odor line 3 means go-left, both paid from reward line 1 of their own well.
#:
#: NO SUBSTANCE NAMES. These used to read "odor 1 (sandalwood)", which was a
#: claim about what is in a bottle on ONE bench -- and the whole point of the
#: trial table is that the next bench along has something else on that line. The
#: substance belongs to the rig's wiring, where an operator names the channel
#: and every screen reads it back; a preset that asserted it would be wrong for
#: everyone but the person who wrote it, and wrong silently.
#:
#: `label` NAMES THE CONTINGENCY, never the substance, and that line is the whole
#: distinction. "Go right" is a restatement of the row directly below it -- this
#: odor is answered at the right well -- and is true on every bench; "sandalwood"
#: is true on one. A name is required (TSK110), so leaving it empty would ship a
#: preset that arrives with an error against every row; these are a starting
#: point the operator is free to rename, and renaming one is a task edit.
_GO_RIGHT = TrialTypeDef(
    odor_channel="odor_line_1",
    onset_strobe="ODOR_1_ON",
    response_channel="right_well",
    reward_channel="fluid_2",
    label="Go right",
)
_GO_LEFT = TrialTypeDef(
    odor_channel="odor_line_3",
    onset_strobe="ODOR_3_ON",
    response_channel="left_well",
    reward_channel="fluid_0",
    label="Go left",
)

#: The two extra odors the shaping pool could draw from. Present because the
#: shaping sketches declared four slots; both shipped with weight 0, so a
#: preset that instantiates them presents neither until someone raises one.
#:
#: Their names carry the odor line because two conditions cannot share one name
#: (TSK111) -- and the line, unlike the bottle on it, is what this row binds.
_GO_RIGHT_2 = TrialTypeDef(
    odor_channel="odor_line_2",
    onset_strobe="ODOR_2_ON",
    response_channel="right_well",
    reward_channel="fluid_2",
    weight=0,
    label="Go right (odor 2)",
)
_GO_LEFT_2 = TrialTypeDef(
    odor_channel="odor_line_4",
    onset_strobe="ODOR_4_ON",
    response_channel="left_well",
    reward_channel="fluid_0",
    weight=0,
    label="Go left (odor 4)",
)

#: `applyShapingDefaults()`, transcribed. The values a shaping sketch applied on
#: a bare START, and the 20/25/50/100 schedule it walked.
_SHAPING_PARAMS: dict[str, Any] = {
    "polling_rate": 2,
    "lazy_rat_delay": 4000,
    "no_poke_hold_timeout": 5000,
    "lazy_escalation": False,  # shaping passed no policy, so it never escalated
}
_SHAPING_STAGES = [
    StageRow(0, 10, 10, 10000, 8000),
    StageRow(20, 100, 50, 10000, 8000),
    StageRow(25, 125, 250, 5000, 8000),
    StageRow(50, 250, 500, 2000, 4000),
    StageRow(100, 500, 500, 2000, 4000),
]

#: `applyEasedShapingDefaults()`: the same shape, more trials per step and a
#: longer runway before the holds bite.
_EASED_SHAPING_PARAMS: dict[str, Any] = {
    **_SHAPING_PARAMS,
    "lazy_rat_delay": 3000,   # a shorter penalty: re-engaging is what we want
    "no_poke_hold_timeout": 3000,
}
_EASED_SHAPING_STAGES = [
    StageRow(0, 10, 10, 15000, 12000),
    StageRow(40, 50, 25, 12000, 10000),
    StageRow(80, 125, 100, 8000, 8000),
    StageRow(140, 250, 250, 5000, 6000),
    StageRow(220, 500, 500, 2000, 4000),
]

#: `applyEasedDiscriminationDefaults()`. Row 4 IS the full task and matches the
#: unramped preset exactly — it used to set a 350 ms well hold against both its
#: own docblock and the 200 ms the real task uses, which made the eased sketch's
#: final stage stricter than the task it was easing into.
_EASED_DISC_STAGES = [
    StageRow(0, 10, 10, 10000, 8000),
    StageRow(15, 100, 50, 10000, 8000),
    StageRow(30, 200, 200, 5000, 6000),
    StageRow(50, 350, 350, 3000, 4000),
    StageRow(80, 500, 200, 2000, 4000),
]


def _replace_weight(trial: TrialTypeDef, weight: int) -> TrialTypeDef:
    """The same trial type at a different pool weight.

    A shaping preset declares all four slots and gives one of them the weight,
    exactly as the retired sketches did — the weights ARE the difference between
    shaping_GR and shaping_GL, and spelling that out is what makes the pair one
    task rather than two.
    """
    return replace(trial, weight=weight)


def _preset(
    preset_id: str,
    name: str,
    summary: str,
    definition: TaskDefinition,
) -> dict[str, Any]:
    return {
        "id": preset_id,
        "name": name,
        "summary": summary,
        "definition": definition,
    }


PRESETS: tuple[dict[str, Any], ...] = (
    _preset(
        "grgl_2odor",
        "GRGL — 2-odor discrimination",
        "The full task. Two odors, one per side, chosen live against the "
        "animal's recent bias. No ramp: it starts at full strictness.",
        TaskDefinition(
            id="grgl_2odor",
            name="GRGL 2-Odor",
            category="Discrimination",
            selection_mode="antibias",
            trials=[_GO_RIGHT, _GO_LEFT],
            stages=[StageRow(0, 500, 200, 2000, 4000)],
            params={},
            legacy_names=["GRGL_2-Odor"],
            notes="Transcribed from the retired GRGL_2-Odor sketch.",
        ),
    ),
    _preset(
        "grgl_2odor_eased",
        "GRGL — 2-odor, eased in",
        "The same task entered through a five-stage ramp, with the abstention "
        "penalty held flat until the last stage so an animal still being shaped "
        "is never escalated against.",
        TaskDefinition(
            id="grgl_2odor_eased",
            name="GRGL 2-Odor Eased",
            category="Discrimination",
            selection_mode="antibias",
            trials=[_GO_RIGHT, _GO_LEFT],
            stages=_EASED_DISC_STAGES,
            params={
                "lazy_escalation_stage": 4,
                "p_side_min": 0.05,
                "p_side_max": 0.95,
                "max_consecutive_side": 6,
            },
            legacy_names=["GRGL_2-Odor_EZ"],
            notes="Transcribed from the retired GRGL_2-Odor_EZ sketch.",
        ),
    ),
    _preset(
        "shaping_right",
        "Shaping — go right",
        "One side only, drawn from a weighted pool over a five-stage ramp. No "
        "anti-bias estimate and no correction budgets: every completed trial "
        "advances.",
        TaskDefinition(
            id="shaping_right",
            name="Shaping Right",
            category="Shaping",
            selection_mode="pool",
            trials=[
                _GO_RIGHT,                          # PW1 = 1
                _GO_RIGHT_2,                        # PW2 = 0
                _replace_weight(_GO_LEFT, 0),       # PW3 = 0
                _GO_LEFT_2,                         # PW4 = 0
            ],
            stages=_SHAPING_STAGES,
            params=_SHAPING_PARAMS,
            legacy_names=["shaping_GR", "Shape - R"],
            notes="Transcribed from the retired shaping_GR sketch.",
        ),
    ),
    _preset(
        "shaping_left",
        "Shaping — go left",
        "The go-left mirror of the shaping preset. The only thing that differs "
        "is which trial type carries the weight.",
        TaskDefinition(
            id="shaping_left",
            name="Shaping Left",
            category="Shaping",
            selection_mode="pool",
            trials=[
                _replace_weight(_GO_RIGHT, 0),
                _GO_RIGHT_2,
                _GO_LEFT,                           # PW3 = 1
                _GO_LEFT_2,
            ],
            stages=_SHAPING_STAGES,
            params=_SHAPING_PARAMS,
            legacy_names=["shaping_GL", "Shape - L"],
            notes="Transcribed from the retired shaping_GL sketch.",
        ),
    ),
    _preset(
        "shaping_eased",
        "Shaping — eased",
        "The shaping schedule stretched out and started softer, for an animal "
        "struggling with the standard ramp. Go-right by default; move the "
        "weight to shape the other side.",
        TaskDefinition(
            id="shaping_eased",
            name="Shaping Eased",
            category="Shaping",
            selection_mode="pool",
            trials=[
                _GO_RIGHT,
                _GO_RIGHT_2,
                _replace_weight(_GO_LEFT, 0),
                _GO_LEFT_2,
            ],
            stages=_EASED_SHAPING_STAGES,
            params=_EASED_SHAPING_PARAMS,
            legacy_names=["shaping_GR_EZ", "shaping_GL_EZ"],
            notes="Transcribed from the retired shaping_*_EZ sketches.",
        ),
    ),
)


def summaries() -> list[dict[str, Any]]:
    """The gallery listing — everything but the definitions themselves."""
    return [
        {"id": p["id"], "name": p["name"], "summary": p["summary"]}
        for p in PRESETS
    ]


def get(preset_id: str) -> dict[str, Any] | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def instantiate(preset_id: str, task_id: str, name: str | None = None) -> TaskDefinition:
    """A fresh, editable definition from a preset.

    The id and name are the caller's, not the preset's: two tasks from one
    preset is the normal case (a per-cohort copy with different reward volumes),
    and reusing the preset's id would make the second overwrite the first.
    """
    preset = get(preset_id)
    if preset is None:
        raise KeyError(preset_id)
    definition: TaskDefinition = preset["definition"]
    return replace(definition, id=task_id, name=name or definition.name)
