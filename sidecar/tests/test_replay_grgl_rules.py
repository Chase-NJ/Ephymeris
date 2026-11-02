"""The core's GRGL rules (`INTERP` 7, BoxInterp.h's GRGL RULES): an escalating
penalty, a state that waits for an input to be low, aborts that repeat and do
not count, and anti-bias with GRGL's strength, clamp and run cap.

Each rule is checked on a small table written by hand, through `replay.py`.
The differential test holds BoxInterp.h to the same actions tick for tick.
"""

from __future__ import annotations

from collections import Counter

import pytest

from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.taskdef import lowering

NONE = rp.NONE
CORRECT = lowering.OUTCOME_CORRECT
ABORT = lowering.OUTCOME_ABORT_BEFORE
SKIPPED = lowering.class_mask(lowering.EXCLUDED_CLASSES)
HITS = lowering.class_mask(lowering.HIT_CLASSES)


def run(table: rp.Table, params: list[int], events=(), ticks: int = 100_000, seed: int = 7):  # noqa: ANN001, ANN201
    return rp.replay(table, params, seed, list(events), ticks)


def entries_of(actions, state: int) -> list[int]:  # noqa: ANN001
    return [now for now, a in actions if state in a.entered]


# --- the escalating penalty ---------------------------------------------------


def lazy_table() -> rp.Table:
    """A trial: wait for a poke (bit 0) for params[0] ms. A poke is correct and
    runs params[4]; a timeout is an abort whose penalty escalates from params[1]
    by params[2] a time, capped at params[3]."""
    states = [
        rp.StateRow(watch=1, timer_min=0, timer_max=0, on_timeout=1, edge_first=0, edge_count=1,
                    flags=rp.STARTS_TRIAL),
        rp.StateRow(timer_min=1, timer_max=1, on_timeout=0, flags=rp.ESCALATE, outcome=ABORT),
        rp.StateRow(timer_min=4, timer_max=4, on_timeout=0, outcome=CORRECT),
    ]
    edges = [rp.EdgeRow(0, rp.RISE, 2)]
    blocks = rp.Blocks(rows=[rp.Block()], skipped=SKIPPED, hits=HITS, lazy_step=2, lazy_max=3)
    return rp.Table(states=states, edges=edges, blocks=blocks)


def penalties(actions, start: int = 0) -> list[int]:  # noqa: ANN001
    """How long each stay in the penalty state lasted."""
    entered = entries_of(actions, 1)
    left = entries_of(actions, 0)
    return [min(t for t in left if t > e) - e for e in entered if e >= start and any(t > e for t in left)]


def test_a_penalty_escalates_by_its_step_up_to_its_cap():
    actions = run(lazy_table(), [100, 6000, 6000, 30000, 500], ticks=200_000)
    assert penalties(actions)[:7] == [6000, 12000, 18000, 24000, 30000, 30000, 30000]


def test_only_a_hit_resets_the_escalation():
    # Two lazy trials (6 s, 12 s), then a poke: correct. The next lazy trial is back at 6 s.
    first_poke = 100 + 6000 + 100 + 12000 + 50
    actions = run(lazy_table(), [100, 6000, 6000, 30000, 500], [(first_poke, rp.Edges(rose=1))], ticks=60_000)
    assert penalties(actions)[:3] == [6000, 12000, 6000]


def test_an_escalating_state_needs_interp_7():
    with pytest.raises(ValueError, match="INTERP 6"):
        rp.check_interp(lazy_table(), 6)


# --- waiting for an input to be low --------------------------------------------


def await_table() -> rp.Table:
    """Wait for a rise on bit 0 (state 0), hold it for params[0] ms (state 1, its
    level watched), then wait for its release (state 2, AWAIT_LOW), then params[1] ms."""
    states = [
        rp.StateRow(watch=1, edge_first=0, edge_count=1, flags=rp.STARTS_TRIAL),
        rp.StateRow(watch=1, timer_min=0, timer_max=0, on_timeout=2),
        rp.StateRow(watch=1, edge_first=1, edge_count=1, flags=rp.AWAIT_LOW),
        rp.StateRow(timer_min=1, timer_max=1, on_timeout=0, outcome=CORRECT),
    ]
    edges = [rp.EdgeRow(0, rp.RISE, 1), rp.EdgeRow(0, rp.FALL, 3)]
    return rp.Table(states=states, edges=edges, blocks=rp.Blocks(rows=[rp.Block()], hits=HITS))


def test_an_await_state_waits_for_the_release_when_the_input_is_still_up():
    actions = run(await_table(), [200, 1000], [(10, rp.Edges(rose=1)), (900, rp.Edges(fell=1))], ticks=1500)
    assert entries_of(actions, 2) == [210] and entries_of(actions, 3) == [900]


def test_an_await_state_is_left_at_once_when_the_input_is_already_down():
    # Released during the hold, which watches the input: its level is known to be low.
    actions = run(await_table(), [200, 1000], [(10, rp.Edges(rose=1)), (100, rp.Edges(fell=1))], ticks=1500)
    assert entries_of(actions, 2) == [210] and entries_of(actions, 3) == [211]


# --- aborts that repeat and do not count ----------------------------------------


def abort_table(repeat: bool) -> rp.Table:
    """A pick of two rows (branches to states 1 and 2), each a Wait for bit 0 whose
    timeout is an abort (state 3) and whose poke is correct (state 4). Block 0
    runs params[1] trials."""
    states = [
        rp.StateRow(edge_first=0, edge_count=2, flags=rp.STARTS_TRIAL | rp.PICK),
        rp.StateRow(watch=1, timer_min=0, timer_max=0, on_timeout=3, edge_first=2, edge_count=1),
        rp.StateRow(watch=1, timer_min=0, timer_max=0, on_timeout=3, edge_first=3, edge_count=1),
        rp.StateRow(timer_min=0, timer_max=0, on_timeout=0, outcome=ABORT),
        rp.StateRow(timer_min=0, timer_max=0, on_timeout=0, outcome=CORRECT),
    ]
    edges = [rp.EdgeRow(0, 0, 1), rp.EdgeRow(0, 0, 2), rp.EdgeRow(0, rp.RISE, 4), rp.EdgeRow(0, rp.RISE, 4)]
    blocks = rp.Blocks(rows=[rp.Block(first=0, count=2, n_min=1, n_max=1)], skipped=SKIPPED, hits=HITS,
                       repeat_aborts=repeat)
    return rp.Table(states=states, edges=edges, blocks=blocks)


def trial_starts(actions):  # noqa: ANN001, ANN201
    return [(now, a) for now, a in actions if a.flags & rp.ACT_TRIAL_START]


def test_an_abort_repeats_its_row_and_is_reported_uncounted():
    # Nothing pokes, so every trial aborts: each repeats the first trial's row.
    actions = run(abort_table(True), [100, 3], ticks=2000, seed=11)
    starts = trial_starts(actions)
    rows = [a.entered[1] for _, a in starts]
    assert len(set(rows)) == 1
    assert all(a.flags & rp.ACT_UNCOUNTED and a.flags & rp.ACT_CORRECTION for _, a in starts[1:])
    assert not any(a.flags & rp.ACT_DONE for _, a in starts), "an abort never counts toward the block's N"


def test_counted_trials_still_end_the_block():
    # A poke 10 ms into each trial: three counted trials (starting at 0, 110 and
    # 220), then the blocks are done at the fourth start.
    pokes = [(t, rp.Edges(rose=1)) for t in (10, 120, 230)]
    falls = [(t, rp.Edges(fell=1)) for t in (15, 125, 235)]
    actions = run(abort_table(True), [100, 3], sorted(pokes + falls), ticks=1000)
    done = [now for now, a in trial_starts(actions) if a.flags & rp.ACT_DONE]
    assert done == [330]


def test_without_the_switch_an_abort_counts_and_draws_fresh():
    actions = run(abort_table(False), [100, 3], ticks=2000, seed=11)
    starts = trial_starts(actions)
    assert not any(a.flags & rp.ACT_UNCOUNTED for _, a in starts)
    assert any(a.flags & rp.ACT_DONE for _, a in starts)


# --- GRGL's anti-bias -------------------------------------------------------------


def test_two_sided_weights_are_grgl_s_side_probabilities_in_permille():
    # pRight = 0.5 - strength * (2 * rights - L) / L, clamped to [pMin, pMax].
    assert rp.antibias_weights([15, 5], 20, 500, 20, 980) == [250, 750]
    assert rp.antibias_weights([10, 0], 10, 500, 20, 980) == [20, 980]
    assert rp.antibias_weights([0, 0], 0, 500, 20, 980) == [500, 500]


def test_n_sided_weights_sum_to_a_thousand_before_the_clamp():
    weights = rp.antibias_weights([6, 3, 3], 12, 500, 0, 1000)
    assert sum(weights) in (999, 1000) and weights[0] < weights[1] == weights[2]


def antibias_table(strength: int, max_run: int) -> rp.Table:
    """A pick of two rows on two sides; each trial a 100 ms ITI with no response.
    params[0] the ITI; params[1..4] strength, pMin, pMax and the run cap."""
    states = [
        rp.StateRow(edge_first=0, edge_count=2, flags=rp.STARTS_TRIAL | rp.PICK),
        rp.StateRow(timer_min=0, timer_max=0, on_timeout=0, outcome=CORRECT),
        rp.StateRow(timer_min=0, timer_max=0, on_timeout=0, outcome=CORRECT),
    ]
    edges = [rp.EdgeRow(0, 0, 1), rp.EdgeRow(0, 0, 2)]
    block = rp.Block(first=0, count=2, select=rp.ANTIBIAS, strength=1 if strength else NONE,
                     p_min=2, p_max=3, max_run=4 if max_run else NONE)
    blocks = rp.Blocks(rows=[block], entries=[rp.Entry(side=0), rp.Entry(side=1)], hits=HITS)
    return rp.Table(states=states, edges=edges, blocks=blocks)


def drawn_rows(actions):  # noqa: ANN001, ANN201
    return [a.entered[1] for _, a in trial_starts(actions)]


def test_the_run_cap_bounds_a_run_of_one_side():
    actions = run(antibias_table(strength=500, max_run=1), [100, 500, 20, 980, 2], ticks=100_000, seed=3)
    rows = drawn_rows(actions)
    runs = [len(list(g)) for _, g in __import__("itertools").groupby(rows)]
    assert len(rows) > 900 and max(runs) <= 2


def test_with_no_responses_the_draw_stays_even():
    actions = run(antibias_table(strength=500, max_run=0), [100, 500, 20, 980, 0], ticks=100_000, seed=5)
    shares = Counter(drawn_rows(actions))
    assert abs(shares[1] - shares[2]) < 0.1 * sum(shares.values())


def test_grgl_anti_bias_needs_interp_7():
    with pytest.raises(ValueError, match="INTERP 6"):
        rp.check_interp(antibias_table(500, 1), 6)


def test_a_version_6_table_runs_as_before():
    # Nothing a version 6 table holds reads any rule above, so its actions are unchanged.
    table = await_table()
    plain = rp.Table(states=[rp.StateRow(*s.__dict__.values()) for s in table.states[:2]]
                     + [rp.StateRow(watch=1, edge_first=1, edge_count=1)] + [table.states[3]],
                     edges=table.edges, blocks=rp.Blocks(rows=[rp.Block()], hits=HITS))
    rp.check_interp(plain, 6)
    actions = run(plain, [200, 1000], [(10, rp.Edges(rose=1)), (100, rp.Edges(fell=1))], ticks=1500)
    assert entries_of(actions, 3) == [], "a plain Wait for a release already past never ends"


def test_a_side_is_an_input_bit_or_none():
    # The C core holds at most 33 sides (an input bit, or NONE) on its stack.
    with pytest.raises(ValueError, match="side"):
        rp.Blocks(rows=[rp.Block(first=0, count=1, select=rp.ANTIBIAS)], entries=[rp.Entry(side=40)])
        rp.Table(states=[rp.StateRow(edge_first=0, edge_count=1, flags=rp.STARTS_TRIAL | rp.PICK),
                         rp.StateRow(timer_min=0, timer_max=0, on_timeout=0)],
                 edges=[rp.EdgeRow(0, 0, 1)],
                 blocks=rp.Blocks(rows=[rp.Block(first=0, count=1, select=rp.ANTIBIAS)],
                                  entries=[rp.Entry(side=40)]))
