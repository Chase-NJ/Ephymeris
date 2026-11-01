"""A spine task and a rig that can run one.

A spine strobes its channels' edge codes, and the shipped channel set names
none: a machine's first wiring save issues them (`TASKS.md#edge-codes`). So the
rig here is the shipped one after that save, planned by the real allocator
against the shipped vocabulary, and every code number is read back from that
vocabulary, never written here.
"""

from __future__ import annotations

import copy

from ephymeris_sidecar.hardware.store import default_document
from ephymeris_sidecar.rig import allocation, registry


def issued_rig() -> tuple[dict, dict]:
    """(rig document, vocabulary document): the shipped rig after its first save."""
    vocab_doc = registry.default_vocabulary_document()
    rig, allocations = allocation.plan(default_document(), registry.Vocabulary(vocab_doc))
    return rig, allocation.issue(vocab_doc, allocations)


def install(rig: dict | None = None, vocab: dict | None = None) -> None:
    """Put `rig` and `vocab` in force (the issued rig by default)."""
    if rig is None and vocab is None:
        rig, vocab = issued_rig()
    registry.set_rig_source(None if rig is None else (lambda: copy.deepcopy(rig)))
    registry.set_vocabulary_source(None if vocab is None else (lambda: copy.deepcopy(vocab)))


def uninstall() -> None:
    registry.set_rig_source(None)
    registry.set_vocabulary_source(None)


def tracer(**edits) -> dict:
    """The tracer: wait for a poke with the light on, present odor 1 while the
    poke is held, a delay, a reward on the right well's line, an ITI."""
    doc = {
        "id": "spine_tracer",
        "name": "Spine Tracer",
        "category": "Tasks",
        "slots": [
            {"id": "port", "type": "digital_in"},
            {"id": "cue", "type": "digital_out"},
            {"id": "sample", "type": "digital_out"},
            {"id": "reward", "type": "digital_out"},
        ],
        "spine": [
            {"phase": "wait", "on": "port", "outputs": ["cue"]},
            {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
            {"phase": "delay", "ms": 500},
            {"phase": "outcome", "line": "reward", "ms": 0},
            {"phase": "iti", "ms": 3000},
        ],
        "rows": [
            {
                "id": "r1",
                "name": "Odor 1",
                "bind": {"port": "odor_port", "cue": "trial_light", "sample": "odor_line_1", "reward": "fluid_2"},
                "rewardMs": 100,
                "rewardPermille": 1000,
            }
        ],
        "blocks": [{"id": "b1", "rows": ["r1"], "trials": 20}],
        "params": {},
    }
    doc.update(edits)
    return doc


def two_afc(**edits) -> dict:
    """Odor 2AFC: odor 1 pays at the right well, odor 2 at the left, each only
    when the well is held; the other well is a wrong response."""
    bind = {"port": "odor_port", "left": "left_well", "right": "right_well", "cue": "trial_light",
            "reward_l": "fluid_1", "reward_r": "fluid_2"}

    def row(row_id: str, name: str, odor: str, correct: str, wrong: str, line: str) -> dict:
        return {
            "id": row_id,
            "name": name,
            "bind": dict(bind, sample=odor),
            "rewardMs": 100,
            "rewardPermille": 1000,
            "map": {
                correct: {"outcome": "correct", "line": line, "rewardPermille": 1000, "hold": True},
                wrong: {"outcome": "wrong_response"},
                "timeout": {"outcome": "omission"},
            },
        }

    doc = {
        "id": "spine_2afc",
        "name": "Spine 2AFC",
        "category": "Tasks",
        "slots": [
            {"id": "port", "type": "digital_in"},
            {"id": "left", "type": "digital_in"},
            {"id": "right", "type": "digital_in"},
            {"id": "cue", "type": "digital_out"},
            {"id": "sample", "type": "digital_out"},
            {"id": "reward_l", "type": "digital_out"},
            {"id": "reward_r", "type": "digital_out"},
        ],
        "spine": [
            {"phase": "wait", "on": "port", "outputs": ["cue"]},
            {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
            {"phase": "response", "responses": ["left", "right"], "ms": 5000, "holdMs": 200},
            {"phase": "outcome", "ms": 0},
            {"phase": "iti", "ms": 3000},
        ],
        "rows": [
            row("odor_1", "Odor 1", "odor_line_1", "right", "left", "reward_r"),
            row("odor_2", "Odor 2", "odor_line_2", "left", "right", "reward_l"),
        ],
        "blocks": [{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": 20}],
        "params": {},
    }
    doc.update(edits)
    return doc


def go_no_go(**edits) -> dict:
    """Go/no-go: odor 1 asks for a poke at the right well, which pays; odor 2
    asks the animal to withhold, and a poke there is a false alarm."""
    bind = {"port": "odor_port", "resp": "right_well", "cue": "trial_light", "reward": "fluid_2"}
    doc = {
        "id": "spine_go_no_go",
        "name": "Spine Go No-Go",
        "category": "Tasks",
        "slots": [
            {"id": "port", "type": "digital_in"},
            {"id": "resp", "type": "digital_in"},
            {"id": "cue", "type": "digital_out"},
            {"id": "sample", "type": "digital_out"},
            {"id": "reward", "type": "digital_out"},
        ],
        "spine": [
            {"phase": "wait", "on": "port", "outputs": ["cue"]},
            {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000},
            {"phase": "response", "responses": ["resp"], "ms": 3000},
            {"phase": "outcome", "ms": 0},
            {"phase": "iti", "ms": 3000},
        ],
        "rows": [
            {"id": "go", "name": "Go", "bind": dict(bind, sample="odor_line_1"),
             "rewardMs": 100, "rewardPermille": 1000,
             "map": {"resp": {"outcome": "correct", "line": "reward", "rewardPermille": 1000},
                     "timeout": {"outcome": "omission"}}},
            {"id": "no_go", "name": "No-go", "bind": dict(bind, sample="odor_line_2"),
             "rewardMs": 100, "rewardPermille": 1000,
             "map": {"resp": {"outcome": "false_alarm"}, "timeout": {"outcome": "withheld"}}},
        ],
        "blocks": [{"id": "b1", "rows": ["go", "no_go"], "trials": 20}],
        "params": {},
    }
    doc.update(edits)
    return doc
