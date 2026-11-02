"""Pavlovian trace and delay conditioning as spine tasks (`TASKS.md#pavlovian-conditioning`).

ADR 0003's first graded paradigm, and the one place its definition lives:

    baseline  Delay, watching the lick sensor
    CS        Present, the CS on, watching licks
    trace     Delay, watching licks              (delay conditioning drops it)
    US        Outcome: the reward line on every CS+ trial, none on CS-, watching licks
    ITI

There is no response gate: the CS is followed by the US whatever the animal
does, and what it learned is read from its licks
(`ANALYTICS.md#phase-window-rates`). `phases()` is the spine with no names,
the shape a seed spine carries; `definition()` adds the CS+ and CS- rows and
their block, ready for `tasks.save`.

Plain data in, plain JSON out: nothing here reads the rig. A channel the rig
lacks (a stock box has no lick sensor or tone) is the validator's SPN101.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Phase durations, ms. Every one is a parameter (`TASKS.md#lowering`), so a
#: run overrides it per box like any other.
BASELINE_MS = 2000
CS_MS = 2000
TRACE_MS = 1000
#: The class timeout after the US: the consummatory window.
US_MS = 3000
ITI_MS = 10000

#: The phase index of the trace in `phases()`; `phases(trace=False)` lacks it.
TRACE_PHASE = 2


@dataclass(frozen=True)
class Cue:
    """A CS: a channel, and the pitch it plays at when it is a tone. `hz` None
    is a level line (a light, an odor line), switched on and off."""

    channel: str
    hz: int | None = None


def phases(trace: bool = True, *, tone: bool = True) -> dict[str, Any]:
    """The slots and the spine, and nothing named: the seed.

    `tone` makes the CS slot a `tone_out`, whose pitch each row gives; without
    it the CS is a level `digital_out` each row binds to its own channel."""
    watch = ["lick"]
    spine = [
        {"phase": "delay", "ms": BASELINE_MS, "watch": list(watch)},
        {"phase": "present", "outputs": ["cs"], "ms": CS_MS, "watch": list(watch)},
        {"phase": "delay", "ms": TRACE_MS, "watch": list(watch)},
        {"phase": "outcome", "line": "us", "ms": US_MS, "watch": list(watch)},
        {"phase": "iti", "ms": ITI_MS},
    ]
    if not trace:
        del spine[TRACE_PHASE]
    return {
        "slots": [
            {"id": "lick", "type": "digital_in"},
            {"id": "cs", "type": "tone_out" if tone else "digital_out"},
            {"id": "us", "type": "digital_out"},
        ],
        "spine": spine,
    }


def definition(
    trace: bool = True,
    *,
    lick: str = "lick_spout",
    us: str = "fluid_2",
    cs_plus: Cue = Cue("tone", 8000),
    cs_minus: Cue = Cue("tone", 2000),
    reward_ms: int = 100,
    trials: int = 60,
    task_id: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """A whole task: `phases(trace)` with a CS+ row that pays `us` on every
    trial and a CS- row that never does, drawn from one shuffle bag of five of
    each for `trials` trials. Both cues are tones, or both level lines."""
    tone = cs_plus.hz is not None
    if (cs_minus.hz is not None) != tone:
        raise ValueError("the CS+ and CS- are both tones or both level lines: they share one slot")

    def row(row_id: str, row_name: str, cue: Cue, permille: int) -> dict[str, Any]:
        out: dict[str, Any] = {"id": row_id, "name": row_name,
                               "bind": {"lick": lick, "cs": cue.channel, "us": us},
                               "rewardMs": reward_ms, "rewardPermille": permille}
        if tone:
            out["drive"] = {"cs": {"hz": cue.hz}}
        return out

    kind = "trace" if trace else "delay"
    return {
        "id": task_id or f"pavlovian_{kind}",
        "name": name or f"Pavlovian {kind.capitalize()}",
        "category": "Tasks",
        **phases(trace, tone=tone),
        "rows": [row("cs_plus", "CS+", cs_plus, 1000), row("cs_minus", "CS−", cs_minus, 0)],
        "blocks": [{"id": "b1", "rows": ["cs_plus", "cs_minus"], "select": "bag", "weights": [5, 5],
                    "trials": trials}],
        "params": {},
    }
