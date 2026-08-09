"""The inference rung — `analytics/infer.py`, `data.md` §8.3.

The claim under test: a run that resolves NO profile scores the same trials,
the same way, as it would have under the task's own declaration — because the
strobe registry is append-only and `checkResponse()`'s emission rules name the
correct side on every settled trial. The most important test here is the
equality pin: everything else could pass while inference quietly disagreed
with the declared path over identical data.
"""

from __future__ import annotations

from ephymeris_sidecar.analytics import derive, infer
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.tasks.profile import parse_profile

from tests.test_analytics_derive import GRGL_FULL, document

# The declared GRGL profile the inference must agree with: odor 1 (101) is
# answered right, odor 3 (103) left.
DECLARED = parse_profile(GRGL_FULL)

#: Realistic trial shapes carrying the evidence codes the firmware emits.
REWARDED_1 = [101, 226, 249, 253, 357]      # odor 1 → right, fluid: right correct
WRONG_1 = [101, 226, 248, 257]              # odor 1 → left, error: right correct
HOLD_FAIL_1 = [101, 226, 249, 251]          # right well, hold broken: right correct
REWARDED_3 = [103, 226, 248, 252, 369]      # odor 3 → left, fluid: left correct
WRONG_3 = [103, 226, 249, 258]              # odor 3 → right, error: left correct

SESSION = REWARDED_1 * 3 + WRONG_1 + HOLD_FAIL_1 + REWARDED_3 * 2 + WRONG_3


def by_trigger(profile):
    return {m.trigger_code: m for m in profile.live_metrics}


# --- what inference reads out of a stream -----------------------------------


def test_conditions_are_the_onsets_the_stream_presents() -> None:
    profile = infer.infer_profile(SESSION)
    assert profile is not None
    assert sorted(m.trigger_code for m in profile.live_metrics) == [101, 103]


def test_a_declared_code_the_session_never_presented_is_no_condition() -> None:
    """The registry declares twelve onsets; this stream presents two. Inference
    must not manufacture the other ten — a declared-but-absent condition is the
    profile's business, and inference has no profile."""
    profile = infer.infer_profile(REWARDED_1 * 5)
    assert profile is not None
    assert [m.trigger_code for m in profile.live_metrics] == [101]


def test_sides_are_read_from_fluid_error_and_early_evidence() -> None:
    """Each evidence kind alone must name the side: `FLUID_x` and
    `WATER_UNPOKE_EARLY_x` fire only at the correct well, `WATER_POKE_ERROR_x`
    only at the wrong one."""
    for stream, correct in (
        (REWARDED_1 * 2, 249),   # fluid on the right
        (WRONG_1 * 2, 249),      # error on the left → right is correct
        (HOLD_FAIL_1 * 2, 249),  # early release at the right well
        (REWARDED_3 * 2, 248),
        (WRONG_3 * 2, 248),
    ):
        profile = infer.infer_profile(stream)
        assert profile is not None
        metric = by_trigger(profile)[stream[0]]
        assert metric.success_code == correct, stream


def test_majority_wins_over_a_corrupt_minority() -> None:
    """A hand-edited file can hold anything; one wrong-way vote must not flip
    a session's worth of consistent evidence."""
    # Nine trials say right is correct; one stray FLUID_L says left.
    stream = REWARDED_1 * 9 + [101, 226, 248, 252]
    profile = infer.infer_profile(stream)
    assert profile is not None
    assert by_trigger(profile)[101].success_code == 249


def test_a_never_answered_condition_still_delimits_trials() -> None:
    """The trap `boundaries_for` documents, from the inference side: odor 3
    trials the animal ignored must still CLOSE the odor 1 trial that precedes
    them, or its outcome is stolen by whichever trial answers next."""
    # odor 1 (unanswered), odor 3 opens next trial, THEN a right poke: the poke
    # belongs to the odor-3 trial, not the abandoned odor-1 trial.
    stream = REWARDED_1 + [101, 226] + [103, 226, 249, 258] + REWARDED_3
    profile = infer.infer_profile(stream)
    assert profile is not None
    summary = derive.summarize(document(stream), profile)
    one = next(m for m in summary.metrics if m.triggered == 2)
    assert one.counted == 1, "the abandoned odor-1 trial must be excluded, not mis-scored"
    assert one.excluded == 1


def test_no_onsets_means_no_profile() -> None:
    """A utility sketch's stream — lights, pokes, no stimulus — infers nothing.
    'no-metrics' stays the honest answer for it."""
    assert infer.infer_profile([222, 224, 226, 233]) is None
    assert infer.infer_profile([]) is None


def test_retired_codes_are_not_conditions() -> None:
    """110–113 are the dummy solenoid clicks 29 real sessions contain. They sit
    in the retired registry — a legacy stream carries them BETWEEN trials, and
    treating one as a condition would shred every real trial's scoring."""
    stream = REWARDED_1 + [110, 112] + REWARDED_3
    profile = infer.infer_profile(stream)
    assert profile is not None
    assert sorted(m.trigger_code for m in profile.live_metrics) == [101, 103]
    # ...but their names still label the raw log.
    assert profile.strobes[110].startswith("DUMMY_SOLENOID")


def test_lights_on_is_not_a_condition() -> None:
    """`LIGHTS_ON` ends in `_ON` and fires on every trial; the `_<digit>_ON`
    shape rule is what keeps it out — same rule as the task editor's picker."""
    profile = infer.infer_profile([222] + REWARDED_1 + [222] + REWARDED_1)
    assert profile is not None
    assert [m.trigger_code for m in profile.live_metrics] == [101]


def test_withhold_evidence_makes_a_no_go_condition() -> None:
    """`WATER_POKE_NONE` is the correctly-withheld answer; a condition whose
    trials withhold is scored as the generator would score a declared no-go."""
    nogo = [105, 226, 256]  # odor 5, sampled, correctly withheld
    profile = infer.infer_profile(nogo * 3)
    assert profile is not None
    metric = by_trigger(profile)[105]
    assert metric.success_code == 256
    assert "withhold" in metric.label


# --- the equality pin -------------------------------------------------------


def test_inference_scores_exactly_as_the_declared_profile_does() -> None:
    """The whole point: on the same stream, the inferred profile and the task's
    own declaration must produce the same counted trials, the same hits, and
    the same pooled accuracy — anything less and the fallback silently changes
    the science for exactly the runs nobody can re-check."""
    doc = document(SESSION)
    declared = derive.summarize(doc, DECLARED)
    inferred = derive.summarize(doc, infer.infer_profile(SESSION))

    assert declared.status == inferred.status == "ok"
    assert declared.overall is not None and inferred.overall is not None
    assert declared.overall.p_session == inferred.overall.p_session
    assert declared.overall.counted == inferred.overall.counted

    by_declared = {m.triggered: m for m in declared.metrics}
    for metric in inferred.metrics:
        twin = by_declared[metric.triggered]
        assert metric.p_session == twin.p_session
        assert metric.counted == twin.counted
        assert metric.excluded == twin.excluded

    # The outcome tally and the engagement ladder read the same universal
    # names, so they must agree too.
    assert declared.outcomes == inferred.outcomes


def test_inferred_labels_carry_the_side_and_the_stimulus() -> None:
    profile = infer.infer_profile(SESSION)
    assert profile is not None
    labels = sorted(m.label for m in profile.live_metrics)
    assert labels == ["P(left well | odor 3)", "P(right well | odor 1)"]


def test_the_sketch_name_labels_the_profile_and_decides_nothing() -> None:
    a = infer.infer_profile(SESSION, sketch_name="GRGL_2-Odor")
    b = infer.infer_profile(SESSION)
    assert a is not None and b is not None
    assert a.task_name == "GRGL_2-Odor"
    assert b.task_name == infer.FALLBACK_NAME
    assert [m.to_json() for m in a.live_metrics] == [m.to_json() for m in b.live_metrics]


def test_an_unanswered_condition_orients_deterministically_and_scores_nothing() -> None:
    """No evidence, no pokes — so the arbitrary orientation is provably inert,
    and it must be the SAME arbitrary orientation every pass or the run would
    flip between profile groups on rescan."""
    stream = REWARDED_1 * 2 + [103, 226] * 3  # odor 3 sampled, never answered
    first = infer.infer_profile(stream)
    second = infer.infer_profile(stream)
    assert first is not None and second is not None
    assert [m.to_json() for m in first.live_metrics] == [
        m.to_json() for m in second.live_metrics
    ]
    summary = derive.summarize(document(stream), first)
    odor3 = next(m for m in summary.metrics if m.triggered == 3)
    assert odor3.counted == 0 and odor3.p_session is None


def test_the_registry_agrees_with_the_evidence_rules() -> None:
    """The codes inference votes with, pinned to the shipped registry — a
    renumbering (which the registry forbids) or a renamed slot field would
    otherwise fail silently as 'no evidence' and every side would fall back."""
    vocab = registry.vocabulary()
    slots = {n: vocab.port_slots[n] for n in vocab.port_slots}
    assert vocab.code_of(slots[1]["reward_code"]) == 252
    assert vocab.code_of(slots[2]["reward_code"]) == 253
    assert vocab.code_of(slots[1]["error_code"]) == 257
    assert vocab.code_of(slots[2]["error_code"]) == 258
    assert vocab.code_of(slots[1]["break_code"]) == 250
    assert vocab.code_of(slots[2]["break_code"]) == 251
    assert vocab.code_of("WATER_POKE_NONE") == 256
