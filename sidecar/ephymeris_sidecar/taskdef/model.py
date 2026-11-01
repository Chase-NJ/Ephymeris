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

SelectionMode = Literal["antibias", "pool", "weighted"]

#: Lower snake case, bounded. It becomes a folder name and part of a C
#: identifier, and it is typed by hand.
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")

#: The sketch folder name and the `.ino` must match (arduino-cli's rule), and
#: the name is what a session file records in `sketch`. Kept to the same shape
#: as an id so the two can never disagree about what is legal.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,47}$")


#: Characters no folder name may hold on Windows, where the lab machines run,
#: or that make it a path: separators, a drive's colon, and the rest of
#: Windows' list. Control characters are refused separately.
_NOT_IN_A_FOLDER_NAME = frozenset('<>:"/\\|?*')

#: Device names Windows reserves, with or without an extension, any case.
_WINDOWS_RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(\..*)?$", re.IGNORECASE)


def folder_name_problem(value: str) -> str | None:
    """Why `value` cannot be one folder name on both Windows and macOS, or None.

    A task's category and name each become a folder under `<data_dir>/tasks/`
    that every save deletes and rewrites, so either one being a path -- `..`,
    a separator, a drive or UNC prefix -- would delete and write outside the
    library. A trailing dot or space is dropped by Windows, so "Tracer." and
    "Tracer" would be one folder there; a reserved device name is no folder
    at all. Anything else is the operator's free text."""
    if not value.strip():
        return "it is empty"
    if value in (".", ".."):
        return "it is a relative path, not a folder name"
    bad = sorted({c for c in value if c in _NOT_IN_A_FOLDER_NAME or ord(c) < 32})
    if bad:
        return f"it holds {' '.join(repr(c) for c in bad)}, which a folder name cannot"
    if value[-1] in ". ":
        return "it ends in a dot or a space, which Windows drops from a folder name"
    if _WINDOWS_RESERVED.match(value):
        return "Windows reserves it for a device"
    if len(value) > 64:
        return "it is over 64 characters"
    return None


def folder_key(name: str) -> str:
    """`name` as Windows compares folder names: case-folded, with trailing
    dots and spaces dropped. Two tasks whose names share a key share a folder."""
    return name.rstrip(". ").casefold()


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
    #: Pool and weighted modes. Ignored under plain anti-bias selection, which
    #: weights nothing; under weighted selection it is this type's share
    #: WITHIN its side, which is how a newly introduced odor is shown more
    #: often than a learned one.
    weight: int = 1
    #: The operator's own words, for the trial-table editor. Never generated
    #: from the channels: "orange -> left" is what they call it, and a
    #: derived label would overwrite that on every edit.
    label: str = ""
    #: Solenoid open time on a correct answer, in ms — the reward volume. On
    #: the ROW rather than in `params` for the same reason `weight` is: it is a
    #: property of this condition, so two types paying from one fluid line can
    #: pay differently, and deleting the row takes its volume with it. The
    #: generator compiles it into `TrialType` as the default and declares wire
    #: key RW<slot+1> so a run can override it per box. Meaningless on a no-go.
    reward_time: int = 100

    def to_json(self) -> dict[str, Any]:
        return {
            "odorChannel": self.odor_channel,
            "onsetStrobe": self.onset_strobe,
            "isGo": self.is_go,
            "responseChannel": self.response_channel,
            "rewardChannel": self.reward_channel,
            "weight": self.weight,
            "label": self.label,
            "rewardTime": self.reward_time,
        }

    @staticmethod
    def from_json(raw: Any) -> "TrialTypeDef":
        if not isinstance(raw, dict):
            raise TaskDefinitionError("each trial type must be an object")
        return TrialTypeDef(
            # UNFILLED, not invalid. A row the operator has started and not
            # finished is an incomplete task, not a non-definition — and the
            # split above is exactly that: `from_json` refuses what isn't a
            # definition at all, `validate.py` reports what is wrong with one.
            # Refusing an empty channel here made `tasks.preview` fail outright
            # the moment "Add trial type" was pressed, which took the state
            # machine, the parameter rail and every OTHER diagnostic off the
            # screen until both dropdowns were filled. TSK101/TSK104 name the
            # empty row instead.
            odor_channel=_opt_str(raw.get("odorChannel")) or "",
            onset_strobe=_opt_str(raw.get("onsetStrobe")) or "",
            is_go=bool(raw.get("isGo", True)),
            response_channel=_opt_str(raw.get("responseChannel")),
            reward_channel=_opt_str(raw.get("rewardChannel")),
            weight=_int(raw.get("weight", 1), "weight"),
            label=str(raw.get("label", "")),
            # Absent on a definition saved before reward volume moved onto the
            # row; 100 ms is what every fluid line paid then.
            reward_time=_int(raw.get("rewardTime", 100), "rewardTime"),
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
class SpineSlot:
    """A role in the spine (`port`, `sample`), bound to a channel by each row."""

    id: str
    type: str  # digital_in | digital_out

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type}


@dataclass(frozen=True)
class SpinePhase:
    """One phase from the palette. Fields a phase does not use stay None.

    `ms` is the default of the phase's timer parameter (`T<i>` on the wire);
    a Wait and a Counter have one only when they declare `timeout_ms`. A
    Response window's `hold_ms` is the default of its `H<i>`, and a Counter's
    `count` and `count_max` of its `N<i>` and `NX<i>`.
    """

    phase: str
    on: str | None = None              # wait, hold, counter: the input slot it watches
    outputs: tuple[str, ...] = ()      # output slots HIGH while in the phase
    ms: int | None = None              # hold, present, delay, response (the window), outcome (class timeout), iti
    timeout_ms: int | None = None      # wait, counter: optional, out to an end
    edge: str | None = None            # wait: `enter` (the default) or `exit`
    abort_on_release: str | None = None  # present, delay: an input slot whose release aborts
    abort_on_enter: str | None = None  # present, delay: an input slot whose entry aborts
    line: str | None = None            # outcome with no window before it: the reward line's slot
    responses: tuple[str, ...] = ()    # response: the input slots it watches
    hold_ms: int | None = None         # response: how long an entry that holds must be held
    count: int | None = None           # counter: N, or the low end of a drawn N
    count_max: int | None = None       # counter: the high end of a drawn N
    ratios: tuple[int, ...] = ()       # counter: a progressive N, one per completion
    ends_session: bool = False         # counter: its time limit is the session's last trial

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"phase": self.phase}
        for key, value in (("on", self.on), ("outputs", list(self.outputs) or None),
                           ("ms", self.ms), ("timeoutMs", self.timeout_ms), ("edge", self.edge),
                           ("abortOnRelease", self.abort_on_release), ("abortOnEnter", self.abort_on_enter),
                           ("line", self.line),
                           ("responses", list(self.responses) or None), ("holdMs", self.hold_ms),
                           ("count", self.count), ("countMax", self.count_max),
                           ("ratios", list(self.ratios) or None), ("endsSession", self.ends_session or None)):
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True)
class MapEntry:
    """Where one watched response, or the window's timeout, takes a trial.

    `line` is an output slot the row binds to a reward channel; the reward is
    drawn with `reward_permille`, which goes only with a line. `hold` asks for
    the response to be held for the window's `holdMs`, and letting go early is
    `hold_broken`.
    """

    outcome: str
    line: str | None = None
    reward_permille: int = 1000
    hold: bool = False

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"outcome": self.outcome}
        if self.line is not None:
            out["line"] = self.line
        if self.line is not None or self.reward_permille != 1000:
            out["rewardPermille"] = self.reward_permille
        if self.hold:
            out["hold"] = True
        return out


@dataclass(frozen=True)
class SpineRow:
    """A trial type: a stable id, the operator's name, a channel per slot, and
    its contingency map: each of the window's responses, and `timeout`, to an
    outcome class (`MapEntry`).

    `reward_permille` is read only by an Outcome with no Response window before
    it; after a window each map entry carries its own.
    """

    id: str
    name: str
    bind: dict[str, str]
    reward_ms: int = 100
    reward_permille: int = 1000
    map: dict[str, MapEntry] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name, "bind": dict(self.bind),
                               "rewardMs": self.reward_ms, "rewardPermille": self.reward_permille}
        if self.map:
            out["map"] = {key: entry.to_json() for key, entry in self.map.items()}
        return out


@dataclass(frozen=True)
class SpineBlock:
    """Rows drawn for `trials` trials; the session ends after the last block."""

    id: str
    rows: tuple[str, ...]
    trials: int

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "rows": list(self.rows), "trials": self.trials}


@dataclass(frozen=True)
class Spine:
    """A phase-spine task's own fields (`0003-phase-spine-task-model.md#task-definition`).

    Parsed leniently, like a trial row: only a value of the wrong JSON type is
    refused here. A phase this palette lacks, a slot no row binds, a channel
    this rig lacks are diagnostics (`taskdef/spine.py`), so a half-built spine
    still saves and previews.
    """

    slots: tuple[SpineSlot, ...]
    phases: tuple[SpinePhase, ...]
    rows: tuple[SpineRow, ...]
    blocks: tuple[SpineBlock, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "slots": [s.to_json() for s in self.slots],
            "spine": [p.to_json() for p in self.phases],
            "rows": [r.to_json() for r in self.rows],
            "blocks": [b.to_json() for b in self.blocks],
        }

    @staticmethod
    def from_json(raw: dict) -> "Spine":
        def objects(key: str) -> list[dict]:
            value = raw.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, dict) for v in value):
                raise TaskDefinitionError(f"{key} must be a list of objects")
            return value

        def strings(value: Any, what: str) -> tuple[str, ...]:
            if value is None:
                return ()
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise TaskDefinitionError(f"{what} must be a list of strings")
            return tuple(value)

        def opt_int(value: Any, what: str) -> int | None:
            return None if value is None else _int(value, what)

        def ints(value: Any, what: str) -> tuple[int, ...]:
            if value is None:
                return ()
            if not isinstance(value, list):
                raise TaskDefinitionError(f"{what} must be a list of whole numbers")
            return tuple(_int(v, what) for v in value)

        phases = tuple(
            SpinePhase(
                phase=str(p.get("phase", "")),
                on=_opt_str(p.get("on")),
                outputs=strings(p.get("outputs"), "a phase's outputs"),
                ms=opt_int(p.get("ms"), "ms"),
                timeout_ms=opt_int(p.get("timeoutMs"), "timeoutMs"),
                edge=_opt_str(p.get("edge")),
                abort_on_release=_opt_str(p.get("abortOnRelease")),
                abort_on_enter=_opt_str(p.get("abortOnEnter")),
                line=_opt_str(p.get("line")),
                responses=strings(p.get("responses"), "a window's responses"),
                hold_ms=opt_int(p.get("holdMs"), "holdMs"),
                count=opt_int(p.get("count"), "count"),
                count_max=opt_int(p.get("countMax"), "countMax"),
                ratios=ints(p.get("ratios"), "a counter's ratios"),
                ends_session=_bool(p.get("endsSession", False), "endsSession"),
            )
            for p in objects("spine")
        )
        rows = []
        for r in objects("rows"):
            bind = r.get("bind", {})
            if not isinstance(bind, dict) or any(not isinstance(v, str) for v in bind.values()):
                raise TaskDefinitionError("a row's bind maps each slot to a channel name")
            rows.append(SpineRow(
                id=str(r.get("id", "")),
                name=str(r.get("name", "")),
                bind={str(k): v for k, v in bind.items()},
                reward_ms=_int(r.get("rewardMs", 100), "rewardMs"),
                reward_permille=_int(r.get("rewardPermille", 1000), "rewardPermille"),
                map=_contingency_map(r.get("map")),
            ))
        return Spine(
            slots=tuple(SpineSlot(id=str(s.get("id", "")), type=str(s.get("type", ""))) for s in objects("slots")),
            phases=phases,
            rows=tuple(rows),
            blocks=tuple(
                SpineBlock(id=str(b.get("id", "")), rows=strings(b.get("rows"), "a block's rows"),
                           trials=_int(b.get("trials", 1), "trials"))
                for b in objects("blocks")
            ),
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
    #: rests on (`TASKS.md#three-layer-merge`).
    params: dict[str, Any] = field(default_factory=dict)
    #: Names the lab's archives record for runs this profile now covers. Without
    #: them those runs stop decoding in Analytics — silently, because a missing
    #: profile is treated as data.
    legacy_names: list[str] = field(default_factory=list)
    notes: str = ""
    #: A phase-spine task (ADR 0003) when set: the generator lowers it to a
    #: state table and ignores `trials`, `stages` and `selection_mode`. None for
    #: every definition saved before spines existed, whose document and
    #: generated folder are then exactly what they were.
    spine: Spine | None = None

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    @property
    def trial_count(self) -> int:
        """Rows in the trial table, or a spine task's rows."""
        return len(self.spine.rows) if self.spine is not None else len(self.trials)

    def to_json(self) -> dict[str, Any]:
        if self.spine is not None:
            # A spine task stores only what it is: no trial table, ramp or
            # selection mode it would never read.
            return {
                "id": self.id,
                "name": self.name,
                "category": self.category,
                **self.spine.to_json(),
                "params": dict(self.params),
                "legacyNames": list(self.legacy_names),
                "notes": self.notes,
            }
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
        problem = folder_name_problem(name)
        if problem:
            raise TaskDefinitionError(f"name {name!r} is not a usable folder name: {problem}")

        # Free text, but one folder under `<data_dir>/tasks/` (`folder_name_problem`).
        category = str(raw.get("category") or "Tasks")
        problem = folder_name_problem(category)
        if problem:
            raise TaskDefinitionError(f"category {category!r} is not a usable folder name: {problem}")

        mode = raw.get("selectionMode", "antibias")
        if mode not in ("antibias", "pool", "weighted"):
            raise TaskDefinitionError(
                f"selectionMode must be 'antibias', 'pool' or 'weighted', not {mode!r}"
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
        spine = Spine.from_json(raw) if "spine" in raw else None
        return TaskDefinition(
            id=task_id,
            name=name,
            category=category,
            selection_mode=mode,
            trials=[TrialTypeDef.from_json(t) for t in trials_raw],
            stages=stages,
            params=_one_row_reward_keys(dict(params), spine),
            legacy_names=[n for n in legacy],
            notes=str(raw.get("notes", "")),
            # The `spine` key is what makes a definition a spine task.
            spine=spine,
        )


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #


#: The reward keys a one-row spine stored before rewards were keyed by row id.
_ONE_ROW_REWARD_KEYS = ("reward_ms", "reward_permille")


def _one_row_reward_keys(params: dict[str, Any], spine: Spine | None) -> dict[str, Any]:
    """Carry a one-row spine's `reward_ms` and `reward_permille` over to its row's keys.

    A spine of one row stored them unkeyed; its row's parameters are now
    `reward_ms_<row id>` and `reward_permille_<row id>`
    (`TASKS.md#lowering`). Read as the row's, never dropped for its default.
    A key the row already holds wins, and the old one is left for SPN110 to name.
    """
    if spine is None or len(spine.rows) != 1:
        return params
    row = spine.rows[0].id
    for old in _ONE_ROW_REWARD_KEYS:
        new = f"{old}_{row}"
        if old in params and new not in params:
            params[new] = params.pop(old)
    return params


def _contingency_map(raw: Any) -> dict[str, MapEntry]:
    """A row's `map`, refused only for a value of the wrong JSON type."""
    if raw is None:
        return {}
    if not isinstance(raw, dict) or any(not isinstance(v, dict) for v in raw.values()):
        raise TaskDefinitionError("a row's map takes each response, and timeout, to an object")
    out: dict[str, MapEntry] = {}
    for key, entry in raw.items():
        hold = entry.get("hold", False)
        if not isinstance(hold, bool):
            raise TaskDefinitionError(f"map entry {key!r}: hold is true or false, not {hold!r}")
        outcome = entry.get("outcome", "")
        if not isinstance(outcome, str):
            raise TaskDefinitionError(f"map entry {key!r}: outcome is a class name, not {outcome!r}")
        out[str(key)] = MapEntry(
            outcome=outcome,
            line=_opt_str(entry.get("line")),
            reward_permille=_int(entry.get("rewardPermille", 1000), "rewardPermille"),
            hold=hold,
        )
    return out


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


def _bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise TaskDefinitionError(f"{what} is true or false, not {value!r}")
    return value
