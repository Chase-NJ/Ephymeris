"""A legacy run read into its trial table
(`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`), and every figure read
off the table. `test_legacy_pin.py` pins that the numbers
did not move; this pins what the rows say.
"""

from __future__ import annotations

from typing import Any

from ephymeris_sidecar.analytics import stream
from ephymeris_sidecar.analytics.stream import trial_table
from ephymeris_sidecar.analytics.stream.legacy import decode, infer
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.rig.registry import Vocabulary
from ephymeris_sidecar.sessions.run_document import SNAPSHOT_KEY
from ephymeris_sidecar.tasks.profile import parse_profile

SEED = Vocabulary(registry.default_vocabulary_document())
code = SEED.code_of

#: The worked example's six presentations (`ANALYTICS.md#a-worked-example`).
WORKED = [
    "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_UNPOKE WATER_POKE_R FLUID_R STOP_FLUID_G_R",
    "LIGHTS_ON ODOR_POKE ODOR_3_ON ODOR_UNPOKE WATER_POKE_L WATER_UNPOKE_EARLY_L",
    "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_UNPOKE WATER_POKE_L WATER_POKE_ERROR_L",
    "LIGHTS_ON ODOR_POKE ODOR_3_ON ODOR_UNPOKE",
    "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_UNPOKE_EARLY",
    "LIGHTS_ON LAZY_RAT LIGHTS_OFF",
]


def document(lines: list[str]) -> dict[str, Any]:
    names = [name for line in lines for name in line.split()]
    return {"rat": "r", "sketch": "s", "ts_data": [[code(n), 1000 + 100 * i] for i, n in enumerate(names)]}


def metric(mid: str, onset: str, success: str, *alternates: str) -> dict[str, Any]:
    return {"id": mid, "label": mid, "triggerCode": code(onset), "successCode": code(success),
            "alternateCodes": [code(a) for a in alternates], "windowSize": 20}


def profile(*metrics: dict[str, Any]):
    return parse_profile({"taskName": "t", "strobes": {str(c): n for c, n in SEED.code_map().items()},
                          "liveMetrics": list(metrics)})


TWO_ODOR = profile(metric("r1", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L"),
                   metric("l3", "ODOR_3_ON", "WATER_POKE_L", "WATER_POKE_R"))


def test_the_worked_example_is_six_rows_in_the_outcome_classes() -> None:
    table = decode.table_of(document(WORKED), TWO_ODOR)
    rows = [(t.row, t.outcome, t.correct, t.rewarded, t.presented) for t in table.trials]
    assert rows == [
        ("r1", "correct", True, True, True),
        ("l3", "hold_broken", True, False, True),
        ("r1", "wrong_response", False, False, True),
        ("l3", "omission", None, False, True),
        ("r1", "abort_during_sampling", None, False, True),
        (None, None, None, False, True),
    ], "five onsets and a presentation never poked, in stream order"
    first = table.trials[0]
    assert (first.at_ms, first.response, first.response_ms, first.latency_ms) == (200, "WATER_POKE_R", 400, 200)
    assert (first.outcome_ms, first.reward_line, first.reward_ms) == (500, "FLUID_R", None)
    assert [t.index for t in table.trials] == list(range(6))


def test_what_a_legacy_run_cannot_know_is_empty_not_zero() -> None:
    table = decode.table_of(document(WORKED), TWO_ODOR)
    for t in table.trials:
        assert t.phase_entries == () and t.input_counts == (), "no phase is in the strobes"
        assert t.correction is None, "the strobes cannot say"
        assert t.block is None and t.level is None
    wire = table.to_json()
    assert wire["kind"] == "legacy" and wire["phases"] == []
    assert wire["gaps"] == ["phase-entries", "input-counts"]
    assert all(t["phaseEntries"] == [] and t["inputCounts"] == [] for t in wire["trials"])


def test_a_presentation_poked_and_let_go_before_odor_is_an_abort_before_the_stimulus() -> None:
    table = decode.table_of(document(["LIGHTS_ON ODOR_POKE LIGHTS_OFF", *WORKED[:1]]), TWO_ODOR)
    assert [(t.row, t.outcome) for t in table.trials] == [(None, "abort_before_stimulus"), ("r1", "correct")]
    assert stream.engagement_of([code(n) for line in ["LIGHTS_ON ODOR_POKE LIGHTS_OFF", *WORKED[:1]]
                                 for n in line.split()], TWO_ODOR).to_json()["pokeAborted"] == 1


def test_a_legacy_no_go_trial_is_flagged_not_classed_and_keeps_its_verdict() -> None:
    no_go = profile(metric("r1", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L"),
                    metric("nogo", "ODOR_5_ON", "WATER_POKE_NONE", "WATER_POKE_L", "WATER_POKE_R"))
    lines = ["LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_UNPOKE WATER_POKE_NONE",
             "LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_UNPOKE WATER_POKE_L",
             "LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_UNPOKE_EARLY"]
    table = decode.table_of(document(lines), no_go)
    assert [(t.outcome, t.correct, t.response) for t in table.trials] == [
        (None, True, None),  # withheld, or so the verdict says: no class is claimed
        (None, False, "WATER_POKE_L"),  # a false alarm, likewise
        ("abort_during_sampling", None, None),  # left the odor port early: that is known
    ]
    assert "no-go-outcomes" in table.gaps
    summary = stream.summarize(document(lines), no_go)
    assert summary.outcomes.no_response == 2, "today's tally, unchanged"
    assert [(m.id, m.hits, m.counted) for m in summary.metrics] == [("r1", 0, 0), ("nogo", 1, 2)]


def test_two_conditions_on_one_onset_each_keep_their_verdict() -> None:
    shared = profile(metric("r1", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L"),
                     metric("l1", "ODOR_1_ON", "WATER_POKE_L", "WATER_POKE_R"))
    table = decode.table_of(document(WORKED[:1]), shared)
    [trial] = table.trials
    assert trial.row == "r1" and [(s.condition, s.correct) for s in trial.scores] == [("r1", True), ("l1", False)]
    assert trial.to_json()["scores"] == [{"condition": "r1", "correct": True},
                                         {"condition": "l1", "correct": False}]


def test_a_profile_without_the_light_or_the_reward_says_so() -> None:
    names = {str(c): n for c, n in SEED.code_map().items()
             if n not in {"LIGHTS_ON", "ODOR_POKE", "FLUID_R", "FLUID_L"}}
    bare = parse_profile({"taskName": "t", "strobes": names, "liveMetrics": [
        metric("r1", "ODOR_1_ON", "WATER_POKE_R", "WATER_POKE_L")]})
    table = decode.table_of(document(WORKED), bare)
    assert {"outcomes", "presentations"} <= set(table.gaps)
    assert all(t.outcome is None for t in table.trials)
    summary = stream.summarize(document(WORKED), bare)
    assert summary.outcomes is None and summary.engagement is None and summary.metrics


def test_a_legacy_run_charts_its_trial_table() -> None:
    codes = [code(n) for line in WORKED for n in line.split()]
    inferred = infer.infer_profile(codes, vocabulary=SEED)
    wire = stream.trial_table_of(document(WORKED), inferred)
    assert wire is not None and wire["kind"] == "legacy" and len(wire["trials"]) == 6
    assert stream.trial_table_of(document(WORKED), None) is None, "nothing decodes it"


def test_an_abort_is_excluded_from_p_correct_and_a_withhold_is_a_hit() -> None:
    assert trial_table.correct_of("abort_during_sampling") is None
    assert trial_table.correct_of("abort_before_stimulus") is None
    assert trial_table.correct_of(None) is None
    assert trial_table.correct_of("correct") is True and trial_table.correct_of("withheld") is True
    assert trial_table.correct_of("wrong_response") is False and trial_table.correct_of("false_alarm") is False


def test_a_run_another_firmware_interpreter_recorded_is_never_decoded() -> None:
    """Its code names only resemble the trial runner's, so it is reported
    unreadable, by its header or by its snapshot, and nothing reads a trial
    off it (`ANALYTICS.md#why-a-run-has-no-numbers`)."""
    assert stream.summarize(document(WORKED), TWO_ODOR).status == "ok"
    assert stream.summarize({**document(WORKED), "interp": 1}, TWO_ODOR).status == "ok"
    by_header = {**document(WORKED), "interp": 8}
    by_snapshot = {**document(WORKED), SNAPSHOT_KEY: {"taskName": "t", "spine": {"interp": 8}}}
    for foreign in (by_header, by_snapshot):
        summary = stream.summarize(foreign, TWO_ODOR)
        assert (summary.status, summary.metrics, summary.overall) == ("unreadable", [], None)
        assert "firmware interpreter" in summary.detail
        assert stream.trial_table_of(foreign, TWO_ODOR) is None
        assert stream.series(foreign, TWO_ODOR) == [] and stream.trials_of(foreign, TWO_ODOR) == []
        assert stream.strategy_trail(foreign, TWO_ODOR) == []
