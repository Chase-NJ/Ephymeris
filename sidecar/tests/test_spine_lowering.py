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
ABORT_BEFORE, ABORT_DURING = (lowering.OUTCOME_CLASSES.index(name) + 1
                              for name in ("abort_before_stimulus", "abort_during_sampling"))
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
        (0, 0, 4, 4, 0, N, N, N, 0, 0, 0, ABORT_DURING),               # the abort's end: an ITI, marked
    )
    assert low.edges == ((0, lowering.RISE, 1), (0, lowering.FALL, 7))
    assert low.params == ("NT", "T1", "T2", "T3", "T4", "RW1", "RP1")
    assert low.phases == (0, 1, 2, 3, 3, 3, 4, 4) and low.rows == (0, 0, 0, 0, 0, 0, 0, None)
    assert low.counter is None


def test_the_lowered_table_is_one_replay_accepts():
    low = lowering.lower(TRACER, inputs=["port"], outputs=["cue", "sample", "reward"])
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states],
                     edges=[rp.EdgeRow(*e) for e in low.edges])
    assert table.slots_used() == len(low.params)


def test_a_wait_timeout_goes_to_an_end_and_takes_its_own_slot():
    """Before any Present no trial was offered: the timeout is an abort before
    the stimulus. From the first Present on, the animal was asked: an omission."""
    spine = [{"phase": "wait", "on": "port", "timeoutMs": 4000},
             {"phase": "present", "ms": 10},
             {"phase": "wait", "on": "port", "edge": "exit", "timeoutMs": 4000},
             {"phase": "iti", "ms": 100}]
    low = lowering.lower(spine, inputs=["port"], outputs=[])
    assert low.params == ("NT", "T0", "T1", "T2", "T3")
    assert low.states[0][2:5] == (1, 1, 4), "timer T0, out to its end"
    assert low.states[2][2:5] == (3, 3, 5)
    assert [row[11] for row in low.states[4:]] == [ABORT_BEFORE, OMISSION]
    assert all(row[2:5] == (4, 4, 0) for row in low.states[3:]), "each end is the ITI"


# --- Hold, Wait on an exit, aborts and the Counter (#102) ----------------------


def test_a_hold_moves_on_after_its_time_and_a_release_is_hold_broken():
    spine = [{"phase": "wait", "on": "port", "outputs": ["cue"]},
             {"phase": "hold", "on": "port", "ms": 300, "outputs": ["cue"]},
             {"phase": "present", "outputs": ["sample"], "ms": 500},
             {"phase": "iti", "ms": 100}]
    low = lowering.lower(spine, inputs=["port"], outputs=["cue", "sample"])
    assert low.params == ("NT", "T1", "T2", "T3")
    #        outputs watch tmin tmax  on_to chance hit miss first count flags outcome
    assert low.states == (
        (0b01, 1, N, N, N, N, N, N, 0, 1, lowering.STARTS_TRIAL, 0),  # 0 wait for the port
        (0b01, 1, 1, 1, 2, N, N, N, 1, 1, 0, 0),                      # 1 hold it for T1
        (0b10, 0, 2, 2, 3, N, N, N, 0, 0, 0, 0),                      # 2 present
        (0, 0, 3, 3, 0, N, N, N, 0, 0, 0, 0),                         # 3 ITI
        (0, 0, 3, 3, 0, N, N, N, 0, 0, 0, HOLD_BROKEN),               # 4 let go early
    )
    assert low.edges == ((0, lowering.RISE, 1), (0, lowering.FALL, 4))


def test_a_wait_on_an_exit_moves_on_at_the_fall():
    spine = [{"phase": "wait", "on": "port", "edge": "exit"}, {"phase": "iti", "ms": 1}]
    assert lowering.lower(spine, inputs=["port"], outputs=[]).edges == ((0, lowering.FALL, 1),)


def test_present_and_delay_abort_on_either_edge_and_the_class_says_where():
    spine = [{"phase": "delay", "ms": 100, "abortOnEnter": "lick"},
             {"phase": "present", "outputs": ["sample"], "ms": 500, "abortOnRelease": "port",
              "abortOnEnter": "lick"},
             {"phase": "delay", "ms": 100, "abortOnRelease": "port"},
             {"phase": "iti", "ms": 100}]
    low = lowering.lower(spine, inputs=["port", "lick"], outputs=["sample"])
    ends = {s: row[11] for s, row in enumerate(low.states) if row[11]}
    assert ends == {4: ABORT_BEFORE, 5: ABORT_DURING}, "one end per class, after the ITI"
    assert low.edges == ((1, lowering.RISE, 4),
                         (0, lowering.FALL, 5), (1, lowering.RISE, 5),
                         (0, lowering.FALL, 5))
    assert [low.states[s][1] for s in range(3)] == [0b10, 0b11, 0b01]


def test_one_end_per_class_serves_every_row():
    """An end is the ITI with a class, and the rows share it: an 18-row task
    pays one state for its aborts, not 18."""
    spine = [GO_NO_GO[0], dict(GO_NO_GO[1], abortOnRelease="port"), *GO_NO_GO[2:]]
    low = lowering.lower(spine, inputs=["port", "resp"], outputs=["cue", "sample", "reward"], rows=[GO, NO_GO])
    end = len(low.states) - 1
    assert end == 15, "the go/no-go pair's 15 states, then one end"
    assert low.states[end][11] == ABORT_DURING and low.rows[end] is None and low.phases[end] == 4
    assert [e for e in low.edges if e[1] == lowering.FALL] == [(0, lowering.FALL, end)] * 2


COUNT = lowering.STARTS_TRIAL | lowering.COUNT
FR = [{"phase": "counter", "on": "lever", "count": 5, "outputs": ["light"]},
      {"phase": "outcome", "line": "reward", "ms": 0},
      {"phase": "iti", "ms": 0}]
FR_SLOTS = {"inputs": ["lever"], "outputs": ["light", "reward"]}


def test_a_fixed_ratio_counter_lowers_to_one_counter_state_reading_its_n():
    low = lowering.lower(FR, **FR_SLOTS)
    assert low.params == ("NT", "N0", "T1", "T2", "RW1", "RP1")
    assert low.states == (
        (0b01, 1, N, N, N, N, N, N, 0, 1, COUNT, 0),                   # 0 count lever rises
        (0, 0, N, N, N, 5, 2, 3, 0, 0, 0, CORRECT),                    # 1 the N-th: draw the reward
        (0b10, 0, 4, 4, 3, N, N, N, 0, 0, 0, 0),                       # 2 the reward
        (0, 0, 2, 2, 4, N, N, N, 0, 0, 0, 0),                          # 3 the class timeout
        (0, 0, 3, 3, 0, N, N, N, 0, 0, 0, 0),                          # 4 ITI
    )
    assert low.edges == ((0, lowering.RISE, 1),)
    assert low.counter == (1, 1, ())


def test_a_variable_ratio_draws_n_between_two_slots():
    spine = [dict(FR[0], count=1, countMax=9), *FR[1:]]
    low = lowering.lower(spine, **FR_SLOTS)
    assert low.params == ("NT", "N0", "NX0", "T1", "T2", "RW1", "RP1")
    assert low.counter == (1, 2, ())


def test_a_progressive_ratio_with_a_limit_that_ends_the_session():
    spine = [{"phase": "counter", "on": "lever", "ratios": [1, 2, 4, 6], "timeoutMs": 60000,
              "endsSession": True}, *FR[1:]]
    low = lowering.lower(spine, **FR_SLOTS)
    assert low.params == ("NT", "T0", "T1", "T2", "RW1", "RP1")
    assert low.counter == (N, N, (1, 2, 4, 6))
    assert low.states[0][2:5] == (1, 1, 5), "the limit, out to its end"
    assert low.states[5] == (0, 0, 3, 3, 0, N, N, N, 0, 0, lowering.LAST_TRIAL, OMISSION)
    # Without endsSession the limit's end is an omission that leaves the session running.
    spine[0] = dict(spine[0], endsSession=False)
    assert lowering.lower(spine, **FR_SLOTS).states[5][10] == 0


def test_every_lowered_table_with_a_counter_is_one_replay_accepts():
    for spine in (FR, [dict(FR[0], count=1, countMax=9), *FR[1:]],
                  [{"phase": "counter", "on": "lever", "ratios": [1, 2], "timeoutMs": 5, "endsSession": True},
                   *FR[1:]]):
        low = lowering.lower(spine, **FR_SLOTS)
        cmin, cmax, ratios = low.counter
        table = rp.Table(states=[rp.StateRow(*s) for s in low.states], edges=[rp.EdgeRow(*e) for e in low.edges],
                         counter=rp.Counter(cmin, cmax, ratios))
        assert table.slots_used() == len(low.params)


def test_two_counters_are_not_a_table():
    with pytest.raises(lowering.LoweringError, match="Counter"):
        lowering.lower([FR[0], FR[0], FR[2]], **FR_SLOTS)


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


# --- the Response window, the contingency map and several rows (#101) ----------

PICK = lowering.STARTS_TRIAL | lowering.PICK
CORRECT, WRONG, HOLD_BROKEN, OMISSION, WITHHELD, FALSE_ALARM = (
    lowering.OUTCOME_CLASSES.index(name) + 1
    for name in ("correct", "wrong_response", "hold_broken", "omission", "withheld", "false_alarm")
)

GO_NO_GO = [
    {"phase": "wait", "on": "port", "outputs": ["cue"]},
    {"phase": "present", "outputs": ["cue", "sample"], "ms": 500},
    {"phase": "response", "responses": ["resp"], "ms": 3000, "outputs": ["cue"]},
    {"phase": "outcome", "ms": 0},
    {"phase": "iti", "ms": 1000},
]
GO = {"id": "go", "bind": {"port": "P", "resp": "R", "cue": "C", "sample": "O1", "reward": "F"},
      "map": {"resp": {"outcome": "correct", "line": "reward", "rewardPermille": 1000},
              "timeout": {"outcome": "omission"}}}
NO_GO = {"id": "nogo", "bind": {"port": "P", "resp": "R", "cue": "C", "sample": "O2", "reward": "F"},
         "map": {"resp": {"outcome": "false_alarm"}, "timeout": {"outcome": "withheld"}}}


def test_a_go_no_go_pair_lowers_to_a_pick_state_and_a_copy_of_the_spine_per_row():
    low = lowering.lower(GO_NO_GO, inputs=["port", "resp"], outputs=["cue", "sample", "reward"],
                         rows=[GO, NO_GO])
    # Bits are channels: `sample` is O1 in one row and O2 in the other, two bits.
    assert low.inputs == (("port", "P"), ("resp", "R"))
    assert low.outputs == (("cue", "C"), ("sample", "O1"), ("sample", "O2"), ("reward", "F"))
    assert low.params == ("NT", "T1", "T2", "T3", "T4", "RW1", "RP1_1")
    #        outputs watch tmin tmax  on_to chance hit miss first count flags outcome
    assert low.states == (
        (0, 0, N, N, N, N, N, N, 0, 2, PICK, 0),                # 0  pick a row
        (0b0001, 0b01, N, N, N, N, N, N, 2, 1, 0, 0),           # 1  go: wait for the port
        (0b0011, 0, 1, 1, 3, N, N, N, 0, 0, 0, 0),              # 2  present odor 1
        (0b0001, 0b10, 2, 2, 7, N, N, N, 3, 1, 0, 0),           # 3  the window
        (0, 0, N, N, N, 6, 5, 6, 0, 0, 0, CORRECT),             # 4  resp: draw the reward
        (0b1000, 0, 5, 5, 6, N, N, N, 0, 0, 0, 0),              # 5  the reward line open
        (0, 0, 3, 3, 8, N, N, N, 0, 0, 0, 0),                   # 6  the class timeout
        (0, 0, 3, 3, 8, N, N, N, 0, 0, 0, OMISSION),            # 7  timeout: the class timeout
        (0, 0, 4, 4, 0, N, N, N, 0, 0, 0, 0),                   # 8  ITI, back to the pick
        (0b0001, 0b01, N, N, N, N, N, N, 4, 1, 0, 0),           # 9  no-go: wait for the port
        (0b0101, 0, 1, 1, 11, N, N, N, 0, 0, 0, 0),             # 10 present odor 2
        (0b0001, 0b10, 2, 2, 13, N, N, N, 5, 1, 0, 0),          # 11 the window
        (0, 0, 3, 3, 14, N, N, N, 0, 0, 0, FALSE_ALARM),        # 12 resp: no line
        (0, 0, 3, 3, 14, N, N, N, 0, 0, 0, WITHHELD),           # 13 timeout
        (0, 0, 4, 4, 0, N, N, N, 0, 0, 0, 0),                   # 14 ITI
    )
    assert low.edges == ((0, 0, 1), (0, 0, 9), (0, lowering.RISE, 2), (1, lowering.RISE, 4),
                         (0, lowering.RISE, 10), (1, lowering.RISE, 12))
    assert low.phases == (None, 0, 1, 2, 3, 3, 3, 3, 4, 0, 1, 2, 3, 3, 4)
    assert low.rows == (None, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1)


TWO_AFC = [
    {"phase": "wait", "on": "port", "outputs": ["cue"]},
    {"phase": "response", "responses": ["left", "right"], "ms": 5000, "holdMs": 200, "outputs": ["cue"]},
    {"phase": "outcome", "ms": 0},
    {"phase": "iti", "ms": 3000},
]
RIGHT_IS_CORRECT = {
    "id": "odor_1",
    "bind": {"port": "P", "left": "L", "right": "R", "cue": "C", "reward_l": "FL", "reward_r": "FR"},
    "map": {"right": {"outcome": "correct", "line": "reward_r", "rewardPermille": 1000, "hold": True},
            "left": {"outcome": "wrong_response"},
            "timeout": {"outcome": "omission"}},
}
AFC_SLOTS = {"inputs": ["port", "left", "right"], "outputs": ["cue", "reward_l", "reward_r"]}


def test_a_2afc_row_with_a_hold_lowers_to_the_worked_table():
    low = lowering.lower(TWO_AFC, **AFC_SLOTS, rows=[RIGHT_IS_CORRECT])
    # The window's H1 straight after its T1; right is entry 2 (responses, then timeout).
    assert low.params == ("NT", "T1", "H1", "T2", "T3", "RW1", "RP1_2")
    assert low.states == (
        (0b001, 0b001, N, N, N, N, N, N, 0, 1, lowering.STARTS_TRIAL, 0),  # 0 wait; one row, no pick
        (0b001, 0b110, 1, 1, 7, N, N, N, 1, 2, 0, 0),                      # 1 the window
        (0, 0, 3, 3, 9, N, N, N, 0, 0, 0, WRONG),                          # 2 left: wrong
        (0b001, 0b100, 2, 2, 4, N, N, N, 3, 1, 0, 0),                      # 3 right: hold it
        (0, 0, N, N, N, 6, 5, 6, 0, 0, 0, CORRECT),                        # 4 held: draw the reward
        (0b100, 0, 5, 5, 6, N, N, N, 0, 0, 0, 0),                          # 5 reward_r open
        (0, 0, 3, 3, 9, N, N, N, 0, 0, 0, 0),                              # 6 the class timeout
        (0, 0, 3, 3, 9, N, N, N, 0, 0, 0, OMISSION),                       # 7 timeout
        (0, 0, 3, 3, 9, N, N, N, 0, 0, 0, HOLD_BROKEN),                    # 8 let go early
        (0, 0, 4, 4, 0, N, N, N, 0, 0, 0, 0),                              # 9 ITI
    )
    assert low.edges == ((0, lowering.RISE, 1), (1, lowering.RISE, 2), (2, lowering.RISE, 3),
                         (2, lowering.FALL, 8))
    assert low.phases == (0, 1, 2, 1, 2, 2, 2, 2, 2, 3), "the hold is the window's phase"
    assert low.rows == (0,) * 10


def test_every_resolved_branch_enters_exactly_one_outcome_state_and_a_line_is_drawn_there():
    """The contract the trial table reads (#99): each branch out of the window
    marks its class once, and with a line that state is the chance state whose
    on_hit is the reward state."""
    low = lowering.lower(TWO_AFC, **AFC_SLOTS, rows=[RIGHT_IS_CORRECT])
    marked = [s for s, row in enumerate(low.states) if row[11]]
    assert [low.states[s][11] for s in marked] == [WRONG, CORRECT, OMISSION, HOLD_BROKEN]
    chance = low.states[4]
    assert chance[5] != N and low.states[chance[6]][0] == 0b100


def test_a_tracer_row_pays_by_its_own_keys_and_lowers_as_before():
    rows = [{"id": "r1", "bind": {"port": "odor_port", "cue": "a", "sample": "b", "reward": "c"}}]
    low = lowering.lower(TRACER, inputs=["port"], outputs=["cue", "sample", "reward"], rows=rows)
    assert low.states == lowering.lower(TRACER, inputs=["port"], outputs=["cue", "sample", "reward"]).states
    assert low.params == ("NT", "T1", "T2", "T3", "T4", "RW1", "RP1")


def test_a_window_whose_map_is_incomplete_is_not_a_table():
    row = dict(RIGHT_IS_CORRECT, map={"right": {"outcome": "correct"}})
    with pytest.raises(lowering.LoweringError, match="left"):
        lowering.lower(TWO_AFC, **AFC_SLOTS, rows=[row])
