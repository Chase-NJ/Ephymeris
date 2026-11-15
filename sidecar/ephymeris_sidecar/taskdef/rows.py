"""Which trial rows the generator emits, decided once.

`generate.task_trials_h` writes a row into `kTrials[]` only if it can resolve
every index and code the row needs, and silently drops the rest. TSK108 ("no
presentable trial") has to ask the SAME question, or a table the generator
empties still validates clean and the session runs nothing.

So both call `resolve_row`: the generator to build the row, the validator to
count it. A row is presentable exactly when this returns something.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import TrialTypeDef


@dataclass(frozen=True)
class ResolvedRow:
    """What a row resolves to against the rig. Go-only fields are None on a no-go row."""

    odor_index: int
    port: Any = None                      # the response channel
    reward_index: int | None = None
    slot: dict[str, str] | None = None    # the vocabulary's port-slot entry


def reward_index(channels, name: str | None) -> int | None:
    """Position in the DECLARED reward list — the index into `Fluids[]`.

    The same order `BOX_FLUID_PINS` is emitted in, so index and pin describe one
    line by construction rather than by agreement. Declaration order rather than
    pin order for the reason `declared_of_kind` gives: these happen to ascend
    today, and relying on that is how the odor table went wrong.
    """
    if name is None:
        return None
    for i, channel in enumerate(channels.declared_of_kind("reward")):
        if channel.name == name:
            return i
    return None


def resolve_row(trial: TrialTypeDef, channels, vocab) -> ResolvedRow | None:
    """The row the generator would emit for `trial`, or None if it drops it."""
    # Declaration order, matching BOX_ODOR_PINS: slot i of that table is
    # `Odors[i]`, so the two must be built from the same list.
    emitters = channels.declared_of_kind("emitter")
    odor_index = next(
        (i for i, c in enumerate(emitters) if c.name == trial.odor_channel), None
    )
    if odor_index is None or trial.onset_strobe not in vocab:
        return None
    if not trial.is_go:
        return ResolvedRow(odor_index)

    port = channels.get(trial.response_channel) if trial.response_channel else None
    reward = reward_index(channels, trial.reward_channel)
    slot = vocab.port_slot(port.port_slot) if port and port.port_slot else None
    # Only a RESPONSE channel answers a trial: nothing stops a slot being
    # declared on a reward line, and its codes would then be emitted as the
    # well's own.
    if port is None or port.kind != "response" or reward is None or not slot:
        return None
    return ResolvedRow(odor_index, port, reward, slot)
