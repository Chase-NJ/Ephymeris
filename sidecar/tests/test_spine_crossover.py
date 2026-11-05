"""A spine run on the panels a GRGL run feeds (#167, `ANALYTICS.md#rewarded-and-response-accuracy`).

A replayed trial table is tallied into the legacy shapes (`TrialOutcomes`,
`ConditionOutcomes`, `TrialEngagement`), so the cross-session panels read a
spine run as they read a legacy one, and response accuracy is legacy P(hit)'s
figure on both: the right well first, hold or not, with no response and aborts
left out.
"""

from __future__ import annotations

import pytest

from ephymeris_sidecar.analytics import stream
from ephymeris_sidecar.analytics.stream import crossover
from ephymeris_sidecar.analytics.stream import simulate as sim
from ephymeris_sidecar.analytics.stream.outcomes import TrialOutcomes
from ephymeris_sidecar.analytics.stream.trial_table import ReplayTrial
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef.model import TaskDefinition
from tests.fixtures import spine as fixture


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


def run(definition: dict, animal: str, seed: int = 5, **kwargs) -> dict:  # noqa: ANN003
    shot = generate.build_profile(TaskDefinition.from_json(definition)).to_json()
    return sim.simulate(shot, sim.Animal(animal, **kwargs), seed, limit_ms=10 * 60_000).document


def summary(document: dict):  # noqa: ANN201
    result = stream.summarize(document, None)
    assert result.status == "ok", result.detail
    return result


def two_afc(trials: int = 60, **edits) -> dict:  # noqa: ANN003
    return fixture.two_afc(blocks=[{"id": "b1", "rows": ["odor_1", "odor_2"], "trials": trials}], **edits)


# --- one trial, classified ------------------------------------------------------


def trial(outcome: str, response: str | None = None, rewarded: bool = False) -> ReplayTrial:
    return ReplayTrial(index=0, at_ms=0, row="r", outcome=outcome, response=response, rewarded=rewarded)


@pytest.mark.parametrize("t, bucket", [
    (trial("correct", "right_well", rewarded=True), "rewarded"),
    (trial("correct", "right_well"), "unpaid"),
    (trial("hold_broken", "right_well"), "hold_failed"),
    (trial("hold_broken", "left_well"), "wrong_well"),
    (trial("wrong_response", "left_well"), "wrong_well"),
    (trial("omission"), "no_response"),
    (trial("withheld"), "withheld"),
    (trial("false_alarm", "right_well"), "false_alarm"),
    (trial("abort_during_sampling"), "aborted"),
    (trial("abort_before_stimulus"), None),
])
def test_each_class_lands_in_its_legacy_bucket(t, bucket):
    assert crossover.bucket_of(t, correct="right_well") == bucket


def test_a_row_with_no_one_correct_response_reads_its_class():
    # A bandit row pays at either well: the class alone says it was right.
    assert crossover.bucket_of(trial("correct", "left_well", rewarded=True), correct=None) == "rewarded"
    assert crossover.bucket_of(trial("hold_broken", "left_well"), correct=None) == "hold_failed"


# --- response accuracy ------------------------------------------------------------


def test_response_accuracy_is_legacy_p_hit_on_a_legacy_tally():
    outcomes = TrialOutcomes(trials=10, administered=10, rewarded=5, hold_failed=1, wrong_well=2, no_response=2)
    assert outcomes.p_response == 6 / 8
    assert outcomes.to_json()["pResponse"] == 0.75


def test_a_withhold_is_a_hit_and_a_false_alarm_a_miss():
    outcomes = TrialOutcomes(trials=4, administered=4, withheld=3, false_alarm=1)
    assert outcomes.p_response == 3 / 4


def test_an_always_correct_spine_2afc_reads_one_on_every_panel():
    s = summary(run(two_afc(), "correct"))
    assert s.outcomes.p_response == 1.0 and s.outcomes.p_rewarded == 1.0
    assert s.outcomes.rewarded == s.outcomes.trials == 60
    assert [c.label for c in s.conditions] == ["Odor 1", "Odor 2"]
    assert [c.answer_side for c in s.conditions] == ["right", "left"]
    assert all(c.trigger_code is None for c in s.conditions)


def test_a_random_animal_s_response_accuracy_counts_right_and_wrong_wells_only():
    document = run(two_afc(200), "random")
    s = summary(document)
    table = stream.trial_table_of(document, None)["trials"]
    correct = {"odor_1": "right_well", "odor_2": "left_well"}
    answered = [t for t in table if t["response"] is not None and t["complete"]]
    right = sum(t["response"] == correct[t["row"]] for t in answered)
    assert s.outcomes.no_response == sum(t["outcome"] == "omission" for t in table if t["complete"])
    assert s.outcomes.p_response == pytest.approx(right / len(answered))


def test_a_correct_trial_whose_draw_failed_is_unpaid_and_still_right():
    doc = two_afc()
    for row in doc["rows"]:
        for entry in row["map"].values():
            if entry["outcome"] == "correct":
                entry["rewardPermille"] = 500
    s = summary(run(doc, "correct"))
    assert 0 < s.outcomes.unpaid < s.outcomes.trials
    assert s.outcomes.rewarded + s.outcomes.unpaid == s.outcomes.trials
    assert s.outcomes.p_response == 1.0 and s.outcomes.p_rewarded < 1.0


def test_go_no_go_rows_tally_withholds_and_false_alarms():
    doc = fixture.go_no_go(blocks=[{"id": "b1", "rows": ["go", "no_go"], "trials": 80}])
    correct = summary(run(doc, "correct"))
    assert correct.outcomes.withheld > 0 and correct.outcomes.false_alarm == 0
    assert correct.outcomes.p_response == 1.0
    random = summary(run(doc, "random"))
    assert random.outcomes.false_alarm > 0


def test_a_task_with_no_response_window_has_no_outcome_tally():
    s = summary(run(fixture.fixed_ratio(5), "correct"))
    assert s.outcomes is None and s.conditions == []


# --- engagement ---------------------------------------------------------------------


def test_an_engaged_animal_climbs_every_rung():
    s = summary(run(two_afc(), "correct"))
    e = s.engagement
    assert e.presented == e.poked == e.odor_delivered == 60


def test_an_animal_that_never_pokes_is_presented_and_nothing_more():
    s = summary(run(fixture.held_trial(), "silent"))
    e = s.engagement
    assert e.presented > 0 and e.poked == 0 and e.odor_delivered == 0


# --- the snapshot -------------------------------------------------------------------


def test_the_snapshot_names_each_response_port_s_side():
    shot = generate.build_profile(TaskDefinition.from_json(two_afc())).to_json()
    sides = {i["channel"]: i.get("side") for i in shot["spine"]["inputs"]}
    assert sides == {"odor_port": None, "left_well": "left", "right_well": "right"}
