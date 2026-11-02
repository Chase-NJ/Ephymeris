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


#: Driven outputs a rig can add (`TASKS.md#driven-outputs`): (entry, pin). Pins
#: 45 and 12 are PWM pins clear of Timer2, so a tone beside them is legal.
DRIVEN_CHANNELS = {
    "light": ({"kind": "cue", "type": "pwm_out", "role": "stimulus"}, 45),
    "tone": ({"kind": "cue", "type": "tone_out", "role": "stimulus"}, 12),
    "laser": ({"kind": "cue", "type": "digital_out", "mode": "train", "role": "stimulus"}, 11),
}


#: A lick sensor (ADR 0003's `lick_spout`): an input, active HIGH as a
#: capacitive sensor is, debounced. Pin 18 is free on the shipped rig.
LICK_CHANNEL = ({"kind": "response", "type": "digital_in", "role": "port", "active_level": "high",
                 "debounce_ms": 2}, 18)


def issued_rig(driven: bool = False, lick: bool = False) -> tuple[dict, dict]:
    """(rig document, vocabulary document): the shipped rig after its first save,
    with `DRIVEN_CHANNELS` added first when `driven`, then `lick_spout` when `lick`."""
    vocab_doc = registry.default_vocabulary_document()
    doc = default_document()
    if driven:
        for name, (entry, pin) in DRIVEN_CHANNELS.items():
            doc["channels"][name] = copy.deepcopy(entry)
            doc["pins"][name] = {"index": pin}
    if lick:
        entry, pin = LICK_CHANNEL
        bits = [p["watch_bit"] for p in doc["pins"].values() if "watch_bit" in p]
        doc["channels"]["lick_spout"] = copy.deepcopy(entry)
        doc["pins"]["lick_spout"] = {"index": pin, "watch_bit": max(bits) + 1}
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


def stimulus(**edits) -> dict:
    """The driven outputs (`TASKS.md#driven-outputs`), on `issued_rig(driven=True)`:
    a poke starts a second of the light at the row's duty, the tone at its
    pitch and the laser's train, then an ITI. Two rows drive them differently;
    the dim row's 300 ms train runs out before its phase, the bright row's
    runs as long as the phase."""
    bind = {"port": "odor_port", "cue": "trial_light", "light": "light", "tone": "tone", "laser": "laser"}
    doc = {
        "id": "spine_stimulus",
        "name": "Spine Stimulus",
        "category": "Tasks",
        "slots": [
            {"id": "port", "type": "digital_in"},
            {"id": "cue", "type": "digital_out"},
            {"id": "light", "type": "pwm_out"},
            {"id": "tone", "type": "tone_out"},
            {"id": "laser", "type": "digital_out", "mode": "train"},
        ],
        "spine": [
            {"phase": "wait", "on": "port", "outputs": ["cue"]},
            {"phase": "present", "outputs": ["light", "tone", "laser"], "ms": 1000},
            {"phase": "iti", "ms": 500},
        ],
        "rows": [
            {"id": "dim", "name": "Dim", "bind": dict(bind),
             "drive": {"light": {"duty": 64}, "tone": {"hz": 2000},
                       "laser": {"hz": 20, "widthMs": 5, "ms": 300}}},
            {"id": "bright", "name": "Bright", "bind": dict(bind),
             "drive": {"light": {"duty": 255}, "tone": {"hz": 4000},
                       "laser": {"hz": 30, "widthMs": 10, "ms": 0}}},
        ],
        "blocks": [{"id": "b1", "rows": ["dim", "bright"], "trials": 3}],
        "params": {},
    }
    doc.update(edits)
    return doc


def ratio(**edits) -> dict:
    """An operant ratio schedule: count the right well's pokes, pay at the N-th,
    a short ITI, again. FR-5 as written; `counter` edits make it VR or PR."""
    doc = {
        "id": "spine_fr",
        "name": "Spine FR",
        "category": "Tasks",
        "slots": [
            {"id": "lever", "type": "digital_in"},
            {"id": "light", "type": "digital_out"},
            {"id": "reward", "type": "digital_out"},
        ],
        "spine": [
            {"phase": "counter", "on": "lever", "count": 5, "outputs": ["light"]},
            {"phase": "outcome", "line": "reward", "ms": 0},
            {"phase": "iti", "ms": 500},
        ],
        "rows": [
            {"id": "r1", "name": "Lever", "bind": {"lever": "right_well", "light": "trial_light", "reward": "fluid_2"},
             "rewardMs": 100, "rewardPermille": 1000},
        ],
        "blocks": [{"id": "b1", "rows": ["r1"], "trials": 50}],
        "params": {},
    }
    counter = edits.pop("counter", None)
    if counter is not None:
        doc["spine"][0] = {"phase": "counter", "on": "lever", "outputs": ["light"], **counter}
    doc.update(edits)
    return doc


def fixed_ratio(n: int = 5, **edits) -> dict:
    return ratio(**{"id": f"spine_fr_{n}", "name": f"Spine FR {n}", "counter": {"count": n}, **edits})


def variable_ratio(low: int = 1, high: int = 9, **edits) -> dict:
    """VR-(low+high)/2: N drawn uniformly from [low, high] at each reward."""
    return ratio(**{"id": "spine_vr", "name": "Spine VR", "counter": {"count": low, "countMax": high}, **edits})


#: Richardson and Roberts (1996)'s progressive ratio, its first ten steps.
RICHARDSON_ROBERTS = [1, 2, 4, 6, 9, 12, 15, 20, 25, 32]


def progressive_ratio(limit_ms: int = 2000, **edits) -> dict:
    """PR: the k-th reward needs the k-th ratio; a ratio left unfinished for
    `limit_ms` is an omission that ends the session, after its ITI."""
    counter = {"ratios": list(RICHARDSON_ROBERTS), "timeoutMs": limit_ms, "endsSession": True}
    return ratio(**{"id": "spine_pr", "name": "Spine PR", "counter": counter, **edits})


def held_trial(**edits) -> dict:
    """Self-initiated, with every early exit: a poke within 5 s (or an abort
    before the stimulus), held 300 ms (a release is hold broken), odor 1 while
    the poke is held (a release aborts during sampling), a Delay that a poke at
    the right well aborts, a reward, an ITI."""
    doc = tracer(**{"id": "spine_held", "name": "Spine Held", **edits})
    doc["slots"].append({"id": "early", "type": "digital_in"})
    doc["spine"] = [
        {"phase": "wait", "on": "port", "outputs": ["cue"], "timeoutMs": 5000},
        {"phase": "hold", "on": "port", "ms": 300, "outputs": ["cue"]},
        {"phase": "present", "outputs": ["cue", "sample"], "ms": 500, "abortOnRelease": "port"},
        {"phase": "delay", "ms": 400, "abortOnEnter": "early"},
        {"phase": "outcome", "line": "reward", "ms": 0},
        {"phase": "iti", "ms": 1000},
    ]
    doc["rows"][0]["bind"]["early"] = "right_well"
    return doc


# --- blocks (#103) ----------------------------------------------------------------


def _afc_row(row_id: str, name: str, odor: str, entries: dict[str, tuple[str, int]]) -> dict:
    """A 2AFC row on `odor`: each well in `entries` maps to (class, permille);
    a correct entry pays that well's line, held."""
    bind = {"port": "odor_port", "left": "left_well", "right": "right_well", "cue": "trial_light",
            "reward_l": "fluid_1", "reward_r": "fluid_2", "sample": odor}
    entry_map: dict = {"timeout": {"outcome": "omission"}}
    for well, (outcome, permille) in entries.items():
        entry_map[well] = ({"outcome": outcome, "line": f"reward_{well[0]}", "rewardPermille": permille,
                            "hold": True} if outcome == "correct" else {"outcome": outcome})
    return {"id": row_id, "name": name, "bind": bind, "rewardMs": 100, "rewardPermille": 1000,
            "map": entry_map}


def reversal(**edits) -> dict:
    """ADR 0003's reversal: block a pays odor 1 at the right well and odor 2 at
    the left, repeats an error once, and ends at 8 correct of the last 10; block
    b pays them the other way round for 4 trials, and the session ends."""
    doc = two_afc(**{"id": "spine_reversal", "name": "Spine Reversal", **edits})
    doc["rows"] += [
        _afc_row("odor_1_rev", "Odor 1, reversed", "odor_line_1",
                 {"left": ("correct", 1000), "right": ("wrong_response", 0)}),
        _afc_row("odor_2_rev", "Odor 2, reversed", "odor_line_2",
                 {"right": ("correct", 1000), "left": ("wrong_response", 0)}),
    ]
    doc["blocks"] = [
        {"id": "a", "rows": ["odor_1", "odor_2"], "criterion": {"correct": 8, "of": 10}, "correction": 1},
        {"id": "b", "rows": ["odor_1_rev", "odor_2_rev"], "trials": 4},
    ]
    return doc


def bandit(**edits) -> dict:
    """ADR 0003's two-armed bandit on one stimulus: both wells are correct, the
    left paying 80% of the time in block a and 20% in block b, and the right the
    other way round. The blocks loop, each lasting 40-60 trials; the session's
    `sessionTrials` caps it."""
    doc = two_afc(**{"id": "spine_bandit", "name": "Spine Bandit", **edits})
    doc["rows"] = [
        _afc_row("left_good", "Left good", "odor_line_1", {"left": ("correct", 800), "right": ("correct", 200)}),
        _afc_row("right_good", "Right good", "odor_line_1", {"left": ("correct", 200), "right": ("correct", 800)}),
    ]
    doc["blocks"] = [
        {"id": "a", "rows": ["left_good"], "trials": 40, "trialsMax": 60},
        {"id": "b", "rows": ["right_good"], "trials": 40, "trialsMax": 60, "next": "a"},
    ]
    doc["sessionTrials"] = 130
    return doc
