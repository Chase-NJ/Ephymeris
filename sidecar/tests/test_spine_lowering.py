"""Lowering a spine into BoxInterp.h's state table — `taskdef/lowering.py`.

The generator's half of ADR 0003's "lowered to a state table". The table is
what the board walks and what replay replays, so it is pinned here against a
worked example written out by hand from BoxInterp.h's "Lowering the first
phases", and held to both interpreters by the differential test.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.taskdef import lowering

N = lowering.NONE
TRACER = [
    {"phase": "wait", "on": "port", "outputs": ["cue"]},
    {"phase": "present", "outputs": ["cue", "sample"], "ms": 1000, "abortOnRelease": "port"},
    {"phase": "delay", "ms": 500},
    {"phase": "outcome", "line": "reward", "ms": 0},
    {"phase": "iti", "ms": 3000},
]


def test_the_tracer_spine_lowers_to_the_worked_table():
    low = lowering.lower(TRACER, inputs=["port"], outputs=["cue", "sample", "reward"])
    #        outputs watch tmin tmax  on_to chance hit miss first count flags outcome
    assert low.states == (
        (0b001, 1, N, N, N, N, N, N, 0, 1, lowering.STARTS_TRIAL, 0),  # wait for the port, cue on
        (0b011, 1, 1, 1, 2, N, N, N, 1, 1, 0, 0),                      # present; a release aborts
        (0, 0, 2, 2, 3, N, N, N, 0, 0, 0, 0),                          # delay
        (0, 0, N, N, N, 6, 4, 5, 0, 0, 0, lowering.OUTCOME_CORRECT),   # outcome: draw the reward
        (0b100, 0, 5, 5, 5, N, N, N, 0, 0, 0, 0),                      # the reward line open
        (0, 0, 3, 3, 6, N, N, N, 0, 0, 0, 0),                          # the class timeout
        (0, 0, 4, 4, 0, N, N, N, 0, 0, 0, 0),                          # ITI, back to the trial
    )
    assert low.edges == ((0, lowering.RISE, 1), (0, lowering.FALL, 6))
    assert low.params == ("NT", "T1", "T2", "T3", "T4", "RW1", "RP1")


def test_the_lowered_table_is_one_replay_accepts():
    low = lowering.lower(TRACER, inputs=["port"], outputs=["cue", "sample", "reward"])
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states],
                     edges=[rp.EdgeRow(*e) for e in low.edges])
    assert table.slots_used() == len(low.params)


def test_a_wait_timeout_goes_to_the_iti_and_takes_its_own_slot():
    spine = [{"phase": "wait", "on": "port", "timeoutMs": 4000}, {"phase": "iti", "ms": 100}]
    low = lowering.lower(spine, inputs=["port"], outputs=[])
    assert low.params == ("NT", "T0", "T1")
    assert low.states[0][2:5] == (1, 1, 1), "timer T0, out to the ITI"


def test_an_outcome_keeps_its_outputs_high_through_the_reward():
    """A phase's outputs are HIGH for the whole phase (TASKS.md#what-a-spine-task-holds).
    An outcome that dropped them for the reward would strobe the cue off and on
    again mid-phase, and replay, reading the same table, would never object."""
    spine = [{"phase": "wait", "on": "port"},
             {"phase": "outcome", "line": "reward", "outputs": ["cue"], "ms": 10},
             {"phase": "iti", "ms": 10}]
    low = lowering.lower(spine, inputs=["port"], outputs=["cue", "reward"])
    chance, reward, settle = low.states[1], low.states[2], low.states[3]
    assert chance[0] == 0, "a chance state takes no time and drives nothing"
    assert reward[0] == 0b11, "the reward line opens beside the phase's own outputs"
    assert settle[0] == 0b01


def test_no_output_a_phase_names_ever_drops_while_in_that_phase():
    """The property the outcome bug broke, over random spines: every state a
    phase rests in drives every output the phase names."""
    import random

    rng = random.Random(98)
    inputs, outputs = ["a", "b"], ["x", "y", "z", "w"]
    for _ in range(500):
        spine = []
        for _ in range(rng.randint(1, 5)):
            kind = rng.choice(("wait", "present", "delay", "outcome"))
            p = {"phase": kind, "outputs": rng.sample(outputs, rng.randint(0, 3)), "ms": 5}
            if kind == "wait":
                p["on"] = rng.choice(inputs)
            if kind == "present" and rng.random() < 0.5:
                p["abortOnRelease"] = rng.choice(inputs)
            if kind == "outcome":
                p["line"] = rng.choice(outputs)
            spine.append(p)
        spine.append({"phase": "iti", "ms": 5, "outputs": rng.sample(outputs, rng.randint(0, 1))})
        low = lowering.lower(spine, inputs=inputs, outputs=outputs)
        for s, row in enumerate(low.states):
            if row[5] != lowering.NONE:
                continue  # a chance state never rests
            named = spine[low.phases[s]].get("outputs", [])
            mask = sum(1 << outputs.index(o) for o in named)
            assert row[0] & mask == mask, (spine, s)


def test_a_spine_lowering_refuses_is_not_a_table():
    with pytest.raises(lowering.LoweringError):
        lowering.lower([{"phase": "wait", "on": "port"}], inputs=["port"], outputs=[])  # no ITI
    with pytest.raises(lowering.LoweringError):
        lowering.lower(TRACER, inputs=[], outputs=["cue", "sample", "reward"])  # "port" unresolved
