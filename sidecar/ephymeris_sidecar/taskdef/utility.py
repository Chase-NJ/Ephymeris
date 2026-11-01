"""The box utility, generated from the rig — `TASKS.md#the-box-utility`.

`BOX_Utility` used to be a hand-written sketch that knew this lab's box by
heart: twelve odor lines called O1..O12, four fluid lines F1..F4, three beams
called odor port / left well / right well, and a `task.json` whose Debug Mode
grids listed exactly those. A rig with a relabelled line drove the right pin
under the wrong name; a rig with a different count did not fit at all.

Now the logic lives once in the firmware library (`BoxUtility.h`, host-tested)
and everything it knows about THIS box is generated here from the channel set
-- each channel's type, mode, role and active level, never its kind -- in two
halves that must agree and so are written together:

* `UtilityChannels.h` — one row per output and per input: the channel name
  (the command token and STATUS key), the Rig page's label, the pin, and an
  output's role group and drive, or an input's active level.
* `task.json` — the sketch folder's own rig-independent profile (buttons, the
  pulse-width select, legacy names) with the rig half merged in: one Debug Mode
  grid row per output (a driven one with its setting), a telemetry field per
  input, and the identify pair.

Nothing here names a channel; `test_box_utility.py` fails if anything does.

A sketch opts in by including `UtilityChannels.h`, exactly as one opts into
rig pins by including `TaskPins.h` (`taskdef/bundled.py`), and is rebuilt on
the same triggers: every start, every wiring change, every vocabulary edit.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from ..rig import registry

#: The header a sketch includes to declare it is a box utility.
UTILITY_HEADER = "UtilityChannels.h"

#: Output groups, in the order the table and the self-test take them: the
#: channel-set roles each holds, and the `BoxUtilGroup` it becomes. Read from
#: `role` and `type`, never from `kind` (ADR 0003 retires it). A role not named
#: here lands in the cue group, so every output appears; `sync` never does: a
#: pulse on it is an edge in a recording, and the trial runner owns that line.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("BOX_UTIL_STIMULUS", ("stimulus",)),
    ("BOX_UTIL_REWARD", ("reward",)),
    ("BOX_UTIL_CUE", ("cue",)),
    ("BOX_UTIL_ROUTING", ("routing",)),
)
_CUE_GROUP = "BOX_UTIL_CUE"
_ROLE_GROUP = {role: group for group, roles in GROUPS for role in roles}

#: Debug Mode grids: id, label, the groups they hold. `fluids` keeps its id
#: because Prime finds the reward grid by it (`UtilityControls.tsx`).
GRIDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("fluids", "Reward lines", ("BOX_UTIL_REWARD",)),
    ("aux", "Cues & other lines", ("BOX_UTIL_CUE", "BOX_UTIL_ROUTING")),
    ("emitters", "Stimulus lines", ("BOX_UTIL_STIMULUS",)),
)


def wants_utility(sketch_dir: Path) -> bool:
    """Whether this sketch is a box utility to be generated for the rig.

    Read from the `.ino` itself, for the reason `bundled.wants_pinning` gives:
    a manifest would be a second declaration of the same thing.
    """
    ino = Path(sketch_dir) / f"{Path(sketch_dir).name}.ino"
    try:
        return f'#include "{UTILITY_HEADER}"' in ino.read_text(encoding="utf-8")
    except OSError:
        return False


def group_of(channel: registry.Channel) -> str:
    """The `BoxUtilGroup` an output is tested and shown with, by its role."""
    return _ROLE_GROUP.get(channel.role, _CUE_GROUP)


def is_output(channel: registry.Channel) -> bool:
    """Whether the utility drives this channel: any output type but the sync
    line's (by role, or by the kind the trial runner finds it by)."""
    return (registry.TYPE_DIRECTION.get(channel.type) == "out"
            and channel.role != "sync" and channel.kind != "sync")


def outputs(channels: registry.ChannelMap) -> list[registry.Channel]:
    """Every output the utility drives, grouped by role, in DECLARATION order
    within a group — the order the Rig page lists them."""
    outs = [c for c in channels if is_output(c)]
    return [c for group, _ in GROUPS for c in outs if group_of(c) == group]


def inputs(channels: registry.ChannelMap) -> list[registry.Channel]:
    """Every `digital_in`, whatever its role, in declaration order."""
    return [c for c in channels if c.type == "digital_in"]


#: A driven output's `BoxUtilDrive`, and what the utility plays on it while it
#: is on, which its label says (`TASKS.md#driven-outputs`). A plain output is a
#: level line.
DRIVES: dict[str | None, tuple[str, str | None]] = {
    None: ("BOX_UTIL_LEVEL", None),
    "pwm": ("BOX_UTIL_PWM", None),
    "tone": ("BOX_UTIL_TONE", "test tone"),
    "train": ("BOX_UTIL_TRAIN", "test train"),
}

#: The one setting each drive has in Debug Mode (`TASKS.md#the-box-utility`):
#: its label, its STATUS suffix (`<channel>.<suffix>=<n>`), the verb that sets
#: it, and the values offered. The board's own default (`BoxUtility.h`) is
#: among them, and the board refuses anything outside its limits. A train's
#: width stays 5 ms, shorter than the period of every rate offered.
SETTINGS: dict[str, tuple[str, str, str, tuple[tuple[str, int], ...]]] = {
    "pwm": ("Duty", "duty", "DUTY", (("10%", 26), ("25%", 64), ("50%", 128), ("100%", 255))),
    "tone": ("Pitch", "hz", "HZ", (("500 Hz", 500), ("1 kHz", 1000), ("2 kHz", 2000),
                                   ("4 kHz", 4000), ("8 kHz", 8000))),
    "train": ("Rate", "hz", "HZ", (("5 Hz", 5), ("10 Hz", 10), ("20 Hz", 20), ("40 Hz", 40))),
}


def row_label(channel: registry.Channel) -> str:
    """The Rig page's label, with the port a reward line serves when known —
    "which well does fluid 2 feed?" is the question priming is for — or what a
    driven output plays while it is on."""
    serves = channel.serves or channel.well
    if group_of(channel) == "BOX_UTIL_REWARD" and serves:
        return f"{channel.label} · {serves.replace('_', ' ')}"
    test = DRIVES[channel.drive][1]
    return f"{channel.label} · {test}" if test else channel.label


def setting(channel: registry.Channel) -> dict[str, Any] | None:
    """A driven output's Debug Mode setting, or None for a level line."""
    if channel.drive is None:
        return None
    label, suffix, verb, values = SETTINGS[channel.drive]
    return {
        "label": label,
        "state": f"{channel.name}.{suffix}",
        "options": [{"label": text, "value": str(n), "command": f"{verb} {channel.name} {n}"}
                    for text, n in values],
    }


def utility_channels_h(sketch_name: str) -> str:
    """The channel table for `BoxUtility.h`, from the rig in force."""
    channels = registry.channels()
    outs = outputs(channels)
    ins = inputs(channels)

    out_rows = [
        f'  {{{_c(c.name)}, {_c(row_label(c))}, {c.index}, {group_of(c)}, {DRIVES[c.drive][0]}}}'
        for c in outs
    ]
    in_rows = [f"  {{{_c(c.name)}, {_c(c.label)}, {c.index}, {1 if c.active_level == 'high' else 0}}}"
               for c in ins]
    if not in_rows:
        # A zero-length array is not C++; the engine reads NUM_INPUTS, not this.
        in_rows = ['  {"", "", -1, 0}']
    # Every key, its "=0" and a space, and a driven output's setting key with a
    # five-digit value, plus the fixed tail, with room to spare: a STATUS line
    # truncated mid-key would light the wrong row.
    status_bytes = (96 + sum(len(c.name) + 4 for c in outs + ins)
                    + sum(len(c.name) + 12 for c in outs if c.drive is not None))

    lines = [
        "/*  GENERATED by Ephymeris -- do not edit.",
        "",
        "    The box utility's channel table, from THIS RIG'S wiring and labels",
        "    (docs/TASKS.md#the-box-utility). Rewritten whenever the wiring changes;",
        "    an edit here is lost at the next change without a word.",
        "",
        f"    Sketch:  {sketch_name}",
        f"    Wiring:  {channels.pinout_id} ({channels.content_hash()})",
        "*/",
        "",
        "#ifndef UTILITY_CHANNELS_H",
        "#define UTILITY_CHANNELS_H",
        "",
        f"#define BOX_UTILITY_NUM_OUTPUTS {len(outs)}",
        "#define BOX_UTILITY_OUTPUTS { \\",
        *(row + (", \\" if i < len(out_rows) - 1 else " \\") for i, row in enumerate(out_rows)),
        "}",
        f"#define BOX_UTILITY_NUM_INPUTS {len(ins)}",
        "#define BOX_UTILITY_INPUTS { \\",
        *(row + (", \\" if i < len(in_rows) - 1 else " \\") for i, row in enumerate(in_rows)),
        "}",
        "/*  tone() is linked only for a rig with a tone output. */",
        f"#define BOX_UTILITY_HAS_TONE {1 if any(c.drive == 'tone' for c in outs) else 0}",
        f"#define BOX_UTILITY_STATUS_BYTES {status_bytes}",
        "",
        "#endif // UTILITY_CHANNELS_H",
        "",
    ]
    return "\n".join(lines)


def utility_profile(template: dict[str, Any]) -> dict[str, Any]:
    """The sketch folder's own `task.json`, with the rig half merged in.

    The template keeps what does not depend on the box (buttons, the pulse
    select, legacy names, the common telemetry fields); this adds a grid per
    group of outputs (a driven output's row with its setting), a telemetry field
    per input, and an identify pair on the first cue that is a plain level
    line. Grids the template already declares under the same id are replaced,
    so regenerating is idempotent.
    """
    channels = registry.channels()
    profile = copy.deepcopy(template)
    grid_ids = {grid_id for grid_id, _, _ in GRIDS}
    controls = [c for c in profile.get("controls", []) if c.get("id") not in grid_ids]

    outs = outputs(channels)
    for grid_id, label, groups in GRIDS:
        rows = []
        for c in outs:
            if group_of(c) not in groups:
                continue
            row: dict[str, Any] = {
                "label": row_label(c),
                "state": c.name,
                "toggle": f"TOGGLE {c.name}",
                "pulse": f"PULSE {c.name}",
                "kind": c.kind,  # the colour family Debug Mode draws it in
            }
            if (own := setting(c)) is not None:
                row["setting"] = own
            rows.append(row)
        if rows:
            controls.append({"id": grid_id, "type": "grid", "label": label, "channels": rows})
    profile["controls"] = controls

    telemetry = profile.setdefault("telemetry", {"match": "STATUS", "fields": []})
    input_keys = {c.name for c in inputs(channels)}
    fields = [f for f in telemetry.get("fields", []) if f.get("key") not in input_keys]
    fields += [{"key": c.name, "label": c.label} for c in inputs(channels)]
    telemetry["fields"] = fields

    # Identify lights a box while animals are placed into it, so never a cue
    # that plays a tone or runs a train.
    cue = next((c for c in outs if c.role == "cue" and c.drive is None), None)
    if cue is not None:
        profile["identify"] = {"on": f"ON {cue.name}", "off": f"OFF {cue.name}"}
    else:
        profile.pop("identify", None)
    return profile


def _c(text: str) -> str:
    """A C string literal for `text`: UTF-8 bytes, quotes and backslashes
    escaped, anything unprintable as a three-digit octal escape (always three
    digits, so a following digit can never be read into it)."""
    out = []
    for byte in text.encode("utf-8"):
        ch = chr(byte)
        if ch in '"\\':
            out.append("\\" + ch)
        elif 32 <= byte < 127:
            out.append(ch)
        else:
            out.append(f"\\{byte:03o}")
    return '"' + "".join(out) + '"'
