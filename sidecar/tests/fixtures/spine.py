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
