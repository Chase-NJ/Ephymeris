"""The trial table, read off a replay — `ANALYTICS.md#how-a-spine-run-is-scored`.

Every column comes from the state table's own fields: a trial starts where a
state with `STARTS_TRIAL` is entered, its outcome class is the `outcome` of
the states it entered, a reward is the hit branch of a chance state that bears
an outcome, and a response is an edge exit read through the phase map. Nothing
reads a phase kind or a code name, so a table with an outcome no task has used
yet scores with no change here.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream import table_metrics, trial_table
from ephymeris_sidecar.taskdef import lowering
from tests.fixtures import spine as fixture

PORT = 0
#: NT, T1 (present), T2 (delay), T3 (outcome), T4 (ITI), RW1, RP1
PARAMS = (3, 1000, 500, 0, 3000, 100, 1000)
N = rp.NONE


def tracer_table() -> tuple[rp.Table, lowering.Lowered]:
    low = lowering.lower(fixture.tracer()["spine"], ["port"], ["cue", "sample", "reward"])
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states],
                     edges=[rp.EdgeRow(*e) for e in low.edges])
    return table, low


def poke(at: int) -> tuple[int, rp.Edges]:
    return at, rp.Edges(rose=1 << PORT)


def release(at: int) -> tuple[int, rp.Edges]:
    return at, rp.Edges(fell=1 << PORT)


def trials(table: rp.Table, params, events, ticks: int, end: int | None = None, phase_of=None):
    actions = rp.replay(table, params, 7, events, ticks)
    return trial_table.trials_of(table, actions, end=end, phase_of=phase_of)


def test_a_held_trial_is_correct_and_paid_and_an_abort_is_marked_at_its_end() -> None:
    table, low = tracer_table()
    # Trial 1 holds through the present; trial 2 lets go during it.
    events = [poke(200), release(1500), poke(5000), release(5300)]
    out = trials(table, PARAMS, events, 9000, phase_of=low.phases)
    first, second = out[0], out[1]

    assert first.at == 0 and first.complete
    assert first.outcome == lowering.OUTCOME_CORRECT
    assert first.rewarded and first.reward_outputs == 1 << 2, "the reward slot's bit"
    assert first.reward_ms == PARAMS[5], "the ticks the line was actually open"
    assert first.response is None, "a timer took it to the outcome: no response"
    assert first.entries[1] == 200 and first.entries[2] == 1200, "the present at the poke, the delay 1000 ms on"

    # The release during the present goes to the abort's end, which marks it (#102).
    assert second.outcome == lowering.OUTCOME_ABORT_DURING and not second.rewarded
    assert second.counts == {(0, PORT): 1}, "the poke that left the wait, counted in the wait"
    # Trial 3 starts after trial 2's ITI and is cut off by the end of the replay.
    assert len(out) == 3 and not out[2].complete


def test_the_trial_the_session_ends_on_is_not_a_trial() -> None:
    table, _ = tracer_table()
    params = (1, *PARAMS[1:])
    actions = rp.replay(table, params, 7, [poke(200)], 6000)
    end = next(now for now, a in actions if a.flags & rp.ACT_TRIAL_START and now > 0)
    out = trial_table.trials_of(table, actions, end=end)
    assert len(out) == 1 and out[0].complete


def test_a_reward_drawn_against_is_correct_but_not_rewarded() -> None:
    table, _ = tracer_table()
    params = (*PARAMS[:6], 0)
    out = trials(table, params, [poke(200)], 4000)
    assert out[0].outcome == lowering.OUTCOME_CORRECT
    assert not out[0].rewarded and out[0].reward_ms is None


#: A table no lowering writes yet: a wait for a poke, then a response window
#: whose two edges go to outcome classes 6 and 42 (one this code has never seen
#: named), each a state of its own, then an ITI.
UNSEEN = 42


def unseen_table() -> rp.Table:
    return rp.Table(
        states=[
            rp.StateRow(watch=0b01, edge_first=0, edge_count=1, flags=rp.STARTS_TRIAL),
            rp.StateRow(watch=0b10, timer_min=1, timer_max=1, on_timeout=4, edge_first=1, edge_count=2),
            rp.StateRow(outputs=0b1, timer_min=2, timer_max=2, on_timeout=4, outcome=6),
            rp.StateRow(timer_min=2, timer_max=2, on_timeout=4, outcome=UNSEEN),
            rp.StateRow(timer_min=3, timer_max=3, on_timeout=0),
        ],
        edges=[rp.EdgeRow(0, rp.RISE, 1), rp.EdgeRow(1, rp.RISE, 2), rp.EdgeRow(1, rp.FALL, 3)],
    )


def test_an_outcome_never_seen_before_is_scored_by_its_number_with_no_change() -> None:
    table = unseen_table()
    params = (2, 2000, 50, 1000)
    events = [(100, rp.Edges(rose=0b01)), (400, rp.Edges(rose=0b10)),
              (1600, rp.Edges(rose=0b01)), (1700, rp.Edges(fell=0b10))]
    out = trials(table, params, events, 8000)
    first, second = out[0], out[1]
    assert first.outcome == 6 and first.response == (1, rp.RISE)
    assert first.response_at == 400 and first.latency == 300, "from the window's entry at 100"
    assert not first.rewarded, "no chance state: nothing paid"
    assert second.response == (1, rp.FALL) and second.outcome == UNSEEN

    naming = trial_table.Naming(inputs=("port", "lever"), outputs=("light",))
    named = [trial_table.name(t, naming) for t in out[:2]]
    assert named[0].outcome == lowering.OUTCOME_CLASSES[5]
    assert named[1].outcome == f"outcome_{UNSEEN}"
    assert named[0].response == "lever" and named[0].response_edge == "rise"

    score = table_metrics.score(named, rows=())
    assert {c.outcome_class: c.n for c in score.classes} == {"false_alarm": 1, f"outcome_{UNSEEN}": 1}


def hold_table() -> rp.Table:
    """A response window whose response must be held: window -> hold -> correct,
    or a release in the hold -> hold broken. The window and its hold are one phase."""
    return rp.Table(
        states=[
            rp.StateRow(timer_min=1, timer_max=1, on_timeout=1, flags=rp.STARTS_TRIAL),
            rp.StateRow(watch=0b1, timer_min=2, timer_max=2, on_timeout=4, edge_first=0, edge_count=1),
            rp.StateRow(watch=0b1, timer_min=1, timer_max=1, on_timeout=3, edge_first=1, edge_count=1),
            rp.StateRow(timer_min=1, timer_max=1, on_timeout=0, outcome=lowering.OUTCOME_CORRECT),
            rp.StateRow(timer_min=1, timer_max=1, on_timeout=0,
                        outcome=lowering.OUTCOME_CLASSES.index("hold_broken") + 1),
        ],
        edges=[rp.EdgeRow(0, rp.RISE, 2), rp.EdgeRow(0, rp.FALL, 4)],
    )


def test_a_held_response_is_timed_from_the_window_not_the_end_of_the_hold() -> None:
    table = hold_table()
    phases = (0, 1, 1, 2, 2)
    params = (3, 100, 5000)
    # Trial 1: responds 250 ms into the window and holds; trial 2: lets go in the hold.
    events = [(350, rp.Edges(rose=1)), (900, rp.Edges(fell=1)), (1100, rp.Edges(rose=1)),
              (1150, rp.Edges(fell=1))]
    out = trials(table, params, events, 3000, phase_of=phases)
    held, broken = out[0], out[1]
    assert held.outcome == lowering.OUTCOME_CORRECT
    assert held.response == (0, rp.RISE) and held.response_at == 350 and held.latency == 250
    assert broken.outcome == lowering.OUTCOME_CLASSES.index("hold_broken") + 1
    assert broken.response == (0, rp.RISE) and broken.response_at == 1100


def test_counts_and_phase_entries_group_states_by_the_phase_map() -> None:
    table, low = tracer_table()
    out = trials(table, PARAMS, [poke(200), release(1500)], 6000, phase_of=low.phases)
    naming = trial_table.Naming(inputs=("odor_port",), outputs=("trial_light", "odor_line_1", "fluid_2"),
                                phase_of=low.phases, phases=5)
    first = trial_table.name(out[0], naming)
    assert first.phase_entries == (0, 200, 1200, 1700, 1801)
    assert first.reward_line == "fluid_2" and first.reward_ms == 100
    assert first.input_counts == (trial_table.InputCount(phase=0, channel="odor_port", count=1),)
    unmapped = trial_table.name(out[0], trial_table.Naming(inputs=("odor_port",), outputs=()))
    assert unmapped.phase_entries == () and unmapped.input_counts == ()


def test_metrics_are_functions_of_the_table() -> None:
    def trial(i: int, row: str | None, outcome: str | None, rewarded: bool, complete: bool = True):
        return trial_table.ReplayTrial(index=i, at_ms=i * 1000, row=row, outcome=outcome,
                                       rewarded=rewarded, complete=complete)

    table = [trial(0, "go", "correct", True), trial(1, "go", "omission", False),
             trial(2, "go", None, False), trial(3, "nogo", "false_alarm", False),
             trial(4, "nogo", "withheld", False), trial(5, "go", "correct", True, complete=False)]
    score = table_metrics.score(table, rows=(("go", "Go"), ("nogo", "No-go")))
    assert score.trials == 5 and score.unclassified == 1, "an incomplete trial is left out"
    assert score.rewarded.n == 1 and score.rewarded.of == 5
    go = score.rows[0]
    assert (go.row_id, go.trials, go.unclassified) == ("go", 3, 1)
    assert {c.outcome_class: c.n for c in go.classes} == {"correct": 1, "omission": 1}
    correct = next(c for c in go.classes if c.outcome_class == "correct")
    assert correct.p == 1 / 3 and correct.low is not None and correct.low < correct.p < correct.high

    metrics = table_metrics.correct_metrics(score)
    assert [(m.label, m.hits, m.counted, m.triggered, m.excluded) for m in metrics] == [
        ("P(correct | Go)", 1, 2, 3, 1), ("P(correct | No-go)", 1, 2, 2, 0)], \
        "a withhold is the no-go row's hit, a false alarm its miss"
    overall = table_metrics.overall_correct(score)
    assert (overall.hits, overall.counted) == (2, 4)


def test_the_hops_before_the_trial_start_on_one_tick_belong_to_the_trial_that_ends() -> None:
    """A window that starts the trial, whose lick goes to an outcome-bearing
    chance state that misses straight back to the window: the lick, the class
    and the latency are the old trial's, and the new trial starts empty."""
    omission = lowering.OUTCOME_CLASSES.index("omission") + 1
    table = rp.Table(
        states=[
            rp.StateRow(watch=0b1, timer_min=1, timer_max=1, on_timeout=2, edge_first=0, edge_count=1,
                        flags=rp.STARTS_TRIAL),
            rp.StateRow(chance=2, on_hit=3, on_miss=0, outcome=lowering.OUTCOME_CORRECT),
            rp.StateRow(timer_min=3, timer_max=3, on_timeout=0, outcome=omission),
            rp.StateRow(outputs=0b1, timer_min=3, timer_max=3, on_timeout=0),
        ],
        edges=[rp.EdgeRow(0, rp.RISE, 1)],
    )
    params = (1000, 1000, 0, 100)  # the draw always misses
    first, second = trials(table, params, [(300, rp.Edges(rose=1))], 1500)[:2]
    assert first.outcome == lowering.OUTCOME_CORRECT and not first.rewarded
    assert first.response == (0, rp.RISE) and first.response_at == 300 and first.latency == 300
    assert second.at == 300 and second.outcome == omission
    assert second.response is None and second.counts == {}


HOLD_BROKEN = lowering.OUTCOME_CLASSES.index("hold_broken") + 1
OMISSION = lowering.OUTCOME_CLASSES.index("omission") + 1


def window_table(*, delay: bool = False, marked_chance: bool = True) -> tuple[rp.Table, tuple[int, ...]]:
    """A response window with a hold, as #101's lowering writes one: the lick
    goes to a hold in the window's phase, whose timer goes on to the Outcome
    (a chance state, then the reward line, then the class timeout) and whose
    release goes to a `hold_broken` branch; the window's timeout goes to an
    `omission` branch. `delay` puts a Delay phase between the window and the
    Outcome; `marked_chance=False` marks the class on the reward state instead
    of the chance state. Phases: 0 start, 1 window, 2 delay, 3 outcome, 4 ITI."""
    rows: list[rp.StateRow] = []
    phases: list[int] = []
    idx = {name: i for i, name in enumerate(
        ["start", "window", "hold", *(["delay"] if delay else []), "chance", "reward", "settle",
         "broken", "omit", "iti"])}
    post = idx["delay"] if delay else idx["chance"]

    def add(phase: int, **fields) -> None:  # noqa: ANN003
        rows.append(rp.StateRow(**fields))
        phases.append(phase)

    add(0, timer_min=1, timer_max=1, on_timeout=idx["window"], flags=rp.STARTS_TRIAL)
    add(1, watch=1, timer_min=2, timer_max=2, on_timeout=idx["omit"], edge_first=0, edge_count=1)
    add(1, watch=1, timer_min=3, timer_max=3, on_timeout=post, edge_first=1, edge_count=1)
    if delay:
        add(2, timer_min=6, timer_max=6, on_timeout=idx["chance"])
    add(3, chance=4, on_hit=idx["reward"], on_miss=idx["settle"],
        outcome=lowering.OUTCOME_CORRECT if marked_chance else 0)
    add(3, outputs=1, timer_min=5, timer_max=5, on_timeout=idx["settle"],
        outcome=0 if marked_chance else lowering.OUTCOME_CORRECT)
    add(3, timer_min=6, timer_max=6, on_timeout=idx["iti"])
    add(3, timer_min=6, timer_max=6, on_timeout=idx["iti"], outcome=HOLD_BROKEN)
    add(3, timer_min=6, timer_max=6, on_timeout=idx["iti"], outcome=OMISSION)
    add(4, timer_min=7, timer_max=7, on_timeout=idx["start"])
    edges = [rp.EdgeRow(0, rp.RISE, idx["hold"]), rp.EdgeRow(0, rp.FALL, idx["broken"])]
    return rp.Table(states=rows, edges=edges), tuple(phases)


#: start 100, window 2000, hold 200, permille 1000, reward 50, settle 10, ITI 500
WINDOW_PARAMS = (0, 100, 2000, 200, 1000, 50, 10, 500)


def window_trials(windows=None, **shape):  # noqa: ANN001, ANN003
    """Trial 1 licks 250 ms into the window (opened at 100) and holds; trial 2
    licks, then lets go during the hold; trial 3 never licks."""
    table, phases = window_table(**shape)
    # Trial 1: hold ends at 550, then [delay 10], reward 50, settle 10, ITI 500.
    start2 = 1110 + (10 if shape.get("delay") else 0)
    events = [(350, rp.Edges(rose=1)), (700, rp.Edges(fell=1)),
              (start2 + 300, rp.Edges(rose=1)), (start2 + 350, rp.Edges(fell=1))]
    actions = rp.replay(table, WINDOW_PARAMS, 7, events, start2 + 4000)
    return trial_table.trials_of(table, actions, end=None, phase_of=phases, windows=windows), 100


def test_a_held_response_is_the_windows_lick_in_the_lowerings_real_shape() -> None:
    for shape in ({}, {"delay": True}, {"marked_chance": False}, {"windows": frozenset({1})},
                  {"windows": frozenset({1}), "delay": True}):
        out, window_at = window_trials(**shape)
        held, broken, unanswered = out[0], out[1], out[2]
        assert held.outcome == lowering.OUTCOME_CORRECT, shape
        assert (held.response, held.response_at, held.latency) == ((0, rp.RISE), 350, 350 - window_at), shape
        assert broken.outcome == HOLD_BROKEN, shape
        assert broken.response == (0, rp.RISE) and broken.response_at == broken.at + 300, shape
        assert broken.latency == 200, "from the window opening, 100 ms into the trial"
        assert unanswered.outcome == OMISSION and unanswered.response is None, shape


def test_a_wait_that_can_abort_gives_an_omission_no_response_when_phases_name_the_window() -> None:
    """A Wait whose go edge leads on and whose abort edge goes to a class is a
    deciding state, but it is not the window: with `table.phases`, only an
    edge that left the Response window is a response."""
    abort = lowering.OUTCOME_CLASSES.index("abort_before_stimulus") + 1
    table = rp.Table(
        states=[
            rp.StateRow(watch=0b01, edge_first=0, edge_count=2, flags=rp.STARTS_TRIAL),   # 0 wait
            rp.StateRow(watch=0b10, timer_min=1, timer_max=1, on_timeout=3, edge_first=2, edge_count=1),  # 1 window
            rp.StateRow(timer_min=2, timer_max=2, on_timeout=5, outcome=lowering.OUTCOME_CORRECT),
            rp.StateRow(timer_min=2, timer_max=2, on_timeout=5, outcome=OMISSION),
            rp.StateRow(timer_min=2, timer_max=2, on_timeout=5, outcome=abort),
            rp.StateRow(timer_min=2, timer_max=2, on_timeout=0),                                  # 5 ITI
        ],
        edges=[rp.EdgeRow(0, rp.RISE, 1), rp.EdgeRow(0, rp.FALL, 4), rp.EdgeRow(1, rp.RISE, 2)],
    )
    phases, windows = (0, 1, 2, 2, 2, 3), frozenset({1})
    params = (0, 1000, 100)
    # Trial 1: pokes at 200 and never licks; trial 2: pokes, licks 300 ms in.
    events = [(200, rp.Edges(rose=1)), (1500, rp.Edges(rose=1)), (1800, rp.Edges(rose=0b10))]
    actions = rp.replay(table, params, 7, events, 2500)
    omitted, answered = trial_table.trials_of(table, actions, end=None, phase_of=phases, windows=windows)[:2]
    assert omitted.outcome == OMISSION and omitted.response is None
    assert answered.response == (1, rp.RISE) and answered.latency == 300
    # Without `table.phases` the structural rule stands, and names the poke.
    structural = trial_table.trials_of(table, actions, end=None)[0]
    assert structural.response == (0, rp.RISE)


#: #101's generated go/no-go table (`test_spine_lowering.py`), with its pick
#: state, and with the pick written as a 50% chance state for INTERP 2.
_PICK_PARAMS = (10, 500, 3000, 0, 1000, 100, 1000, 500)


def go_no_go_table(*, pick_as_chance: bool = True) -> rp.Table:
    n, correct = N, lowering.OUTCOME_CORRECT
    false_alarm = lowering.OUTCOME_CLASSES.index("false_alarm") + 1
    withheld = lowering.OUTCOME_CLASSES.index("withheld") + 1
    first = (rp.StateRow(chance=7, on_hit=1, on_miss=9, flags=rp.STARTS_TRIAL) if pick_as_chance
             else rp.StateRow(*(0, 0, n, n, n, n, n, n, 0, 2, rp.STARTS_TRIAL | rp.PICK, 0)))
    rows = [
        (0b0001, 0b01, n, n, n, n, n, n, 2, 1, 0, 0),
        (0b0011, 0, 1, 1, 3, n, n, n, 0, 0, 0, 0),
        (0b0001, 0b10, 2, 2, 7, n, n, n, 3, 1, 0, 0),
        (0, 0, n, n, n, 6, 5, 6, 0, 0, 0, correct),
        (0b1000, 0, 5, 5, 6, n, n, n, 0, 0, 0, 0),
        (0, 0, 3, 3, 8, n, n, n, 0, 0, 0, 0),
        (0, 0, 3, 3, 8, n, n, n, 0, 0, 0, OMISSION),
        (0, 0, 4, 4, 0, n, n, n, 0, 0, 0, 0),
        (0b0001, 0b01, n, n, n, n, n, n, 4, 1, 0, 0),
        (0b0101, 0, 1, 1, 11, n, n, n, 0, 0, 0, 0),
        (0b0001, 0b10, 2, 2, 13, n, n, n, 5, 1, 0, 0),
        (0, 0, 3, 3, 14, n, n, n, 0, 0, 0, false_alarm),
        (0, 0, 3, 3, 14, n, n, n, 0, 0, 0, withheld),
        (0, 0, 4, 4, 0, n, n, n, 0, 0, 0, 0),
    ]
    edges = [(0, 0, 1), (0, 0, 9), (0, rp.RISE, 2), (1, rp.RISE, 4), (0, rp.RISE, 10), (1, rp.RISE, 12)]
    if pick_as_chance:
        edges = edges[2:]
        rows = [(*r[:8], r[8] - 2 if r[9] else 0, *r[9:]) for r in rows]
    return rp.Table(states=[first, *(rp.StateRow(*r) for r in rows)], edges=[rp.EdgeRow(*e) for e in edges])


GO_NO_GO_PHASES = (None, 0, 1, 2, 3, 3, 3, 3, 4, 0, 1, 2, 3, 3, 4)
GO_NO_GO_ROWS = (None, "go", "go", "go", "go", "go", "go", "go", "go", "nogo", "nogo", "nogo", "nogo", "nogo", "nogo")


def animal_licking_only_on_go(table: rp.Table, params, ticks: int, interp: int = rp.INTERP_VERSION):
    """Pokes whenever a Wait watches the port, licks only in the go window (state 3)."""
    core, first = rp.begin(table, params, 7, 0, interp)
    actions, port, lick = [(0, first)], False, False
    for now in range(1, ticks + 1):
        rose = fell = 0
        state = core.state
        if state in (1, 9) and not port:
            rose |= 1
        elif state not in (1, 9) and port:
            fell |= 1
        if state == 3 and not lick:
            rose |= 2
        elif state != 3 and lick:
            fell |= 2
        port ^= bool((rose | fell) & 1)
        lick ^= bool((rose | fell) & 2)
        core, a = rp.step(core, rp.Edges(rose, fell), now)
        if not a.idle:
            actions.append((now, a))
    return actions


@pytest.mark.parametrize("pick", [False, True], ids=["chance", "pick"])
def test_a_perfect_go_no_go_session_scores_one_with_withheld_as_a_hit(pick: bool) -> None:
    table = go_no_go_table(pick_as_chance=not pick)
    actions = animal_licking_only_on_go(table, _PICK_PARAMS, 40000, interp=3 if pick else 2)
    trials = trial_table.trials_of(table, actions, end=None, phase_of=GO_NO_GO_PHASES, windows=frozenset({2}))
    naming = trial_table.Naming(inputs=("port", "resp"), outputs=("cue", "o1", "o2", "reward"),
                                phase_of=GO_NO_GO_PHASES, phases=5, row_of=GO_NO_GO_ROWS,
                                rows={"go": ("Go", None), "nogo": ("No-go", None)})
    named = [trial_table.name(t, naming) for t in trials if t.complete][:10]
    assert len(named) == 10 and {t.row for t in named} == {"go", "nogo"}
    assert {t.outcome for t in named} == {"correct", "withheld"}
    score = table_metrics.score(named, rows=(("go", "Go"), ("nogo", "No-go")))
    assert [m.p_session for m in table_metrics.correct_metrics(score)] == [1.0, 1.0]
    assert table_metrics.overall_correct(score).p_session == 1.0
    assert table_metrics.HITS == frozenset({"correct", "withheld"})
