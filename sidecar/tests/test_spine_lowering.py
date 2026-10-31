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


def test_a_spine_lowering_refuses_is_not_a_table():
    with pytest.raises(lowering.LoweringError):
        lowering.lower([{"phase": "wait", "on": "port"}], inputs=["port"], outputs=[])  # no ITI
    with pytest.raises(lowering.LoweringError):
        lowering.lower(TRACER, inputs=[], outputs=["cue", "sample", "reward"])  # "port" unresolved
