"""Phase-window rates — `analytics/stream/rates.py`, `ANALYTICS.md#phase-window-rates`.

Every figure here is a function of the trial table: each counted phase's rate
per trial (its watched rises over the ticks it lasted), the mean per row with a
Student-t interval over trials, and the paired difference against the
channel's first counted phase. The expected numbers are worked by hand.
"""

from __future__ import annotations

import random

import pytest

from ephymeris_sidecar.analytics.stream import rates
from ephymeris_sidecar.analytics.stream import replay as rp
from ephymeris_sidecar.analytics.stream import stats
from ephymeris_sidecar.analytics.stream.trial_table import InputCount, ReplayTrial
from ephymeris_sidecar.taskdef import lowering, pavlovian

#: The trace spine's phase entries, ms after the trial's start: baseline 2 s,
#: CS 2 s, trace 1 s, the US and its window 3 s, the ITI 10 s.
OFFSETS = (0, 2000, 4000, 5000, 8000)
TRIAL_MS = 18000
ROWS = (("cs_plus", "CS+"), ("cs_minus", "CS−"))
WINDOWS = tuple(rates.Window(p, "lick_spout") for p in (0, 1, 2, 3))
LABELS = ("delay", "present", "delay", "outcome", "iti")


def trial(index: int, row: str, licks: dict[int, int], *, outcome: str = "correct", complete: bool = True,
          entries: tuple[int | None, ...] = OFFSETS) -> ReplayTrial:
    at = index * TRIAL_MS
    return ReplayTrial(
        index=index, at_ms=at, row=row, row_name=dict(ROWS)[row],
        phase_entries=tuple(None if e is None else at + e for e in entries),
        outcome=outcome, correct=outcome == "correct" or None,
        input_counts=tuple(InputCount(p, "lick_spout", n) for p, n in sorted(licks.items()) if n),
        complete=complete,
    )


def by(result, row: str, phase: int):  # noqa: ANN001, ANN201
    return next(w for w in result if w.row_id == row and w.phase == phase)


def test_a_rate_is_the_mean_per_trial_rate_with_its_t_interval():
    # CS+: CS rates 2, 3, 4, 5 /s over its 2 s; baseline 1, 1, 2, 1 /s; trace 3 /s throughout.
    table = [trial(k, "cs_plus", {0: b, 1: c, 2: 3})
             for k, (b, c) in enumerate([(2, 4), (2, 6), (4, 8), (2, 10)])]
    out = rates.window_rates(table, WINDOWS, rows=ROWS, labels=LABELS)
    cs = by(out, "cs_plus", 1)
    # mean 3.5, sd sqrt(5/3), t(0.975, 3) = 3.182446: 3.5 ± 2.054254.
    assert (cs.rate.n, cs.rate.mean) == (4, pytest.approx(3.5))
    assert (cs.rate.low, cs.rate.high) == (pytest.approx(1.445746, abs=1e-5), pytest.approx(5.554254, abs=1e-5))
    assert (cs.label, cs.channel, cs.reference) == ("present", "lick_spout", 0)
    # Paired against the baseline: 1, 2, 2, 4, mean 2.25, sd sqrt(4.75/3): 2.25 ± 2.002249.
    assert cs.versus.mean == pytest.approx(2.25)
    assert (cs.versus.low, cs.versus.high) == (pytest.approx(0.247751, abs=1e-5), pytest.approx(4.252249, abs=1e-5))
    trace = by(out, "cs_plus", 2)
    assert (trace.rate.mean, trace.rate.low, trace.rate.high) == (3.0, 3.0, 3.0), "no spread, no width"
    assert trace.versus.mean == pytest.approx(1.75)
    baseline = by(out, "cs_plus", 0)
    assert baseline.reference is None and baseline.versus is None, "the baseline is its own reference"
    assert baseline.rate.mean == pytest.approx(1.25)


def test_every_row_is_reported_and_one_with_no_trials_says_so():
    table = [trial(0, "cs_plus", {1: 4})]
    out = rates.window_rates(table, WINDOWS, rows=ROWS, labels=LABELS)
    assert [(w.row_id, w.phase) for w in out] == [(r, p) for r, _ in ROWS for p in (0, 1, 2, 3)]
    one = by(out, "cs_plus", 1)
    assert (one.rate.n, one.rate.mean, one.rate.low, one.rate.high) == (1, 2.0, None, None), \
        "one trial has a rate and no spread"
    none = by(out, "cs_minus", 1)
    assert (none.rate.n, none.rate.mean, none.versus.n) == (0, None, 0)
    assert none.low_confidence and one.low_confidence


def test_a_rates_interval_never_runs_below_zero():
    table = [trial(k, "cs_plus", {1: n}) for k, n in enumerate([0, 0, 0, 0, 0, 4])]
    cs = by(rates.window_rates(table, WINDOWS, rows=ROWS, labels=LABELS), "cs_plus", 1)
    assert cs.rate.low == 0.0 and cs.rate.high > 0
    assert cs.versus.low < 0, "a difference may"


def test_only_complete_unaborted_trials_with_a_known_span_count():
    table = [
        trial(0, "cs_plus", {1: 4}),
        trial(1, "cs_plus", {1: 40}, complete=False),                         # cut off by a crash
        trial(2, "cs_plus", {1: 40}, outcome="abort_during_sampling"),         # left mid-trial
        trial(3, "cs_plus", {0: 2}, entries=(0, None, None, None, 2000)),      # never reached the CS
        trial(4, "cs_plus", {1: 8}),
    ]
    out = rates.window_rates(table, WINDOWS, rows=ROWS, labels=LABELS)
    assert by(out, "cs_plus", 1).rate.n == 2 and by(out, "cs_plus", 1).rate.mean == pytest.approx(3.0)
    assert by(out, "cs_plus", 0).rate.n == 3, "the trial that stopped at its baseline still had one"


def test_the_last_phase_lasts_until_the_next_trial_and_the_last_trials_until_nothing():
    iti = (rates.Window(4, "lick_spout"),)
    table = [trial(0, "cs_plus", {4: 20}), trial(1, "cs_plus", {4: 20})]
    [plus, _] = rates.window_rates(table, iti, rows=ROWS, labels=LABELS)
    assert (plus.rate.n, plus.rate.mean) == (1, pytest.approx(2.0)), "10 s of ITI; the last ITI has no end"


def test_anticipatory_rates_from_a_lick_stream_of_known_rates():
    """Licks drawn as a Poisson stream at known rates per window, 200 trials a
    row: CS+ 1/s at baseline, 4/s in the CS and 6/s in the trace; CS− 1/s
    throughout. Each mean lands within its interval of the truth, and CS−'s
    anticipatory difference is zero within its interval."""
    rng = random.Random(116)
    truth = {"cs_plus": (1.0, 4.0, 6.0), "cs_minus": (1.0, 1.0, 1.0)}
    spans = (2.0, 2.0, 1.0)

    def poisson(mean: float) -> int:
        n, t = 0, rng.expovariate(1.0)
        while t < mean:
            n, t = n + 1, t + rng.expovariate(1.0)
        return n

    table = []
    for k in range(400):
        row = "cs_plus" if k % 2 == 0 else "cs_minus"
        table.append(trial(k, row, {p: poisson(truth[row][p] * spans[p]) for p in range(3)}))
    out = rates.window_rates(table, WINDOWS[:3], rows=ROWS, labels=LABELS)
    for row, rates_ in truth.items():
        for p, rate in enumerate(rates_):
            w = by(out, row, p)
            assert w.rate.n == 200 and w.rate.low <= rate <= w.rate.high, (row, p, w.rate)
            if p:
                assert w.versus.low <= rate - rates_[0] <= w.versus.high, (row, p, w.versus)
    assert by(out, "cs_plus", 2).versus.low > 3, "CS+ licks in anticipation"
    assert by(out, "cs_minus", 2).versus.low < 0 < by(out, "cs_minus", 2).versus.high


@pytest.mark.parametrize(("df", "t"), [(1, 12.706205), (2, 4.302653), (5, 2.570582), (10, 2.228139),
                                       (30, 2.042272), (31, 2.039513), (40, 2.021075), (120, 1.979930),
                                       (10**6, 1.959966)])
def test_the_t_quantile_is_the_published_one(df, t):
    assert stats.t_quantile_975(df) == pytest.approx(t, abs=2e-5)


# --- which phases are windows --------------------------------------------------


def table_of(raw: dict) -> tuple[rp.Table, tuple[int | None, ...], tuple[str, ...]]:
    slots = raw["slots"]
    low = lowering.lower(raw["spine"], inputs=[s["id"] for s in slots if s["type"] == "digital_in"],
                         outputs=[s["id"] for s in slots if s["type"] != "digital_in"],
                         rows=raw["rows"], blocks=raw["blocks"],
                         drives={s["id"]: "tone" for s in slots if s["type"] == "tone_out"})
    table = rp.Table(states=[rp.StateRow(*s) for s in low.states], edges=[rp.EdgeRow(*e) for e in low.edges])
    return table, low.phases, tuple(channel for _, channel in low.inputs)


def test_a_window_is_a_phase_that_counts_an_input_it_never_acts_on():
    table, phase_of, inputs = table_of(pavlovian.definition())
    names = tuple("lick_spout" for _ in inputs)
    assert rates.windows_of(table, phase_of, names) == tuple(rates.Window(p, "lick_spout") for p in range(4))
    delay, d_phase_of, _ = table_of(pavlovian.definition(trace=False))
    assert rates.windows_of(delay, d_phase_of, names) == tuple(rates.Window(p, "lick_spout") for p in range(3))


def test_a_wait_a_window_and_an_abort_are_not_windows():
    """A 2AFC's port, wells and an abort input are watched to be acted on, so
    it has no phase-window rates."""
    from tests.fixtures import spine as fixture

    raw = fixture.two_afc()
    raw["spine"][1]["abortOnEnter"] = "left"
    table, phase_of, inputs = table_of(raw)
    assert rates.windows_of(table, phase_of, inputs) == ()


def test_a_cached_rates_low_confidence_is_judged_again_on_every_request():
    """The threshold is a per-request argument and the payload is cached
    (`DATA.md#caching`), so `lowConfidence` is re-judged, as a metric's is."""
    from ephymeris_sidecar.analytics import scoring
    from ephymeris_sidecar.analytics.stream.summary import summarize, with_threshold

    payload = summarize(scoring._trace_canary(), None).to_json()
    assert payload["replay"]["rates"], "the canary trace run has rates"
    for threshold, low in ((2, False), (10, True)):
        judged = with_threshold(payload, threshold)["replay"]["rates"]
        assert {w["lowConfidence"] for w in judged} == {low}
