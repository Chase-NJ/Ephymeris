"""The shipped rig after its first wiring save.

The shipped channel set names no edge codes: a machine's first wiring save
issues them (`TASKS.md#edge-codes`). So the rig here is the shipped one after
that save, planned by the real allocator against the shipped vocabulary, and
every code number is read back from that vocabulary, never written here.
"""

from __future__ import annotations

import copy

from ephymeris_sidecar.hardware.store import default_document
from ephymeris_sidecar.rig import allocation, registry


#: Driven outputs a rig can add (`TASKS.md#driven-outputs`): (entry, pin). Pins
#: 45 and 12 are PWM pins clear of Timer2, so a tone beside them is legal.
DRIVEN_CHANNELS = {
    "light": ({"kind": "cue", "type": "pwm_out", "role": "stimulus"}, 45),
    "tone": ({"kind": "cue", "type": "tone_out", "role": "stimulus"}, 12),
    "laser": ({"kind": "cue", "type": "digital_out", "mode": "train", "role": "stimulus"}, 11),
}


def issued_rig(driven: bool = False) -> tuple[dict, dict]:
    """(rig document, vocabulary document): the shipped rig after its first
    save, with `DRIVEN_CHANNELS` added first when `driven`."""
    vocab_doc = registry.default_vocabulary_document()
    doc = default_document()
    if driven:
        for name, (entry, pin) in DRIVEN_CHANNELS.items():
            doc["channels"][name] = copy.deepcopy(entry)
            doc["pins"][name] = {"index": pin}
    rig, allocations = allocation.plan(doc, registry.Vocabulary(vocab_doc))
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
