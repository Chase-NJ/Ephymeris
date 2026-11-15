"""The wiring rules, RIG101-RIG107 and RIG109 (TASKS.md#wiring-rules).

They judge a COMPOSED `ChannelMap`, never the file, so a problem is reported
once whichever half of the wiring caused it. Two callers: `hardware/service.py`
reports them against a draft, and `hardware/store.py` runs them at load, so a
stored file that breaks one is never put in force.
"""

from __future__ import annotations

from typing import Any

from . import registry


def rule_problems(document: Any) -> list[tuple[str, str, str]]:
    """(code, location, message) for every wiring rule a document that passed
    the schema breaks, against the vocabulary in force."""
    try:
        chans = registry.ChannelMap(*registry.split_rig(document))
    except (KeyError, TypeError) as exc:  # pragma: no cover - the schema catches these
        return [("RIG101", "wiring.json", str(exc))]

    vocab = registry.vocabulary()
    return [
        (code, loc, msg)
        for code, pairs in (
            ("RIG101", chans.disagreements()),
            ("RIG102", chans.pin_problems()),
            ("RIG103", chans.duplicate_pins()),
            ("RIG104", chans.slot_problems(vocab)),
            ("RIG105", chans.sync_problems()),
            ("RIG106", chans.onset_problems(vocab)),
            ("RIG107", chans.edge_problems(vocab)),
            ("RIG109", chans.drive_problems()),
        )
        for loc, msg in pairs
    ]
