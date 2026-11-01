"""A phase-spine task: what is wrong with one, and the folder it generates (`TASKS.md#spine-tasks`).

ADR 0003's spine: a spine of phases, rows that bind its slots to this rig's
channels and map each response to an outcome class, one block drawing them.
The definition's data is
`model.Spine`; this module judges it against the rig and the vocabulary and
writes what the board runs:

    <name>.ino      five includes and two calls: the runner is BoxSpine.h's
    TaskPins.h      this rig's pins and every live strobe code (generate.py)
    TaskSpine.h     the lowered state table, the channel rows, the parameters
    task.json       the profile, carrying the `spine` snapshot replay reads

NO FIRMWARE IS WRITTEN PER TASK. Everything a spine varies reaches the board
as data: the table and channel rows at compile time, every duration and
probability as a `SET` parameter. BoxSpine.h is the one runner.

THE SNAPSHOT IS THE RECORD. The profile's `spine` key holds the definition,
the table exactly as lowered, which channel and which edge codes each bit is,
and which wire key each parameter slot is. It rides in every run's `.tsv`
header (`DATA.md#the-tsv-log`), so a crashed run's file alone is enough to
replay it, on any machine, whatever the lowering does in a later version.

Codes are names here, never numbers: the snapshot's own `strobes` map (the
vocabulary when the run started) turns them into numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..rig import registry
from . import lowering
from .model import ID_RE, Spine, TaskDefinition
from .validate import Diagnostic

#: The structural codes a spine strobes, by role (`0003-phase-spine-task-model.md#the-strobe-stream`).
#: The ADR's SESSION_START and SESSION_END are the vocabulary's existing
#: START_SESSION and END_SESSION: the same events, so no code is spent twice.
STRUCTURAL = {"sessionStart": "START_SESSION", "trialStart": "TRIAL_START", "sessionEnd": "END_SESSION"}

SLOT_TYPES = ("digital_in", "digital_out", "pwm_out", "tone_out")
OUTPUT_TYPES = ("digital_out", "pwm_out", "tone_out")

#: Each driven output's row values (`TASKS.md#driven-outputs`), in parameter
#: order: (drive key, metadata prefix, label, unit, min, max). A train's width
#: must also be shorter than its period, 1000 // hz (SPN111).
DRIVE_VALUES: dict[str, tuple[tuple[str, str, str, str | None, int, int], ...]] = {
    "pwm": (("duty", "pwm_duty", "PWM duty", None, 0, 255),),
    "tone": (("hz", "tone_hz", "Tone", "Hz", 31, 65535),),
    "train": (("hz", "train_hz", "Train rate", "Hz", 1, 100),
              ("widthMs", "train_width_ms", "Pulse width", "ms", 1, 999),
              ("ms", "train_ms", "Train length", "ms", 0, 3_600_000)),
}

#: Bounds on each parameter, held by the board too: a value outside them is
#: CLAMPED and the start refused (`TASKS.md#confirming-the-parameters`).
_MS_MAX = 3_600_000
_TRIALS_MAX = 10_000
_REWARD_MS_MAX = 5_000
#: What each part of a task takes of a Mega's RAM in BoxSpine.h, as AVR lays it
#: out. A parameter is its `SpineParam` (a 2 B key pointer and three uint32_t)
#: and its uint32_t in `params[]`, plus its key string, which AVR keeps in RAM.
#: An input bit is its `SpineInput` (8 B) and its debounce state (`level`, `raw`,
#: `rawSince`: 6 B); an output bit its `SpineOutput` (5 B). An empty array still
#: takes one element. `test_spine_task.py` holds these to an AVR build.
PARAM_BYTES = 18
INPUT_BYTES = 14
OUTPUT_BYTES = 5
#: A driven output bit adds its `SpineDrive` (3 B), its train's start tick (4 B)
#: and its pin's level (1 B), and a task with any adds the `SpineDriveRun` that
#: tracks them (9 B). A task with no driven output compiles none of it.
DRIVE_BYTES = 8
DRIVE_RUN_BYTES = 9
#: What linking the AVR core's `tone()` adds, only when a task has a tone
#: output (`SPINE_HAS_TONE`). Measured by the same test.
TONE_RAM_BYTES = 32
#: The globals of a spine sketch apart from its task's data: the runner,
#: BehaviorBox.h and the Arduino core, measured by that same test. A build can
#: come in a few bytes under the sum (the compiler folds a one-element input
#: array), never over it.
RUNNER_RAM_BYTES = 384
#: The most RAM a task's data (`task_ram_bytes`) may take, out of a Mega's 8192 B.
#: With the runner's own, globals stay at most 5384 B (66%), leaving the stack
#: and the serial buffers at least 2808 B (`TASKS.md#spine-diagnostics`). An
#: 18-row 2AFC fits.
TASK_RAM_MAX = 5000


def task_ram_bytes(low: lowering.Lowered) -> int:
    """The bytes of RAM a task's generated `TaskSpine.h` adds to a Mega build:
    its states and edge rows, its parameters, its channel bits and its driven
    outputs."""
    return (lowering.table_bytes(len(low.states), max(1, len(low.edges)))
            + sum(PARAM_BYTES + len(key) + 1 for key in low.params)
            + INPUT_BYTES * max(1, len(low.inputs)) + OUTPUT_BYTES * max(1, len(low.outputs))
            + (DRIVE_RUN_BYTES + DRIVE_BYTES * len(low.drives) if low.drives else 0)
            + (TONE_RAM_BYTES if any(kind == "tone" for _, kind, _ in low.drives) else 0))


@dataclass
class _Resolved:
    """A spine against this rig: every slot's channel and codes, and the table."""

    inputs: list[dict[str, Any]] = field(default_factory=list)
    outputs: list[dict[str, Any]] = field(default_factory=list)
    lowered: lowering.Lowered | None = None
    #: Why the folder cannot compile, one `#error` each.
    blockers: list[str] = field(default_factory=list)
    problems: list[Diagnostic] = field(default_factory=list)


def diagnostics(definition: TaskDefinition) -> list[Diagnostic]:
    """Every problem with a spine task, located (SPN101–SPN110)."""
    return _resolve(definition).problems


def _resolve(definition: TaskDefinition) -> _Resolved:
    spine = definition.spine
    assert spine is not None
    channels, vocab = registry.channels(), registry.vocabulary()
    out = _Resolved()

    def problem(location: str, code: str, message: str) -> None:
        out.problems.append(Diagnostic(location, message, code))

    slot_type: dict[str, str] = {}
    slot_mode: dict[str, str | None] = {}
    drives: dict[str, str] = {}
    slots_before = len(out.problems)
    for i, slot in enumerate(spine.slots):
        if not slot.id or slot.id in slot_type:
            problem(f"slots[{i}].id", "SPN105", f"slot {slot.id!r} needs an id of its own")
        elif slot.id == lowering.TIMEOUT:
            problem(f"slots[{i}].id", "SPN105", f"no slot can be called {lowering.TIMEOUT!r}: a row's map "
                    "keeps that key for the window running out")
        elif slot.type not in SLOT_TYPES:
            problem(f"slots[{i}].type", "SPN105", f"slot {slot.id!r} is {slot.type!r}, not one of {SLOT_TYPES}")
        elif slot.mode not in (None, "level") and (slot.type, slot.mode) != ("digital_out", "train"):
            problem(f"slots[{i}].mode", "SPN105", f"slot {slot.id!r} is a {slot.type} in {slot.mode!r} mode; "
                    "only a digital_out takes a mode, and it is level or train")
        else:
            slot_type[slot.id] = slot.type
            slot_mode[slot.id] = None if slot.mode == "level" else slot.mode
            drive = registry.drive_of(slot.type, slot_mode[slot.id])
            if drive is not None:
                drives[slot.id] = drive
    inputs = [s for s, t in slot_type.items() if t == "digital_in"]
    outputs = [s for s, t in slot_type.items() if t in OUTPUT_TYPES]
    # A reward line, the only output a phase or map names outside `outputs`, is a level line.
    lines = {s for s in outputs if s not in drives}

    shape_ok = _shape_problems(spine, slot_type, lines, problem) and len(out.problems) == slots_before
    rows_ok = _row_problems(spine, problem)
    map_ok = _map_problems(spine, lines, problem)
    drive_ok = _drive_problems(spine, drives, out, problem)
    rows = [r.to_json() for r in spine.rows]

    # Every row's bindings. One channel serves one slot, across rows too; the
    # same channel in the same slot of several rows is one bit.
    slot_of: dict[str, str] = {}
    for r, row in enumerate(spine.rows):
        for slot in (*inputs, *outputs):
            at = f"rows[{r}].bind.{slot}"
            name = row.bind.get(slot, "")
            channel = channels.get(name) if name else None
            if channel is None:
                problem(at, "SPN101", f"slot {slot!r} is bound to no channel" if not name
                        else f"this rig has no channel {name!r}")
                out.blockers.append(f"slot {slot} is bound to no channel of this rig")
                continue
            if not _fits(channel, slot_type[slot], slot_mode[slot]):
                wants = _type_name(slot_type[slot], slot_mode[slot])
                problem(at, "SPN102", f"{name} is a {_type_name(channel.type, channel.mode)} {channel.kind} "
                        f"channel; slot {slot!r} needs a {wants}"
                        + (" other than the sync line" if channel.kind == "sync" else ""))
                out.blockers.append(f"{name} is not a {wants} channel")
                continue
            if slot_of.setdefault(name, slot) != slot:
                problem(at, "SPN107", f"{name} is already slot {slot_of[name]!r}; one channel is one slot")

    # One entry per bit, each with its channel's pin and edge codes. A driven
    # slot has a bit per row, so its channel's codes are checked once.
    uncoded: set[tuple[str, str]] = set()
    for kind, slots in (("in", inputs), ("out", outputs)):
        bits, _ = lowering.channel_bits(slots, rows, per_row=drives)
        for slot, name in bits:
            entry: dict[str, Any] = {"slot": slot, "channel": name}
            if slot in drives:
                entry["drive"] = drives[slot]
            (out.inputs if kind == "in" else out.outputs).append(entry)
            channel = channels.get(name) if name else None
            if channel is None or not _fits(channel, slot_type[slot], slot_mode[slot]):
                continue  # diagnosed above
            at = next(f"rows[{r}].bind.{slot}" for r, row in enumerate(spine.rows) if row.bind.get(slot) == name)
            entry["pin"] = channel.index
            if kind == "in":
                entry["activeHigh"] = channel.active_level == "high"
                entry["debounceMs"] = int(channel.debounce_ms or 0)
            named = dict(channel.edges)
            for role, edge in zip(("rise", "fall") if kind == "in" else ("on", "off"),
                                  registry.edges_of(channel.type, channel.mode)):
                code = named.get(edge)
                if code is not None and code in vocab:
                    entry[role] = code
                elif (name, edge) not in uncoded:
                    uncoded.add((name, edge))
                    problem(at, "SPN103", f"the {edge} edge of {name} has no live strobe code. Save the "
                            "wiring on the Rig page to issue one")
                    out.blockers.append(f"the {edge} edge of {name} has no strobe code")

    if shape_ok and rows_ok and map_ok and drive_ok:
        try:
            out.lowered = lowering.lower([p.to_json() for p in spine.phases], inputs=inputs, outputs=outputs,
                                         rows=rows, drives=drives)
        except lowering.LoweringError as exc:  # too many states, or two responses on one channel
            problem("spine", "SPN105", str(exc))
    if out.lowered is not None:
        for bit, kind, first in out.lowered.drives:  # output bit j is out.outputs[j]
            out.outputs[bit]["params"] = list(out.lowered.params[first : first + len(lowering.DRIVE_PARAMS[kind])])
        _table_problems(definition, out, problem)
    if out.lowered is None:
        out.blockers.append("this spine cannot be lowered to a state table; see the task's diagnostics")

    for role, name in STRUCTURAL.items():
        if name not in vocab:
            problem(f"vocabulary.{name}", "SPN104", f"the strobe vocabulary has no {name} code. Add it on "
                    "Task > Strobes, at the number the shipped vocabulary gives it")
            out.blockers.append(f"the strobe vocabulary has no {name} code: add it on Task > Strobes")
    return out


def _shape_problems(spine: Spine, slot_type: dict[str, str], lines: set[str], problem) -> bool:  # noqa: ANN001
    """The spine's own shape (SPN105). True when it can be lowered. `lines` are
    the output slots that can be a reward line: the level ones."""
    ok = True

    def bad(location: str, message: str) -> None:
        nonlocal ok
        ok = False
        problem(location, "SPN105", message)

    phases = spine.phases
    kinds = [p.phase for p in phases]
    if kinds.count("iti") != 1 or not kinds or kinds[-1] != "iti" or len(phases) < 2:
        bad("spine", "a spine ends in exactly one ITI, after at least one other phase: every abort goes there")
    if kinds.count("outcome") > 1:
        # Each resolved trial marks its class in exactly one state (TASKS.md#lowering).
        bad("spine", "a spine has at most one Outcome: a second would mark a trial's class twice")
    windows = [i for i, kind in enumerate(kinds) if kind == "response"]
    if len(windows) > 1:
        bad("spine", "a spine has at most one Response window")
    window = windows[0] if windows else None
    if window is not None:
        end = kinds.index("iti") if "iti" in kinds else len(kinds)
        if kinds[window + 1 : end].count("outcome") != 1:
            bad("spine", "a Response window is followed by exactly one Outcome, before the ITI: the row's "
                "map says what it pays")
    if len(spine.rows) > 1 and kinds and kinds[0] == "outcome":
        bad("spine[0]", "with several rows the first phase cannot be an Outcome: a trial starts by drawing "
            "its row, and an Outcome's draw cannot follow that one in the same tick")
    for i, p in enumerate(phases):
        at = f"spine[{i}]"
        if p.phase not in lowering.PHASES:
            bad(f"{at}.phase", f"{p.phase!r} is not a phase of this palette {lowering.PHASES}")
            continue
        for slot in p.outputs:
            if slot_type.get(slot) not in OUTPUT_TYPES:
                bad(f"{at}.outputs", f"{slot!r} is not an output slot")
        if p.phase == "wait" and slot_type.get(p.on or "") != "digital_in":
            bad(f"{at}.on", f"a wait moves on at an edge of an input slot; {p.on!r} is not one")
        if p.phase == "present" and p.abort_on_release is not None \
                and slot_type.get(p.abort_on_release) != "digital_in":
            bad(f"{at}.abortOnRelease", f"{p.abort_on_release!r} is not an input slot")
        if p.phase == "response":
            if not p.responses or len(set(p.responses)) != len(p.responses) \
                    or any(slot_type.get(s) != "digital_in" for s in p.responses):
                bad(f"{at}.responses", "a window watches one or more input slots, each named once")
        if p.phase == "outcome":
            if window is not None and i > window:
                if p.line is not None:
                    bad(f"{at}.line", "an Outcome after a Response window pays as each row's map says, so it "
                        "names no line of its own")
            elif (p.line or "") not in lines:
                bad(f"{at}.line", f"an outcome opens a level output slot's line; {p.line!r} is not one")
        if p.phase in ("present", "delay", "response", "iti") and p.ms is None:
            bad(f"{at}.ms", f"a {p.phase} lasts a set time; give it ms")
        for key, value in (("ms", p.ms), ("timeoutMs", p.timeout_ms), ("holdMs", p.hold_ms)):
            if value is not None and not 0 <= value <= _MS_MAX:
                bad(f"{at}.{key}", f"a duration is 0 to {_MS_MAX} ms")
    return ok


def _row_problems(spine: Spine, problem) -> bool:  # noqa: ANN001
    """The rows and the block (SPN106, SPN108). True when the rows can be lowered:
    there is one, and each id is its own and can name parameters."""
    ids_ok = True
    if not spine.rows:
        problem("rows", "SPN106", "a spine task has at least one row")
    if len(spine.blocks) != 1:
        # Several blocks need the block runner (#103).
        problem("blocks", "SPN106", f"a spine task has exactly one block for now, not {len(spine.blocks)}")
    seen: set[str] = set()
    for r, row in enumerate(spine.rows):
        at = f"rows[{r}]"
        if not ID_RE.match(row.id):
            ids_ok = False
            problem(f"{at}.id", "SPN106", f"{row.id!r} is not a row id: lower case letters, digits and "
                    "underscores, starting with a letter. It names the row's parameters")
        elif row.id in seen:
            ids_ok = False
            problem(f"{at}.id", "SPN106", f"two rows are {row.id!r}; each row's id is its own")
        seen.add(row.id)
        if not row.name.strip():
            problem(f"{at}.name", "SPN108", "this row has no name. Its name is what every readout of it is titled")
        if not 0 <= row.reward_permille <= 1000:
            problem(f"{at}.rewardPermille", "SPN106", "a reward probability is 0 to 1000 permille")
        if not 0 <= row.reward_ms <= _REWARD_MS_MAX:
            # The board holds RW<r> to this range and would refuse the start (CLAMPED).
            problem(f"{at}.rewardMs", "SPN106", f"a reward opens its line for 0 to {_REWARD_MS_MAX} ms")
    if spine.blocks:
        block = spine.blocks[0]
        drawn = list(block.rows)
        if len(set(drawn)) != len(drawn) or set(drawn) != {row.id for row in spine.rows}:
            problem("blocks[0].rows", "SPN106", "the block draws every row exactly once, by its id")
        if not 1 <= block.trials <= _TRIALS_MAX:
            problem("blocks[0].trials", "SPN106", f"a block runs 1 to {_TRIALS_MAX} trials")
    return bool(spine.rows) and ids_ok


def _map_problems(spine: Spine, lines: set[str], problem) -> bool:  # noqa: ANN001
    """Each row's contingency map (SPN109). True when every map can be written as states."""
    ok = True

    def bad(location: str, message: str, blocks: bool = True) -> None:
        nonlocal ok
        ok = ok and not blocks
        problem(location, "SPN109", message)

    windows = [p for p in spine.phases if p.phase == "response"]
    if len(windows) > 1:
        return False  # SPN105 refuses the spine; no map can be judged against it
    window = windows[0] if windows else None
    for r, row in enumerate(spine.rows):
        at = f"rows[{r}].map"
        if window is None:
            if row.map:
                bad(at, "this row maps responses, but the spine has no Response window", blocks=False)
            continue
        keys = [*window.responses, lowering.TIMEOUT]
        for key in keys:
            if key not in row.map:
                bad(f"{at}.{key}", f"the window watches {key!r} and this row's map does not say where it goes"
                    if key != lowering.TIMEOUT else "this row's map does not say where the window running "
                    "out goes")
        for key, entry in row.map.items():
            if key not in keys:
                bad(f"{at}.{key}", f"the window does not watch {key!r}", blocks=False)
                continue
            if entry.outcome not in lowering.OUTCOME_CLASSES:
                bad(f"{at}.{key}.outcome", f"{entry.outcome!r} is not an outcome class "
                    f"{lowering.OUTCOME_CLASSES}")
            if entry.line is not None and entry.line not in lines:
                bad(f"{at}.{key}.line", f"a reward line is a level output slot; {entry.line!r} is not one")
            if not 0 <= entry.reward_permille <= 1000:
                bad(f"{at}.{key}.rewardPermille", "a reward probability is 0 to 1000 permille", blocks=False)
            elif entry.line is None and entry.reward_permille != 1000:
                bad(f"{at}.{key}.rewardPermille", "a reward probability goes with a line, and this entry "
                    "names none", blocks=False)
            if entry.hold and key == lowering.TIMEOUT:
                bad(f"{at}.{key}.hold", "the window running out is no response to hold")
            elif entry.hold and window.hold_ms is None:
                bad(f"{at}.{key}.hold", "a hold lasts the window's holdMs, and the window gives none")
    return ok


def _fits(channel: registry.Channel, slot_type: str, slot_mode: str | None) -> bool:
    """Whether a channel can fill a slot: the same type and mode, and never the sync line."""
    return channel.type == slot_type and channel.mode == slot_mode and channel.kind != "sync"


def _type_name(channel_type: str, mode: str | None) -> str:
    return f"{channel_type} train" if mode == "train" else channel_type


def _drive_problems(spine: Spine, drives: dict[str, str], out: _Resolved, problem) -> bool:  # noqa: ANN001
    """Each row's values for each driven output slot (SPN111). True when every
    row gives every value in range, so the parameters can be declared."""
    ok = True
    for r, row in enumerate(spine.rows):
        for slot, values in row.drive.items():
            if slot not in drives:
                problem(f"rows[{r}].drive.{slot}", "SPN111", f"{slot!r} is not a PWM, tone or train slot, so it "
                        "takes no drive values")
        for slot, kind in drives.items():
            values = row.drive.get(slot, {})
            for key, _, label, unit, lo, hi in DRIVE_VALUES[kind]:
                at = f"rows[{r}].drive.{slot}.{key}"
                value = values.get(key)
                if value is None:
                    problem(at, "SPN111", f"this row gives slot {slot!r} no {key}: {label.lower()}, "
                            f"{lo} to {hi}{' ' + unit if unit else ''}")
                elif not lo <= value <= hi:
                    problem(at, "SPN111", f"{label} is {lo} to {hi}{' ' + unit if unit else ''}, not {value}")
                else:
                    continue
                ok = False
            hz, width = values.get("hz"), values.get("widthMs")
            if kind == "train" and isinstance(hz, int) and isinstance(width, int) and 1 <= hz <= 100 \
                    and width >= 1000 // hz:
                # Each value is in its own range, but the pair would hold the
                # line HIGH: a steady output where a train was asked for.
                problem(f"rows[{r}].drive.{slot}.widthMs", "SPN111", f"a {width} ms pulse at {hz} Hz is not "
                        f"shorter than its {1000 // hz} ms period, so the line would stay on: a steady "
                        "output, not a train")
                ok = False
    if not ok:
        out.blockers.append("a row gives a PWM, tone or train slot no value, one out of range, or a "
                            "train whose pulse is not shorter than its period")
    return ok


def _table_problems(definition: TaskDefinition, out: _Resolved, problem) -> None:  # noqa: ANN001
    """What only the lowered table shows: parameter keys two rows would share
    (SPN106), stored values no parameter reads (SPN110), and the table's RAM
    (SPN105). A collision withholds the table, since a profile declaring one key
    twice does not load."""
    spine, low = definition.spine, out.lowered
    assert spine is not None and low is not None
    fields = _param_fields(spine, low)
    owner: dict[str, lowering.ParamSlot] = {}
    for f, s in zip(fields, low.slots):
        key = f["metadataKey"]
        if key in owner:
            rows = sorted({spine.rows[r].id for r in (owner[key].row, s.row) if r is not None})
            problem(f"rows[{s.row}].id" if s.row is not None else "spine", "SPN106",
                    f"rows {' and '.join(map(repr, rows))} would both name a parameter {key!r}; rename one")
        owner.setdefault(key, s)
    if len(owner) != len(fields):
        out.lowered = None
        return
    for key in definition.params:
        if key not in owner:
            problem(f"params.{key}", "SPN110", f"no parameter of this task is {key!r}, so its stored value "
                    f"{definition.params[key]!r} is not used. Move it to the parameter it belongs to, or remove it")
    size = task_ram_bytes(low)
    if size > TASK_RAM_MAX:
        problem("spine", "SPN105", f"the state table, parameters and channels take {size} B of the board's RAM, "
                f"over the {TASK_RAM_MAX} B a Mega can spare for them: fewer rows, phases or map entries")
        out.blockers.append(f"the task's data takes {size} B of RAM, over {TASK_RAM_MAX} B")


# --------------------------------------------------------------------------- #
# The profile
# --------------------------------------------------------------------------- #


def profile_json(definition: TaskDefinition) -> dict[str, Any]:
    """The `task.json` a spine task compiles to, with its `spine` snapshot."""
    spine = definition.spine
    assert spine is not None
    resolved = _resolve(definition)
    low = resolved.lowered
    config = [_with_value(f, definition) for f in _param_fields(spine, low)]
    snapshot: dict[str, Any] = {
        "interp": lowering.INTERP_VERSION,
        **spine.to_json(),
        "inputs": [_public(e, ("slot", "channel", "rise", "fall")) for e in resolved.inputs],
        "outputs": [_public(e, ("slot", "channel", "on", "off", "drive", "params")) for e in resolved.outputs],
        "params": list(low.params) if low else [],
        # `phases` and `rows`: the phase index and the row index (into `rows`)
        # each state belongs to, null for the pick state. The trial table reads
        # them; the board never does.
        "table": ({"states": [list(s) for s in low.states], "edges": [list(e) for e in low.edges],
                   "phases": list(low.phases), "rows": list(low.rows)}
                  if low else None),
        "structural": dict(STRUCTURAL),
    }
    return {
        "taskName": definition.name,
        "kind": "behavior",
        "config": config,
        # Nothing scores a spine live yet: Mission Control's replay is #100.
        "liveMetrics": [],
        "legacyNames": list(definition.legacy_names),
        "spine": snapshot,
    }


def _public(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """What replay needs of a channel row; never its pin, which stays on this machine."""
    return {k: entry[k] for k in keys if k in entry}


def _param_fields(spine: Spine, low: lowering.Lowered | None) -> list[dict[str, Any]]:
    """One config field per parameter slot, in slot order: slot s is wire key `params[s]`.

    Metadata keys name a row by its stable id, and a map entry by its slot (or
    `timeout`), so renaming a row or reordering rows moves no stored value.
    """
    if low is None:
        return []
    block = spine.blocks[0] if spine.blocks else None
    out: list[dict[str, Any]] = []
    for s in low.slots:
        if s.role == "trials":
            out.append(_int_field("block_trials", s.key, "Trials", block.trials if block else 1,
                                  "Session", None, 1, _TRIALS_MAX,
                                  "How many trials the session runs; it ends at the start of the next."))
        elif s.role == "timer":
            i = s.phase
            p = spine.phases[i]
            wait = p.phase == "wait"
            metadata = f"wait_{i}_timeout_ms" if wait else f"{p.phase}_{i}_ms"
            name = {"wait": "Wait timeout", "response": "Response window"}.get(p.phase, p.phase.capitalize())
            default = (p.timeout_ms if wait else p.ms) or 0
            help_text = {
                "wait": "How long a wait lasts before it goes to the ITI.",
                "response": "How long the window waits for a response before the map's timeout entry.",
                "outcome": "How long the outcome lasts after the reward, before the next phase.",
            }.get(p.phase, "How long this phase lasts.")
            out.append(_int_field(metadata, s.key, f"{name} (phase {i + 1})", default, "Phases", "ms", 0,
                                  _MS_MAX, help_text))
        elif s.role == "hold":
            i = s.phase
            out.append(_int_field(f"response_{i}_hold_ms", s.key, f"Response hold (phase {i + 1})",
                                  spine.phases[i].hold_ms or 0, "Phases", "ms", 0, _MS_MAX,
                                  "How long a response whose map entry holds must be held; letting go "
                                  "sooner is hold broken."))
        else:
            row = spine.rows[s.row]
            if s.slot is not None:  # a driven output's value
                kind = next(k for k, roles in lowering.DRIVE_PARAMS.items() if s.role in dict(roles))
                key, prefix, label, unit, lo, hi = next(
                    v for v, (role, _) in zip(DRIVE_VALUES[kind], lowering.DRIVE_PARAMS[kind]) if role == s.role)
                value = row.drive.get(s.slot, {}).get(key)
                out.append(_int_field(f"{prefix}_{row.id}_{s.slot}", s.key, f"{label} — {row.name}, {s.slot}",
                                      value if isinstance(value, int) and lo <= value <= hi else lo,
                                      "Outputs", unit, lo, hi, _DRIVE_HELP[s.role]))
            elif s.role == "reward_ms":
                out.append(_int_field(f"reward_ms_{row.id}", s.key, f"Reward — {row.name}", row.reward_ms,
                                      "Reward volume", "ms", 0, _REWARD_MS_MAX,
                                      "How long the reward line opens: the reward volume."))
            elif s.entry is None:
                out.append(_int_field(f"reward_permille_{row.id}", s.key, f"Reward probability — {row.name}",
                                      row.reward_permille, "Reward volume", "‰", 0, 1000,
                                      "The chance, in thousandths, that an outcome opens the line."))
            else:
                out.append(_int_field(f"reward_permille_{row.id}_{s.entry}", s.key,
                                      f"Reward probability — {row.name}, {s.entry}",
                                      row.map[s.entry].reward_permille, "Reward volume", "‰", 0, 1000,
                                      f"The chance, in thousandths, that {s.entry} opens its line."))
    return out


_DRIVE_HELP = {
    "pwm_duty": "The PWM duty this row drives the line at while a phase holds it on: 0 is off, 255 fully on.",
    "tone_hz": "The tone this row plays while a phase holds it on.",
    "train_hz": "How many pulses a second this row's train fires while a phase holds it on.",
    "train_width": "How long each pulse of this row's train is HIGH. Shorter than the period, 1000 / rate.",
    "train_ms": "How long this row's train runs from its first pulse; 0 runs it as long as the phase holds it.",
}


def _int_field(metadata: str, wire: str, label: str, default: int, group: str, unit: str | None,
               lo: int, hi: int, help_text: str) -> dict[str, Any]:
    out: dict[str, Any] = {"metadataKey": metadata, "wireKey": wire, "label": label, "type": "int",
                           "default": default, "group": group, "min": lo, "max": hi, "step": 1,
                           "help": help_text}
    if unit:
        out["unit"] = unit
    return out


def _with_value(field_: dict[str, Any], definition: TaskDefinition) -> dict[str, Any]:
    """`params` holds only divergences, keyed by metadata key, as on a legacy task."""
    key = field_["metadataKey"]
    return field_ | {"default": definition.params[key]} if key in definition.params else field_


# --------------------------------------------------------------------------- #
# The firmware
# --------------------------------------------------------------------------- #


def sketch_ino(definition: TaskDefinition) -> str:
    """The whole `.ino`: the runner is the library's, so there is nothing to write."""
    return (
        "/*  GENERATED by Ephymeris -- do not edit.\n\n"
        f"    The phase-spine task \"{definition.name}\". Every spine task's sketch is\n"
        "    these lines: what the task is arrives as data in TaskSpine.h, and the\n"
        "    one runner is BoxSpine.h (docs/TASKS.md#spine-tasks). */\n\n"
        '#include "TaskPins.h"   // GENERATED: this rig\'s pins and every strobe code. First.\n'
        '#include "TaskSpine.h"  // GENERATED: the state table, channels and parameters.\n'
        "#include <BehaviorBox.h>\n"
        "#include <BoxInterp.h>\n"
        "#include <BoxSpine.h>\n\n"
        "void setup() { box_spine::setup(); }\n\n"
        "void loop() { box_spine::loop(); }\n"
    )


def task_spine_h(definition: TaskDefinition, banner: str) -> str:
    """The table and the channel rows, as preprocessor initialisers.

    Pure preprocessor, like `UtilityChannels.h`: it is read before the library
    has defined a type, and BoxSpine.h builds its arrays from these macros. A
    folder that cannot run says why with an `#error` instead of compiling into
    a board that strobes what nobody declared.
    """
    spine = definition.spine
    assert spine is not None
    resolved = _resolve(definition)
    low = resolved.lowered
    lines = [banner, "", "#ifndef TASK_SPINE_H", "#define TASK_SPINE_H", ""]
    if resolved.blockers:
        lines += [f'#error "{_c_text(b)}"' for b in dict.fromkeys(resolved.blockers)]
        lines += ["", "#endif // TASK_SPINE_H", ""]
        return "\n".join(lines)
    assert low is not None
    fields = [_with_value(f, definition) for f in _param_fields(spine, low)]

    def initialiser(rows: list[str]) -> str:
        # A C array cannot be empty; a count of 0 never reads the placeholder.
        return "{ \\\n" + ", \\\n".join(f"  {r}" for r in rows) + " }" if rows else "{ {0} }"

    states = [
        "{" + ", ".join([f"0x{s[0]:X}UL", f"0x{s[1]:X}UL", *map(str, s[2:])]) + "}" for s in low.states
    ]
    edges = ["{" + ", ".join(map(str, e)) + "}" for e in low.edges]
    inputs = [
        f"{{{e['pin']}, {1 if e['activeHigh'] else 0}, {e['debounceMs']}, BF_{e['rise']}, BF_{e['fall']}}}"
        for e in resolved.inputs
    ]
    outputs = [f"{{{e['pin']}, BF_{e['on']}, BF_{e['off']}}}" for e in resolved.outputs]
    drives = [f"{{{bit}, {_DRIVE_MACRO[kind]}, {first}}}" for bit, kind, first in low.drives]
    params = [f'{{"{f["wireKey"]}", {f["default"]}UL, {f["min"]}UL, {f["max"]}UL}}' for f in fields]
    lines += [
        "/*  The table format this was lowered for; BoxSpine.h refuses another. */",
        f"#define SPINE_INTERP {lowering.INTERP_VERSION}",
        "",
        "/*  The state table (BoxInterp.h, THE STATE TABLE). State 0 starts a trial;",
        "    with several rows it is the pick state that draws the trial's row.",
        "    {outputs, watch, timer_min, timer_max, on_timeout, chance, on_hit,",
        "     on_miss, edge_first, edge_count, flags, outcome} */",
        f"#define SPINE_NUM_STATES {len(states)}",
        f"#define SPINE_STATES {initialiser(states)}",
        "/*  {input, edge, next} */",
        f"#define SPINE_NUM_EDGES {len(edges)}",
        f"#define SPINE_EDGES {initialiser(edges)}",
        "",
        "/*  Input bit i, one per channel, by slot then by row: {pin, active high,",
        "    debounce ms, rise code, fall code}. */",
        f"#define SPINE_NUM_INPUTS {len(inputs)}",
        f"#define SPINE_INPUTS {initialiser(inputs)}",
        "/*  Output bit j, one per channel (one per row for a driven slot), by slot",
        "    then by row: {pin, on code, off code}. */",
        f"#define SPINE_NUM_OUTPUTS {len(outputs)}",
        f"#define SPINE_OUTPUTS {initialiser(outputs)}",
        "/*  Each driven output bit (docs/TASKS.md#driven-outputs): {output bit,",
        "    kind, first parameter slot}. A train's rate, width and length are three",
        "    slots from it. SPINE_HAS_TONE links tone() only when a task plays one. */",
        f"#define SPINE_NUM_DRIVES {len(drives)}",
        f"#define SPINE_DRIVES {initialiser(drives)}",
        f"#define SPINE_HAS_TONE {1 if any(kind == 'tone' for _, kind, _ in low.drives) else 0}",
        "",
        "/*  Parameter slot s: {wire key, default, min, max}. Slot 0 is the block's",
        "    trial count. A SET value outside [min, max] is CLAMPED. */",
        f"#define SPINE_NUM_PARAMS {len(params)}",
        f"#define SPINE_PARAMS {initialiser(params)}",
        "",
        "#endif // TASK_SPINE_H",
        "",
    ]
    return "\n".join(lines)


#: A drive kind -> its `SpineDrive.kind` in BoxSpine.h.
_DRIVE_MACRO = {"pwm": "SPINE_DRIVE_PWM", "tone": "SPINE_DRIVE_TONE", "train": "SPINE_DRIVE_TRAIN"}


def _c_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
