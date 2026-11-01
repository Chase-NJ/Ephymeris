"""The Python port of the phase interpreter — `analytics/stream/replay.py`.

The port's whole job is to agree with `firmware/libraries/BehaviorBox/BoxInterp.h`
tick for tick. The differential test (`extras/host_test/run_diff.sh`) holds the
two equal over generated tables; these tests pin what it cannot: the RNG
against values captured from the C side's host build, a worked trial against
the tick rules written out by hand, and the tables replay refuses.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream.replay import (
    FALL,
    NONE,
    RISE,
    STARTS_TRIAL,
    Actions,
    EdgeRow,
    Edges,
    StateRow,
    Table,
)

# --- avr-libc random(), bit for bit -------------------------------------------

#: The first five values of `interp_random()` from each seed, printed by a
#: host build of BoxInterp.h. Seed 1 is Park and Miller's own sequence; 0 and
#: everything at or above 2^31 - 1 exercise avr-libc's quirks. test_interp.cpp
#: asserts the same literals against the C core; change one, change both.
CAPTURED_FROM_C = {
    0x00000001: (16807, 282475249, 1622650073, 984943658, 1144108930),
    0x00000000: (520932930, 28925691, 822784415, 890459872, 145532761),
    0x075BCD15: (469049721, 2053676357, 1781357515, 1206231778, 891865166),
    0x7FFFFFFE: (2147466840, 1865008398, 524833574, 1162539989, 1003374717),
    0x7FFFFFFF: (0, 520932930, 28925691, 822784415, 890459872),
    0x80000000: (2147466840, 1865008398, 524833574, 1162539989, 1003374717),
    0xFFFFFFFF: (2147466840, 1865008398, 524833574, 1162539989, 1003374717),
}


@pytest.mark.parametrize("seed", sorted(CAPTURED_FROM_C), ids=hex)
def test_the_rng_matches_the_c_host_build(seed: int) -> None:
    ctx, values = seed, []
    for _ in range(5):
        value, ctx = rp.avr_random(ctx)
        values.append(value)
    assert tuple(values) == CAPTURED_FROM_C[seed]


def test_the_rng_meets_park_and_millers_check_value() -> None:
    # "Random number generators: good ones are hard to find", CACM 31(10), 1988.
    ctx = 1
    for _ in range(10000):
        value, ctx = rp.avr_random(ctx)
    assert value == 1043618065


def test_a_draw_is_random_mod_n() -> None:
    # Captured from the C side: interp_draw from seed 42 over n = 1000, 7, 2, 3.
    ctx, got = 42, []
    for n in (1000, 7, 2, 3):
        value, ctx = rp.draw(ctx, n)
        got.append(value)
    assert got == [894, 2, 1, 2]
    assert rp.draw(ctx, 0) == (0, ctx)  # n == 0 draws nothing


# --- a worked trial -----------------------------------------------------------

PORT, LEFT, RIGHT = 1 << 0, 1 << 1, 1 << 2  # inputs
LIGHT, ODOR, FLUID = 1 << 0, 1 << 3, 1 << 5  # outputs
ITI, WAIT, SAMPLE, REWARD, P_ALWAYS, CLASS_TIMEOUT = range(6)
PARAMS = (1000, 5000, 500, 40, 1000, 200)

#: Wait -> Present -> Outcome -> ITI, lowered as BoxInterp.h's
#: "Lowering the first phases" describes. RIGHT is correct, LEFT wrong.
TRIAL = Table(
    states=(
        # 0 Wait for the port, light on
        StateRow(outputs=LIGHT, watch=PORT, timer_min=WAIT, timer_max=WAIT, on_timeout=6,
                 edge_first=0, edge_count=1, flags=STARTS_TRIAL),
        # 1 Present the odor until a well
        StateRow(outputs=LIGHT | ODOR, watch=LEFT | RIGHT, timer_min=WAIT, timer_max=WAIT,
                 on_timeout=5, edge_first=1, edge_count=2),
        # 2 Outcome, correct: reward with p = 1000 permille
        StateRow(chance=P_ALWAYS, on_hit=3, on_miss=4, outcome=1),
        # 3 the reward line open for its ms
        StateRow(outputs=FLUID, timer_min=REWARD, timer_max=REWARD, on_timeout=4),
        # 4 the class's timeout
        StateRow(timer_min=CLASS_TIMEOUT, timer_max=CLASS_TIMEOUT, on_timeout=6),
        # 5 Outcome, wrong response
        StateRow(timer_min=CLASS_TIMEOUT, timer_max=CLASS_TIMEOUT, on_timeout=6, outcome=2),
        # 6 ITI
        StateRow(timer_min=ITI, timer_max=ITI, on_timeout=0),
    ),
    edges=(
        EdgeRow(input=0, edge=RISE, next=1),
        EdgeRow(input=2, edge=RISE, next=2),
        EdgeRow(input=1, edge=RISE, next=5),
    ),
)

#: The animal pokes at 10 and answers right at 300; the right beam clears at
#: 400, when nothing is watching it.
POKES = [(10, Edges(rose=PORT)), (300, Edges(rose=RIGHT)), (400, Edges(fell=RIGHT))]


def test_a_correct_trial_replays_by_the_tick_rules() -> None:
    got = rp.replay(TRIAL, PARAMS, seed=1, events=POKES, ticks=2000)
    assert got == [
        (0, Actions(on=LIGHT, entered=(0, NONE), flags=rp.ACT_SESSION_START | rp.ACT_TRIAL_START)),
        (10, Actions(rose=PORT, on=ODOR, entered=(1, NONE))),
        # The chance state draws 16807 % 1000 = 807 < 1000 and pays in the same
        # tick; outputs are diffed against the resting state it left.
        (300, Actions(rose=RIGHT, on=FLUID, off=LIGHT | ODOR, entered=(2, 3))),
        (340, Actions(off=FLUID, entered=(4, NONE))),
        (540, Actions(entered=(6, NONE))),
        (1540, Actions(on=LIGHT, entered=(0, NONE), flags=rp.ACT_TRIAL_START)),
    ]


def test_replay_from_the_strobed_edges_alone_gives_the_same_run() -> None:
    # The board strobes only watched edges; replay never sees the rest.
    run = rp.replay(TRIAL, PARAMS, seed=1, events=POKES, ticks=2000)
    strobed = [(t, Edges(a.rose, a.fell)) for t, a in run if a.rose or a.fell]
    assert len(strobed) < len(POKES)
    assert rp.replay(TRIAL, PARAMS, seed=1, events=strobed, ticks=2000) == run


def test_replay_runs_across_the_millis_wrap() -> None:
    start = 0xFFFFFF00
    events = [((start + t) & 0xFFFFFFFF, e) for t, e in POKES]
    got = rp.replay(TRIAL, PARAMS, seed=1, events=events, ticks=2000, start=start)
    expected = rp.replay(TRIAL, PARAMS, seed=1, events=POKES, ticks=2000)
    assert got == [((start + t) & 0xFFFFFFFF, a) for t, a in expected]


# --- the pick state (INTERP 3) -------------------------------------------------

ROW_1, ROW_2 = 1, 2
#: State 0 draws one of two rows, each a state that rests for 100 ms and goes back.
PICK = Table(
    states=(
        StateRow(edge_first=0, edge_count=2, flags=STARTS_TRIAL | rp.PICK),
        StateRow(outputs=LIGHT, timer_min=0, timer_max=0, on_timeout=0),
        StateRow(outputs=ODOR, timer_min=0, timer_max=0, on_timeout=0),
    ),
    edges=(EdgeRow(0, 0, ROW_1), EdgeRow(0, 0, ROW_2)),
)


def test_a_pick_state_draws_its_branch_and_goes_on_in_the_same_tick() -> None:
    # Seed 1's first value is 16807: 16807 % 2 = 1, the second branch.
    _, first = rp.begin(PICK, (100,), seed=1, now=0)
    assert first == Actions(on=ODOR, entered=(0, ROW_2), flags=rp.ACT_SESSION_START | rp.ACT_TRIAL_START)
    # Seed 42's first value ends in 894 (test_a_draw_is_random_mod_n): even, the first.
    _, first = rp.begin(PICK, (100,), seed=42, now=0)
    assert first.entered == (0, ROW_1) and first.on == LIGHT


def test_a_pick_state_draws_every_time_it_is_entered() -> None:
    run = rp.replay(PICK, (100,), seed=1, events=[], ticks=400)
    ctx, rows = 1, []
    for _ in range(5):
        k, ctx = rp.draw(ctx, 2)
        rows.append((0, (ROW_1, ROW_2)[k]))
    assert [a.entered for _, a in run] == rows
    assert {a.entered[1] for _, a in run} == {ROW_1, ROW_2}


def test_a_version_2_table_with_a_pick_state_is_refused() -> None:
    """INTERP 2 has no pick state: its core would rest in one forever."""
    with pytest.raises(ValueError, match="pick"):
        rp.replay(PICK, (100,), seed=1, events=[], ticks=10, interp=2)
    rp.replay(TRIAL, PARAMS, seed=1, events=[], ticks=10, interp=2)  # a plain table still runs


# --- what replay refuses ------------------------------------------------------


def test_an_unknown_interpreter_version_is_refused() -> None:
    with pytest.raises(ValueError, match="INTERP 99"):
        rp.replay(TRIAL, PARAMS, seed=1, events=[], ticks=10, interp=99)


def test_the_trial_runner_s_interpreter_is_never_replayed_as_a_table() -> None:
    """One numbering space: INTERP 1 is BehaviorBox.h's trial runner, which every
    recorded GRGL run names, and the state-table interpreter is 2. So a run's
    header alone tells a spine run from a legacy one, and replay never walks a
    legacy run's strobes as if a table had produced them. 2 is the tracer's
    table format, kept so its runs still replay; 3 adds the pick state."""
    assert rp.INTERP_VERSIONS == {2, 3}
    assert rp.INTERP_VERSION == 3
    with pytest.raises(ValueError, match="INTERP 1"):
        rp.replay(TRIAL, PARAMS, seed=1, events=[], ticks=10, interp=1)


def test_a_parameter_slot_past_the_params_is_refused() -> None:
    with pytest.raises(ValueError, match="slot 5"):
        rp.replay(TRIAL, PARAMS[:5], seed=1, events=[], ticks=10)


def test_events_out_of_order_or_on_the_first_tick_are_refused() -> None:
    with pytest.raises(ValueError):
        rp.replay(TRIAL, PARAMS, seed=1, events=[(0, Edges(rose=PORT))], ticks=10)
    with pytest.raises(ValueError):
        rp.replay(TRIAL, PARAMS, seed=1, events=[(5, Edges()), (5, Edges())], ticks=10)
    with pytest.raises(ValueError):
        rp.replay(TRIAL, PARAMS, seed=1, events=[(11, Edges())], ticks=10)


def _one(state: StateRow, *more: StateRow, edges: tuple[EdgeRow, ...] = ()) -> Table:
    return Table(states=(state, *more), edges=edges)


@pytest.mark.parametrize(
    "build, why",
    [
        (lambda: _one(StateRow(edge_count=1), edges=(EdgeRow(0, RISE, 0),)), "not watched"),
        (
            lambda: _one(
                StateRow(watch=PORT, edge_count=2),
                edges=(EdgeRow(0, RISE, 0), EdgeRow(0, RISE, 0)),
            ),
            "twice",
        ),
        (lambda: _one(StateRow(watch=PORT, edge_count=1), edges=(EdgeRow(0, 3, 0),)), "edge"),
        (lambda: _one(StateRow(timer_min=0, timer_max=0, on_timeout=1)), "on_timeout"),
        (lambda: _one(StateRow(timer_min=0, timer_max=NONE, on_timeout=0)), "timer_max"),
        (lambda: _one(StateRow(edge_first=0, edge_count=1, watch=PORT)), "edge rows"),
        (lambda: _one(StateRow(chance=0, on_hit=0, on_miss=0)), "chance state"),
        (
            lambda: _one(StateRow(chance=0, on_hit=1, on_miss=1), StateRow(outputs=LIGHT, chance=0, on_hit=0, on_miss=0)),
            "chance state",
        ),
        (lambda: _one(StateRow(chance=0, on_hit=0, on_miss=0, timer_min=0, timer_max=0, on_timeout=0)), "chance"),
        (lambda: _one(StateRow(outputs=1 << 32)), "outputs"),
        (lambda: Table(states=(), edges=()), "states"),
        # A pick state: no outputs, watch, timer or chance; at least one branch,
        # each an edge row (input 0, edge 0) to a state that does not branch.
        (lambda: _one(StateRow(flags=rp.PICK)), "branch"),
        (lambda: _one(StateRow(outputs=LIGHT, edge_count=1, flags=rp.PICK), StateRow(),
                      edges=(EdgeRow(0, 0, 1),)), "pick state has no"),
        (lambda: _one(StateRow(edge_count=1, timer_min=0, timer_max=0, on_timeout=1, flags=rp.PICK),
                      StateRow(), edges=(EdgeRow(0, 0, 1),)), "pick state has no"),
        (lambda: _one(StateRow(edge_count=1, flags=rp.PICK), StateRow(),
                      edges=(EdgeRow(0, RISE, 1),)), "input 0, edge 0"),
        (lambda: _one(StateRow(edge_count=1, flags=rp.PICK), StateRow(chance=0, on_hit=0, on_miss=0),
                      edges=(EdgeRow(0, 0, 1),)), "branches"),
        (lambda: _one(StateRow(edge_count=1, flags=rp.PICK), edges=(EdgeRow(0, 0, 0),)), "branches"),
        (lambda: _one(StateRow(chance=0, on_hit=1, on_miss=1), StateRow(edge_count=1, flags=rp.PICK),
                      StateRow(), edges=(EdgeRow(0, 0, 2),)), "pick state"),
        (lambda: _one(StateRow(chance=0, on_hit=0, on_miss=0, flags=rp.PICK)), "chance"),
    ],
)
def test_a_table_the_core_cannot_run_is_refused(build, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        build()
