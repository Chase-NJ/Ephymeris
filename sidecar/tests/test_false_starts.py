"""False starts — `DATA.md#false-starts`.

A wrong call either way is plausible-looking data: count a false start and a
session mean is dragged by a three-trial run and what-changed calls the real
run "unchanged"; set aside a real run and an animal's session quietly vanishes
from every curve. Hence two required conditions, a fail-toward-counting rule
for unknowns, and a person's override beating both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import false_starts
from ephymeris_sidecar.analytics.false_starts import RunFacts, classify
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.logbook import diff, mirror
from tests.test_analytics_service import HIT_1, MISS_1, Rig


def facts(run_id: str, order: str, trials: int | None, *, animal: str = "a1", session: str = "s1"):
    return RunFacts(run_id=run_id, session_id=session, animal_id=animal, order=order, trials=trials)


# --- the rule ------------------------------------------------------------------


def test_a_short_run_that_was_restarted_is_a_false_start():
    verdicts = classify([facts("first", "10:00:00", 3), facts("second", "10:04:00", 220)])
    assert verdicts["first"].false_start and verdicts["first"].source == "automatic"
    assert verdicts["first"].restarted_by == "second"
    assert not verdicts["second"].false_start


def test_a_short_run_nobody_restarted_is_data():
    """An animal that quit after four trials ran a session."""
    assert not classify([facts("only", "10:00:00", 4)])["only"].false_start


def test_a_long_first_run_interrupted_for_a_reason_still_counts():
    verdicts = classify([facts("first", "10:00:00", 150), facts("second", "11:00:00", 90)])
    assert not verdicts["first"].false_start


def test_trials_fall_back_to_the_metrics_when_outcomes_are_not_tallied():
    summary = {"outcomes": None, "metrics": [{"triggered": 2}, {"triggered": 1}]}
    assert false_starts.trials_of(summary) == 3
    assert false_starts.trials_of({"outcomes": {"trials": 7}, "metrics": []}) == 7
    assert false_starts.trials_of({"outcomes": None, "metrics": []}) is None


def test_an_unscored_run_is_never_set_aside_by_the_rule():
    verdicts = classify([facts("first", "10:00:00", None), facts("second", "10:05:00", 200)])
    assert not verdicts["first"].false_start


def test_only_the_same_animal_in_the_same_session_restarts_a_run():
    verdicts = classify([
        facts("a1-run", "10:00:00", 2, animal="a1"),
        facts("a2-run", "10:05:00", 200, animal="a2"),
        facts("a1-tomorrow", "10:05:00", 200, session="s2"),
    ])
    assert not verdicts["a1-run"].false_start


def test_order_follows_the_file_name_not_the_row():
    """A recorded run stamps UTC; an adopted one, local time from its folder.
    The file stem's HHMMSS is the one clock both share."""
    early = false_starts.order_key("/x/remy1_2O-Bdisc_4_2026-07-22_093000.json", "2026-07-22T13:30:00+00:00")
    late = false_starts.order_key("/x/remy1_2O-Bdisc_4_2026-07-22_101500.json", "2026-07-22T10:15:00")
    assert early < late


@pytest.mark.parametrize(
    ("override", "expected", "source"),
    [(True, True, "marked"), (False, False, "restored"), (None, True, "automatic")],
)
def test_a_person_overrules_the_rule(override, expected, source):
    runs = [facts("first", "10:00:00", 3), facts("second", "10:04:00", 220)]
    overrides = {} if override is None else {"first": override}
    verdict = classify(runs, overrides)["first"]
    assert verdict.false_start is expected and verdict.source == source


def test_a_person_can_set_aside_a_run_the_rule_would_count():
    verdict = classify([facts("only", "10:00:00", 300)], {"only": True})["only"]
    assert verdict.false_start and verdict.source == "marked"


# --- what changed ----------------------------------------------------------------


def _compared(run_id: str, session: str, box: int) -> diff.ComparedRun:
    return diff.ComparedRun(
        id=run_id, session_id=session, animal_id="a1", box=box,
        task_identity="hash:x", task="GRGL", config={"iti": 4000}, params_hash="p",
    )


def test_the_restart_is_compared_with_the_previous_session_not_the_false_start():
    yesterday = _compared("yesterday", "s0", box=2)
    false_start = _compared("false-start", "s1", box=1)
    real = _compared("real", "s1", box=1)
    verdicts = classify([facts("false-start", "10:00:00", 2), facts("real", "10:04:00", 200),
                         facts("yesterday", "09:00:00", 200, session="s0")])

    changes = diff.compare([yesterday, false_start, real], verdicts)

    assert changes["false-start"]["falseStart"] is True
    assert changes["false-start"]["previousRunId"] is None
    assert changes["real"]["previousRunId"] == "yesterday"
    assert changes["real"]["boxChange"] == {"from": 2, "to": 1}, "the real change, not 'unchanged'"


def test_the_mirror_lists_a_false_start_without_comparing_it():
    lines = mirror.change_lines(
        [{"animalId": "a1", "box": 1, "first": False, "falseStart": True,
          "falseStartSource": "automatic", "params": []}],
        {"a1": "remy1"},
    )
    assert lines == ["- **remy1 (box 1)**: false start, set aside (restarted)"]


# --- end to end ------------------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    r = Rig(db, tmp_path)
    r.write_sketch()
    return r


async def test_the_summary_sets_a_false_start_aside_and_counts_it_nowhere(rig: Rig):
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 2, run_id="early",
                name="remy1_2O-Bdisc_1_2026-07-22_100000")
    rig.add_run(session, "a1", HIT_1 * 15 + MISS_1 * 5, run_id="late",
                name="remy1_2O-Bdisc_1_2026-07-22_100500")

    payload = await rig.service.summary(rig.cohort.id)

    assert [r["runId"] for r in payload["runs"]] == ["late"]
    assert [r["runId"] for r in payload["falseStarts"]] == ["early"]
    assert payload["falseStarts"][0]["restartedBy"] == "late"
    assert payload["counts"]["runs"] == 1 and payload["counts"]["falseStarts"] == 1
    assert sum(g["runCount"] for g in payload["profileGroups"]) == 1


async def test_a_ruling_moves_a_run_between_the_lists_and_back(rig: Rig):
    session = rig.add_session("1", "2026-07-22")
    rig.add_run(session, "a1", HIT_1 * 2, run_id="early",
                name="remy1_2O-Bdisc_1_2026-07-22_100000")
    rig.add_run(session, "a1", HIT_1 * 20, run_id="late",
                name="remy1_2O-Bdisc_1_2026-07-22_100500")

    rig.service.set_false_start(rig.cohort.id, "early", False)
    restored = await rig.service.summary(rig.cohort.id)
    early = next(r for r in restored["runs"] if r["runId"] == "early")
    assert early["falseStartSource"] == "restored" and not restored["falseStarts"]

    rig.service.set_false_start(rig.cohort.id, "early", None)
    assert [r["runId"] for r in (await rig.service.summary(rig.cohort.id))["falseStarts"]] == ["early"]

    with pytest.raises(KeyError):
        rig.service.set_false_start(rig.cohort.id, "not-a-run", True)
