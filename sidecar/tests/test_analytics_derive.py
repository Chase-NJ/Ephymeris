"""Derived metrics — `analytics.md` §3.

These numbers are the scientific output, so the tests are written against the
definition rather than against the implementation. The most important one is
`test_offline_scoring_equals_the_live_run`: everything else could pass while
the dashboard quietly disagreed with what the operator watched on Mission
Control, and that disagreement is the failure nobody would notice.
"""

from __future__ import annotations

from ephymeris_sidecar.analytics import derive
from ephymeris_sidecar.tasks.metrics import compute_series
from ephymeris_sidecar.tasks.profile import parse_profile

# The real GRGL profile: odor 1 should be answered right, odor 3 left.
GRGL = {
    "taskName": "GRGL 2-Odor Discrimination",
    "strobes": {
        "101": "ODOR_1_ON",
        "103": "ODOR_3_ON",
        "248": "WATER_POKE_L",
        "249": "WATER_POKE_R",
        "246": "END_SESSION",
    },
    "liveMetrics": [
        {
            "id": "p_r_odor1", "label": "P(R | Odor 1)",
            "triggerCode": 101, "successCode": 249, "alternateCode": 248,
            "windowSize": 20,
        },
        {
            "id": "p_l_odor3", "label": "P(L | Odor 3)",
            "triggerCode": 103, "successCode": 248, "alternateCode": 249,
            "windowSize": 20,
        },
    ],
}

PROFILE = parse_profile(GRGL)

HIT_1 = [101, 249]        # odor 1 → right: correct
MISS_1 = [101, 248]       # odor 1 → left: wrong, but a response
HIT_3 = [103, 248]        # odor 3 → left: correct
MISS_3 = [103, 249]


def document(codes: list[int], **extra) -> dict:
    """A session document with plausible 1s spacing between events."""
    return {
        "rat": "remy1",
        "sketch": "GRGL_2-Odor",
        "stop_reason": derive.CLEAN_STOP_REASON,
        "n_events": len(codes),
        "ts_data": [[code, index * 1000] for index, code in enumerate(codes)],
        **extra,
    }


# The full GRGL vocabulary, as a real task.json declares it — the outcome
# tally (§3.8) reads these by name, so the names matter as much as the codes.
GRGL_FULL = {
    **GRGL,
    "strobes": {
        **GRGL["strobes"],
        "226": "ODOR_UNPOKE",
        "225": "ODOR_UNPOKE_EARLY",
        "223": "LAZY_RAT",
        "250": "WATER_UNPOKE_EARLY_L",
        "251": "WATER_UNPOKE_EARLY_R",
        "252": "FLUID_L",
        "253": "FLUID_R",
        "257": "WATER_POKE_ERROR_L",
        "258": "WATER_POKE_ERROR_R",
        "357": "STOP_FLUID_G_R",
        "369": "STOP_FLUID_G_L",
    },
}

FULL_PROFILE = parse_profile(GRGL_FULL)

#: Odor 1, sampled to completion, right well, fluid delivered, delivery ends.
REWARDED_1 = [101, 226, 249, 253, 357]
#: Odor 1, correct well, released before the hold — no fluid.
HOLD_FAIL_1 = [101, 226, 249, 251]
#: Odor 1, wrong well.
WRONG_1 = [101, 226, 248, 257]
#: Odor 1, sampled but never answered.
NO_RESPONSE_1 = [101, 226]
#: Odor 1, the animal left the odor port early — never administered.
ABORTED_1 = [101, 225]


# --- §3.8 trial outcomes: rewarded vs side accuracy ------------------------


def test_each_outcome_lands_in_its_own_bucket() -> None:
    codes = REWARDED_1 + HOLD_FAIL_1 + WRONG_1 + NO_RESPONSE_1 + ABORTED_1
    out = derive.outcomes_of(codes, FULL_PROFILE)
    assert out is not None
    assert (out.rewarded, out.hold_failed, out.wrong_well) == (1, 1, 1)
    assert (out.no_response, out.aborted) == (1, 1)
    assert out.trials == 5
    # A trial the animal never engaged with is not evidence about
    # discrimination, so it stays out of the denominator.
    assert out.administered == 4


def test_side_accuracy_credits_a_hold_failure_and_rewarded_accuracy_does_not() -> None:
    """The whole point of §3.8: the animal chose right, and earned nothing."""
    out = derive.outcomes_of(REWARDED_1 + HOLD_FAIL_1, FULL_PROFILE)
    assert out is not None
    assert out.p_rewarded == 0.5, "a hold failure is not a reward"
    assert out.p_side == 1.0, "but the correct side was chosen both times"


def test_side_accuracy_is_never_below_rewarded_accuracy() -> None:
    codes = REWARDED_1 * 3 + HOLD_FAIL_1 * 2 + WRONG_1 + NO_RESPONSE_1
    out = derive.outcomes_of(codes, FULL_PROFILE)
    assert out is not None
    assert out.p_side is not None and out.p_rewarded is not None
    assert out.p_side >= out.p_rewarded


def test_the_end_of_delivery_is_not_a_second_reward() -> None:
    """`STOP_FLUID_G_R` contains the word FLUID and marks delivery *ending*.

    An unanchored match would count it, doubling every rewarded trial — and the
    number would still look plausible, which is what makes it worth a test.
    """
    out = derive.outcomes_of(REWARDED_1, FULL_PROFILE)
    assert out is not None
    assert out.rewarded == 1


def test_an_early_odor_unpoke_is_not_a_completed_sample() -> None:
    """`ODOR_UNPOKE_EARLY` is the opposite event to `ODOR_UNPOKE`."""
    out = derive.outcomes_of(ABORTED_1, FULL_PROFILE)
    assert out is not None
    assert out.administered == 0 and out.aborted == 1
    assert out.p_rewarded is None, "no administered trials is null, never zero"


def test_an_unanswered_trial_closes_at_the_next_odor() -> None:
    """Same boundary rule the metrics use — otherwise the next trial's reward
    would be attributed to the trial that was abandoned."""
    out = derive.outcomes_of(NO_RESPONSE_1 + REWARDED_1, FULL_PROFILE)
    assert out is not None
    assert out.no_response == 1 and out.rewarded == 1


def test_a_profile_without_the_vocabulary_reports_no_outcomes() -> None:
    """The bare GRGL fixture declares no FLUID or ODOR_UNPOKE codes.

    Absent, not zeroed: "this task has no notion of reward delivery" is a
    different claim from "this animal earned nothing".
    """
    assert derive.outcomes_of(HIT_1 + HIT_3, PROFILE) is None
    assert derive.outcomes_of(HIT_1, None) is None


def test_outcomes_ride_along_on_the_summary() -> None:
    summary = derive.summarize(document(REWARDED_1 + WRONG_1), FULL_PROFILE)
    assert summary.outcomes is not None
    payload = summary.to_json()["outcomes"]
    assert payload["rewarded"] == 1 and payload["wrongWell"] == 1
    assert payload["pRewarded"] == 0.5
    # A band needs an interval, and it must stay inside the unit range.
    assert 0.0 <= payload["rewardedLow"] <= payload["pRewarded"] <= payload["rewardedHigh"] <= 1.0


def test_a_run_whose_profile_lacks_the_vocabulary_has_null_outcomes() -> None:
    assert derive.summarize(document(HIT_1), PROFILE).to_json()["outcomes"] is None


def test_rewarded_accuracy_is_independent_of_the_declared_metrics() -> None:
    """A side-biased animal scores at chance on the pooled metric while its
    rewarded accuracy reflects what it actually earned — the two answer
    different questions and must not track each other by construction."""
    # Always goes right: correct on odor 1, wrong on odor 3.
    codes = (REWARDED_1 + [103, 226, 249, 258]) * 5
    summary = derive.summarize(document(codes), FULL_PROFILE)
    assert summary.overall is not None and summary.overall.p_session == 0.5
    assert summary.outcomes is not None and summary.outcomes.p_rewarded == 0.5
    # ...and with hold failures on the rewarded half, they diverge.
    codes2 = (HOLD_FAIL_1 + [103, 226, 249, 258]) * 5
    summary2 = derive.summarize(document(codes2), FULL_PROFILE)
    assert summary2.overall is not None and summary2.overall.p_session == 0.5
    assert summary2.outcomes is not None and summary2.outcomes.p_rewarded == 0.0
    assert summary2.outcomes.p_side == 0.5


# --- §3.1 the boundary-code trap ------------------------------------------


def test_boundaries_are_the_union_of_every_trigger() -> None:
    assert derive.boundaries_for(PROFILE) == frozenset({101, 103})


def test_an_unanswered_trial_is_excluded_not_mis_scored() -> None:
    """The single most important behaviour in this module.

    Odor 1 fires, the animal doesn't respond, odor 3 fires, and *then* it pokes
    left. That left poke belongs to the odor-3 trial. Scored with only its own
    trigger as a boundary — `compute_series`' default — metric 1 would still be
    waiting and would count the poke as its own miss.
    """
    codes = [101, 103, 248]
    metric = PROFILE.live_metrics[0]

    correct = compute_series(metric, codes, derive.boundaries_for(PROFILE))
    wrong = compute_series(metric, codes)  # the default: own trigger only

    assert correct == [], "the abandoned odor-1 trial must be excluded entirely"
    assert wrong == [0.0], "this is the mis-scoring the union of triggers prevents"


def test_offline_scoring_equals_the_live_run() -> None:
    """Replaying a recorded stream must reproduce what Mission Control showed.

    The live path feeds `MetricAccumulator` one strobe at a time; the offline
    path replays the whole list. If these ever disagree, every recorded number
    in the app is subtly wrong and nothing else in this file would catch it.
    """
    codes = (
        HIT_1 + HIT_3 + MISS_1 + HIT_3 + [101, 103, 248] + HIT_1 + MISS_3 + HIT_1
    )
    summary = derive.summarize(document(codes), PROFILE)
    live = dict((mid, (value, n)) for mid, value, n in derive.live_equivalent(PROFILE, codes))

    for metric in summary.metrics:
        live_value, live_n = live[metric.id]
        assert metric.p_window == live_value, f"{metric.id} rolling value drifted from live"
        assert metric.counted == live_n, f"{metric.id} counted trials drifted from live"


# --- §3.2 two probabilities, never one ------------------------------------


def test_p_session_and_p_window_differ_when_the_window_is_short() -> None:
    """They are not interchangeable, which is why both are reported."""
    narrow = parse_profile(
        {**GRGL, "liveMetrics": [{**GRGL["liveMetrics"][0], "windowSize": 2}]}
    )
    # Four wrong, then two right: the last-2 window sees 1.0, the session 0.33.
    codes = MISS_1 * 4 + HIT_1 * 2
    metric = derive.summarize(document(codes), narrow).metrics[0]

    assert metric.p_window == 1.0
    assert metric.p_session is not None and abs(metric.p_session - 2 / 6) < 1e-9
    assert metric.counted == 6, "counted is every scored trial, not the window length"


def test_p_session_ignores_the_authored_window_entirely() -> None:
    codes = HIT_1 * 30 + MISS_1 * 30
    metric = derive.summarize(document(codes), PROFILE).metrics[0]
    assert metric.p_session == 0.5
    # The rolling window (20) sits entirely inside the trailing misses.
    assert metric.p_window == 0.0


# --- pooled accuracy -------------------------------------------------------


def test_a_side_biased_animal_scores_at_chance_overall() -> None:
    """Why the pooled figure exists at all.

    An animal that pokes right on every trial is correct on every odor-1 trial
    and wrong on every odor-3 trial. Read on either metric alone it looks like
    one of the best or one of the worst animals in the cohort; pooled, it sits
    at chance — which is the truth, and what a heatmap asking "who is stuck"
    has to show.
    """
    always_right = ([101, 249] + [103, 249]) * 20
    summary = derive.summarize(document(always_right), PROFILE)
    by_id = {m.id: m for m in summary.metrics}

    assert by_id["p_r_odor1"].p_session == 1.0, "perfect, read alone"
    assert by_id["p_l_odor3"].p_session == 0.0, "hopeless, read alone"
    assert summary.overall is not None
    assert summary.overall.p_session == 0.5, "at chance, which is the honest reading"


def test_overall_pools_trials_rather_than_averaging_proportions() -> None:
    """Weighted by how the session actually ran, not by condition count."""
    # 10 odor-1 trials all correct, 2 odor-3 trials both wrong: 10/12, not 0.5.
    codes = HIT_1 * 10 + MISS_3 * 2
    summary = derive.summarize(document(codes), PROFILE)
    assert summary.overall is not None
    assert abs(summary.overall.p_session - 10 / 12) < 1e-9
    assert summary.overall.counted == 12


def test_overall_is_absent_when_nothing_scored() -> None:
    assert derive.summarize(document([101, 101]), PROFILE).overall is None


def test_a_profile_less_run_has_no_overall() -> None:
    assert derive.summarize(document([221, 222]), None).overall is None


# --- §3.3 trial counts -----------------------------------------------------


def test_excluded_counts_the_unanswered_trials() -> None:
    codes = HIT_1 + [101, 103, 248] + HIT_1
    metric = derive.summarize(document(codes), PROFILE).metrics[0]
    assert metric.triggered == 3
    assert metric.counted == 2
    assert metric.excluded == 1


# --- §3.5 uncertainty ------------------------------------------------------


def test_a_wilson_interval_never_leaves_the_unit_range() -> None:
    """The reason for Wilson over the normal approximation.

    Three of three correct is where the normal approximation gives a zero-width
    interval at exactly 1.0, or runs past it.
    """
    low, high = derive.wilson_interval(3, 3)
    assert 0.0 <= low < high <= 1.0
    assert low < 1.0, "a 3/3 estimate must not claim certainty"


def test_wilson_narrows_as_n_grows() -> None:
    small_low, small_high = derive.wilson_interval(8, 10)
    large_low, large_high = derive.wilson_interval(800, 1000)
    assert (large_high - large_low) < (small_high - small_low)


def test_no_interval_without_trials() -> None:
    assert derive.wilson_interval(0, 0) is None


def test_low_confidence_is_flagged_but_the_value_is_still_reported() -> None:
    """The sidecar never suppresses — presentation decides (§3.5)."""
    metric = derive.summarize(document(HIT_1 * 3), PROFILE, min_counted=10).metrics[0]
    assert metric.low_confidence is True
    assert metric.p_session == 1.0, "the value is reported regardless"
    assert metric.counted == 3


# --- §3.6 edge cases -------------------------------------------------------


def test_zero_counted_trials_is_null_never_zero() -> None:
    """Zero percent and 'no trials' are opposite claims about an animal."""
    metric = derive.summarize(document([101, 101, 101]), PROFILE).metrics[0]
    assert metric.p_session is None
    assert metric.p_window is None
    assert metric.counted == 0
    assert metric.triggered == 3
    assert metric.wilson_low is None


def test_a_profile_less_run_is_listed_with_no_metrics() -> None:
    """Still worth listing — it has a real duration, event count and reason."""
    summary = derive.summarize(document([221, 222, 223]), None)
    assert summary.status == "no-metrics"
    assert summary.metrics == []
    assert summary.total_events == 3
    assert summary.duration_ms == 2000


def test_a_utility_profile_is_scored_but_left_out_of_aggregates() -> None:
    utility = parse_profile({**GRGL, "kind": "utility"})
    summary = derive.summarize(document(HIT_1 * 3), utility)
    assert summary.status == "ok"
    assert summary.excluded_by_default is True
    assert summary.metrics[0].counted == 3


def test_a_board_drop_is_included_and_marked_unclean() -> None:
    summary = derive.summarize(
        document(HIT_1 * 20, stop_reason="board disconnected"), PROFILE
    )
    assert summary.status == "ok"
    assert summary.clean is False
    assert summary.stop_reason == "board disconnected"
    assert summary.metrics[0].counted == 20, "a drop at trial 20 is still 20 good trials"


def test_a_clean_end_is_marked_clean() -> None:
    assert derive.summarize(document(HIT_1), PROFILE).clean is True


def test_malformed_ts_data_rows_are_skipped_not_fatal() -> None:
    """A hand-edited or recovery-produced file must not kill an indexing pass."""
    doc = {
        "stop_reason": "operator stop",
        "ts_data": [[101, 0], "nonsense", [], [249, 1000], [None, 2000], 42],
    }
    summary = derive.summarize(doc, PROFILE)
    assert summary.total_events == 2
    assert summary.metrics[0].counted == 1


def test_a_document_with_no_ts_data_at_all() -> None:
    summary = derive.summarize({"stop_reason": "sidecar error"}, PROFILE)
    assert summary.total_events == 0
    assert summary.duration_ms is None
    assert summary.metrics[0].p_session is None


def test_the_seed_is_carried_when_present() -> None:
    assert derive.summarize(document(HIT_1, trial_seed=288577176), PROFILE).seed == 288577176
    assert derive.summarize(document(HIT_1), PROFILE).seed is None


# --- §5 the within-session series -----------------------------------------


def test_the_series_has_one_point_per_counted_trial() -> None:
    codes = HIT_1 + MISS_1 + HIT_1 + [101, 103, 248]
    metrics = derive.series(document(codes), PROFILE)
    first = next(m for m in metrics if m.id == "p_r_odor1")
    assert first.values == [1.0, 0.5, 2 / 3]
    assert len(first.counts) == len(first.values)


def test_series_counts_are_window_lengths_not_cumulative_totals() -> None:
    """The n a confidence band must use is the window, capped at windowSize."""
    narrow = parse_profile(
        {**GRGL, "liveMetrics": [{**GRGL["liveMetrics"][0], "windowSize": 3}]}
    )
    metrics = derive.series(document(HIT_1 * 5), narrow)
    assert metrics[0].counts == [1, 2, 3, 3, 3]


def test_cumulative_mode_widens_the_window() -> None:
    codes = MISS_1 * 4 + HIT_1 * 2
    narrow = parse_profile(
        {**GRGL, "liveMetrics": [{**GRGL["liveMetrics"][0], "windowSize": 2}]}
    )
    rolling = derive.series(document(codes), narrow, mode="rolling")[0]
    cumulative = derive.series(document(codes), narrow, mode="cumulative")[0]
    assert rolling.values[-1] == 1.0
    assert abs(cumulative.values[-1] - 2 / 6) < 1e-9


def test_series_can_be_filtered_to_one_metric() -> None:
    metrics = derive.series(document(HIT_1 + HIT_3), PROFILE, metric_ids=["p_l_odor3"])
    assert [m.id for m in metrics] == ["p_l_odor3"]


def test_a_profile_less_run_has_no_series() -> None:
    assert derive.series(document([221, 222]), None) == []


# --- wire shaping ----------------------------------------------------------


def test_values_are_rounded_on_the_wire() -> None:
    """Six decimals — smaller frames, and no 0.8500000000000001 in a tooltip."""
    codes = HIT_1 * 2 + MISS_1
    payload = derive.summarize(document(codes), PROFILE).to_json()
    value = payload["metrics"][0]["pSession"]
    assert value == round(2 / 3, 6)
