"""What a task profile IS, as data.

A profile is the operator's answer to four questions, and nothing else:

    which trials does the animal see      -> trials[]
    how does the next one get chosen      -> selection_mode
    does the task ease in, and over how   -> stages[]
    what are the numbers                  -> params{}

Everything else is derived. The pins come from the rig's wiring, the strobe
codes from the vocabulary, the field labels from `fields.py`, and the firmware
from `generate.py`. A profile stores no pin number and no strobe code — it names
CHANNELS and CODE NAMES, which is what makes "odor line 3 means go-left on this
rig" an edit to one document rather than to the firmware.

A `TrialTypeDef` names an `odor_channel` rather than an odor *index* for the same
reason the pinout does: the pin order is not monotonic past line 6, so anything
computing one from the other is wrong. The generator resolves the name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

SelectionMode = Literal["antibias", "pool"]

#: Lower snake case, bounded. It becomes a folder name and part of a C
#: identifier, and it is typed by hand.
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: The sketch folder name and the `.ino` must match (arduino-cli's rule), and
#: the name is what a session file records in `sketch`. Kept to the same shape
#: as an id so the two can never disagree about what is legal.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,47}$")


class TaskDefinitionError(ValueError):
    """The document is not a task definition. Not the same as an invalid one."""


@dataclass(frozen=True)
class TrialTypeDef:
    """One row of the trial table.

    `response_channel` and `reward_channel` are None together, and only on a
    NO-GO type: withholding has no correct port and pays nothing. Splitting them
    would make "rewards a port it does not name" representable.
    """

    odor_channel: str
    onset_strobe: str
    is_go: bool = True
    response_channel: str | None = None
    reward_channel: str | None = None
    #: Pool mode only. Ignored under anti-bias selection, which weights nothing.
    weight: int = 1
    #: The operator's own words, for the trial-table editor. Never generated
    #: from the channels: "orange -> left" is what they call it, and a
    #: derived label would overwrite that on every edit.
    label: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "odorChannel": self.odor_channel,
            "onsetStrobe": self.onset_strobe,
            "isGo": self.is_go,
            "responseChannel": self.response_channel,
            "rewardChannel": self.reward_channel,
            "weight": self.weight,
            "label": self.label,
        }

    @staticmethod
    def from_json(raw: Any) -> "TrialTypeDef":
        if not isinstance(raw, dict):
            raise TaskDefinitionError("each trial type must be an object")
        return TrialTypeDef(
            odor_channel=_req_str(raw, "odorChannel"),
            onset_strobe=_req_str(raw, "onsetStrobe"),
            is_go=bool(raw.get("isGo", True)),
            response_channel=_opt_str(raw.get("responseChannel")),
            reward_channel=_opt_str(raw.get("rewardChannel")),
            weight=_int(raw.get("weight", 1), "weight"),
            label=str(raw.get("label", "")),
        )


@dataclass(frozen=True)
class StageRow:
    """One row of the shaping ramp.

    `trials` on row 0 is not read by the firmware — row 0 is live from trial 0
    by construction — and is stored anyway so the editor shows a consistent
    table and nothing downstream has to know the exception.
    """

    trials: int = 0
    odor_poke_hold: int = 500
    fluid_well_hold: int = 200
    fluid_well_poll: int = 2000
    odor_port_timeout: int = 4000

    def to_json(self) -> dict[str, Any]:
        return {
            "trials": self.trials,
            "odorPokeHold": self.odor_poke_hold,
            "fluidWellHold": self.fluid_well_hold,
            "fluidWellPoll": self.fluid_well_poll,
            "odorPortTimeout": self.odor_port_timeout,
        }

    @staticmethod
    def from_json(raw: Any) -> "StageRow":
        if not isinstance(raw, dict):
            raise TaskDefinitionError("each stage row must be an object")
        return StageRow(
            trials=_int(raw.get("trials", 0), "trials"),
            odor_poke_hold=_int(raw.get("odorPokeHold", 500), "odorPokeHold"),
            fluid_well_hold=_int(raw.get("fluidWellHold", 200), "fluidWellHold"),
            fluid_well_poll=_int(raw.get("fluidWellPoll", 2000), "fluidWellPoll"),
            odor_port_timeout=_int(raw.get("odorPortTimeout", 4000), "odorPortTimeout"),
        )


@dataclass(frozen=True)
class TaskDefinition:
    id: str
    name: str
    category: str = "Tasks"
    selection_mode: SelectionMode = "antibias"
    trials: list[TrialTypeDef] = field(default_factory=list)
    #: At least one row. An empty ramp is not "no ramp" — it is a task with no
    #: holds at all, which the firmware cannot express.
    stages: list[StageRow] = field(default_factory=lambda: [StageRow()])
    #: `metadataKey -> value`, and ONLY where it diverges from `fields.py`'s
    #: default. Storing the full merged set would mean a catalogue change could
    #: not reach a saved profile, which is the same reasoning `taskDefaults`
    #: rests on (`tasks.md` §6.1).
    params: dict[str, Any] = field(default_factory=dict)
    #: Names the lab's archives record for runs this profile now covers. Without
    #: them those runs stop decoding in Analytics — silently, because a missing
    #: profile is treated as data.
    legacy_names: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def trial_count(self) -> int:
        return len(self.trials)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "selectionMode": self.selection_mode,
            "trials": [t.to_json() for t in self.trials],
            "stages": [s.to_json() for s in self.stages],
            "params": dict(self.params),
            "legacyNames": list(self.legacy_names),
            "notes": self.notes,
        }

    @staticmethod
    def from_json(raw: Any) -> "TaskDefinition":
        """Parse, refusing only what is not a definition at all.

        A definition that is well-formed and describes an impossible task —
        an odor channel this rig lacks, a reward line serving the wrong well —
        parses fine and is reported by `validate.py`. That split is the same one
        the rig document draws, and for the same reason: the editor must be able
        to hold a half-finished document.
        """
        if not isinstance(raw, dict):
            raise TaskDefinitionError("a task definition must be an object")

        task_id = _req_str(raw, "id")
        if not ID_RE.match(task_id):
            raise TaskDefinitionError(
                f"{task_id!r} is not a usable id — lower case, digits and "
                "underscores, starting with a letter, up to 48 characters"
            )
        name = _req_str(raw, "name")
        if not NAME_RE.match(name):
            raise TaskDefinitionError(
                f"{name!r} is not a usable name — it becomes a sketch folder, so "
                "it must start alphanumeric and hold only letters, digits, "
                "spaces, dots, dashes and underscores"
            )

        mode = raw.get("selectionMode", "antibias")
        if mode not in ("antibias", "pool"):
            raise TaskDefinitionError(
                f"selectionMode must be 'antibias' or 'pool', not {mode!r}"
            )

        trials_raw = raw.get("trials", [])
        stages_raw = raw.get("stages", [])
        if not isinstance(trials_raw, list) or not isinstance(stages_raw, list):
            raise TaskDefinitionError("trials and stages must be lists")

        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise TaskDefinitionError("params must be an object")

        legacy = raw.get("legacyNames", [])
        if not isinstance(legacy, list) or any(not isinstance(n, str) for n in legacy):
            raise TaskDefinitionError("legacyNames must be a list of strings")

        stages = [StageRow.from_json(s) for s in stages_raw] or [StageRow()]
        return TaskDefinition(
            id=task_id,
            name=name,
            category=str(raw.get("category") or "Tasks"),
            selection_mode=mode,
            trials=[TrialTypeDef.from_json(t) for t in trials_raw],
            stages=stages,
            params=dict(params),
            legacy_names=[n for n in legacy],
            notes=str(raw.get("notes", "")),
        )


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


def _req_str(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TaskDefinitionError(f"{key} is required and must be a non-empty string")
    return value.strip()


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TaskDefinitionError("channel names must be strings")
    return value.strip() or None


def _int(value: Any, what: str) -> int:
    # bool before int: `True` is an int in Python and would silently become 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TaskDefinitionError(f"{what} must be a whole number, not {value!r}")
    return value
