"""A phase-spine task: what is wrong with one, and the folder it generates (`TASKS.md#spine-tasks`).

ADR 0003's first tracer: a spine of the first phases, one row binding its
slots to this rig's channels, one block. The definition's data is
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
from .model import Spine, TaskDefinition
from .validate import Diagnostic

#: The structural codes a spine strobes, by role (`0003-phase-spine-task-model.md#the-strobe-stream`).
#: The ADR's SESSION_START and SESSION_END are the vocabulary's existing
#: START_SESSION and END_SESSION: the same events, so no code is spent twice.
STRUCTURAL = {"sessionStart": "START_SESSION", "trialStart": "TRIAL_START", "sessionEnd": "END_SESSION"}

#: Which edge of a channel's type a bit reports as its rise and its fall.
_INPUT_EDGES = ("enter", "exit")
_OUTPUT_EDGES = ("on", "off")

SLOT_TYPES = ("digital_in", "digital_out")

#: Bounds on each parameter, held by the board too: a value outside them is
#: CLAMPED and the start refused (`TASKS.md#confirming-the-parameters`).
_MS_MAX = 3_600_000
_TRIALS_MAX = 10_000
_REWARD_MS_MAX = 5_000


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
    """Every problem with a spine task, located (SPN101–SPN108)."""
    return _resolve(definition).problems


def _resolve(definition: TaskDefinition) -> _Resolved:
    spine = definition.spine
    assert spine is not None
    channels, vocab = registry.channels(), registry.vocabulary()
    out = _Resolved()

    def problem(location: str, code: str, message: str) -> None:
        out.problems.append(Diagnostic(location, message, code))

    slot_type: dict[str, str] = {}
    for i, slot in enumerate(spine.slots):
        if not slot.id or slot.id in slot_type:
            problem(f"slots[{i}].id", "SPN105", f"slot {slot.id!r} needs an id of its own")
        elif slot.type not in SLOT_TYPES:
            problem(f"slots[{i}].type", "SPN105", f"slot {slot.id!r} is {slot.type!r}, not one of {SLOT_TYPES}")
        else:
            slot_type[slot.id] = slot.type
    inputs = [s for s, t in slot_type.items() if t == "digital_in"]
    outputs = [s for s, t in slot_type.items() if t == "digital_out"]

    shape_ok = _shape_problems(spine, slot_type, problem)
    if shape_ok:
        try:
            out.lowered = lowering.lower([p.to_json() for p in spine.phases], inputs=inputs, outputs=outputs)
        except lowering.LoweringError as exc:  # every case is diagnosed above; this is the guard
            problem("spine", "SPN105", str(exc))
    if out.lowered is None:
        out.blockers.append("this spine cannot be lowered to a state table; see the task's diagnostics")

    # One row and one block: the tracer. Rows that differ need per-row states
    # (#101); several blocks need the block runner (#103).
    if len(spine.rows) != 1:
        problem("rows", "SPN106", f"a spine task has exactly one row for now, not {len(spine.rows)}")
    if len(spine.blocks) != 1:
        problem("blocks", "SPN106", f"a spine task has exactly one block for now, not {len(spine.blocks)}")
    row = spine.rows[0] if spine.rows else None
    if spine.blocks:
        block = spine.blocks[0]
        if row is None or list(block.rows) != [row.id]:
            problem("blocks[0].rows", "SPN106", "the block draws the task's one row, by its id")
        if not 1 <= block.trials <= _TRIALS_MAX:
            problem("blocks[0].trials", "SPN106", f"a block runs 1 to {_TRIALS_MAX} trials")
    if row is not None and not row.name.strip():
        problem("rows[0].name", "SPN108", "this row has no name. Its name is what every readout of it is titled")
    if row is not None and not 0 <= row.reward_permille <= 1000:
        problem("rows[0].rewardPermille", "SPN106", "a reward probability is 0 to 1000 permille")
    if row is not None and not 0 <= row.reward_ms <= _REWARD_MS_MAX:
        # The board holds RW1 to this range and would refuse the start (CLAMPED).
        problem("rows[0].rewardMs", "SPN106", f"a reward opens its line for 0 to {_REWARD_MS_MAX} ms")

    bind = row.bind if row is not None else {}
    held: dict[str, str] = {}
    for kind, slots, edges in (("in", inputs, _INPUT_EDGES), ("out", outputs, _OUTPUT_EDGES)):
        for slot in slots:
            at = f"rows[0].bind.{slot}"
            name = bind.get(slot, "")
            channel = channels.get(name) if name else None
            entry: dict[str, Any] = {"slot": slot, "channel": name}
            (out.inputs if kind == "in" else out.outputs).append(entry)
            if channel is None:
                problem(at, "SPN101", f"slot {slot!r} is bound to no channel" if not name
                        else f"this rig has no channel {name!r}")
                out.blockers.append(f"slot {slot} is bound to no channel of this rig")
                continue
            if channel.type != slot_type[slot] or channel.kind == "sync":
                problem(at, "SPN102", f"{name} is a {channel.type} {channel.kind} channel; slot {slot!r} "
                        f"needs a {slot_type[slot]}" + (" other than the sync line" if channel.kind == "sync" else ""))
                out.blockers.append(f"{name} is not a {slot_type[slot]} channel")
                continue
            if name in held:
                problem(at, "SPN107", f"{name} is already slot {held[name]!r}; one channel is one slot")
            held[name] = slot
            entry["pin"] = channel.index
            if kind == "in":
                entry["activeHigh"] = channel.active_level == "high"
                entry["debounceMs"] = int(channel.debounce_ms or 0)
            named = dict(channel.edges)
            for role, edge in zip(("rise", "fall") if kind == "in" else ("on", "off"), edges):
                code = named.get(edge)
                if code is None or code not in vocab:
                    problem(at, "SPN103", f"the {edge} edge of {name} has no live strobe code. Save the "
                            "wiring on the Rig page to issue one")
                    out.blockers.append(f"the {edge} edge of {name} has no strobe code")
                else:
                    entry[role] = code

    for role, name in STRUCTURAL.items():
        if name not in vocab:
            problem(f"vocabulary.{name}", "SPN104", f"the strobe vocabulary has no {name} code. Add it on "
                    "Task > Strobes, at the number the shipped vocabulary gives it")
            out.blockers.append(f"the strobe vocabulary has no {name} code: add it on Task > Strobes")
    return out


def _shape_problems(spine: Spine, slot_type: dict[str, str], problem) -> bool:  # noqa: ANN001
    """The spine's own shape (SPN105). True when it can be lowered."""
    ok = True

    def bad(location: str, message: str) -> None:
        nonlocal ok
        ok = False
        problem(location, "SPN105", message)

    phases = spine.phases
    kinds = [p.phase for p in phases]
    if kinds.count("iti") != 1 or not kinds or kinds[-1] != "iti" or len(phases) < 2:
        bad("spine", "a spine ends in exactly one ITI, after at least one other phase: every abort goes there")
    for i, p in enumerate(phases):
        at = f"spine[{i}]"
        if p.phase not in lowering.PHASES:
            bad(f"{at}.phase", f"{p.phase!r} is not a phase of this palette {lowering.PHASES}")
            continue
        for slot in p.outputs:
            if slot_type.get(slot) != "digital_out":
                bad(f"{at}.outputs", f"{slot!r} is not an output slot")
        if p.phase == "wait" and slot_type.get(p.on or "") != "digital_in":
            bad(f"{at}.on", f"a wait moves on at an edge of an input slot; {p.on!r} is not one")
        if p.phase == "present" and p.abort_on_release is not None \
                and slot_type.get(p.abort_on_release) != "digital_in":
            bad(f"{at}.abortOnRelease", f"{p.abort_on_release!r} is not an input slot")
        if p.phase == "outcome" and slot_type.get(p.line or "") != "digital_out":
            bad(f"{at}.line", f"an outcome opens an output slot's line; {p.line!r} is not one")
        if p.phase in ("present", "delay", "iti") and p.ms is None:
            bad(f"{at}.ms", f"a {p.phase} lasts a set time; give it ms")
        for key, value in (("ms", p.ms), ("timeoutMs", p.timeout_ms)):
            if value is not None and not 0 <= value <= _MS_MAX:
                bad(f"{at}.{key}", f"a duration is 0 to {_MS_MAX} ms")
    return ok


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
        "outputs": [_public(e, ("slot", "channel", "on", "off")) for e in resolved.outputs],
        "params": list(low.params) if low else [],
        "table": ({"states": [list(s) for s in low.states], "edges": [list(e) for e in low.edges]}
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
    """One config field per parameter slot, in slot order: slot s is wire key `params[s]`."""
    if low is None:
        return []
    row = spine.rows[0] if spine.rows else None
    block = spine.blocks[0] if spine.blocks else None
    timer_of = {key: i for i, key in enumerate(low.timers) if key is not None}
    out: list[dict[str, Any]] = []
    for key in low.params:
        if key == lowering.TRIALS_KEY:
            out.append(_int_field("block_trials", key, "Trials", block.trials if block else 1,
                                  "Session", None, 1, _TRIALS_MAX,
                                  "How many trials the session runs; it ends at the start of the next."))
        elif key == lowering.REWARD_MS_KEY:
            name = row.name if row else "row"
            out.append(_int_field("reward_ms", key, f"Reward — {name}", row.reward_ms if row else 0,
                                  "Reward volume", "ms", 0, _REWARD_MS_MAX,
                                  "How long the reward line opens: the reward volume."))
        elif key == lowering.REWARD_PERMILLE_KEY:
            name = row.name if row else "row"
            out.append(_int_field("reward_permille", key, f"Reward probability — {name}",
                                  row.reward_permille if row else 1000, "Reward volume", "‰", 0, 1000,
                                  "The chance, in thousandths, that an outcome opens the line."))
        else:
            i = timer_of[key]
            p = spine.phases[i]
            wait = p.phase == "wait"
            metadata = f"wait_{i}_timeout_ms" if wait else f"{p.phase}_{i}_ms"
            label = f"{'Wait timeout' if wait else p.phase.capitalize()} (phase {i + 1})"
            default = (p.timeout_ms if wait else p.ms) or 0
            help_text = ("How long a wait lasts before it goes to the ITI." if wait else
                         "How long this phase lasts." if p.phase != "outcome" else
                         "How long the outcome lasts after the reward, before the next phase.")
            out.append(_int_field(metadata, key, label, default, "Phases", "ms", 0, _MS_MAX, help_text))
    return out


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
    params = [f'{{"{f["wireKey"]}", {f["default"]}UL, {f["min"]}UL, {f["max"]}UL}}' for f in fields]
    lines += [
        "/*  The table format this was lowered for; BoxSpine.h refuses another. */",
        f"#define SPINE_INTERP {lowering.INTERP_VERSION}",
        "",
        "/*  The state table (BoxInterp.h, THE STATE TABLE). State 0 starts a trial.",
        "    {outputs, watch, timer_min, timer_max, on_timeout, chance, on_hit,",
        "     on_miss, edge_first, edge_count, flags, outcome} */",
        f"#define SPINE_NUM_STATES {len(states)}",
        f"#define SPINE_STATES {initialiser(states)}",
        "/*  {input, edge, next} */",
        f"#define SPINE_NUM_EDGES {len(edges)}",
        f"#define SPINE_EDGES {initialiser(edges)}",
        "",
        "/*  Input bit i, in slot order: {pin, active high, debounce ms, rise code, fall code}. */",
        f"#define SPINE_NUM_INPUTS {len(inputs)}",
        f"#define SPINE_INPUTS {initialiser(inputs)}",
        "/*  Output bit j, in slot order: {pin, on code, off code}. */",
        f"#define SPINE_NUM_OUTPUTS {len(outputs)}",
        f"#define SPINE_OUTPUTS {initialiser(outputs)}",
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


def _c_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
