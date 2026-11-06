"""A stream-grammar-2 run, decoded (`ANALYTICS.md#stream-grammar-2`).

The firmware's host test pins what a grammar-2 board emits for every outcome
(`extras/host_test/test_trial_stream.cpp`); this pins what the app reads out of
each of those sequences, which decoder a run is handed to, and the per-trial
table its files carry (`DATA.md#the-derived-trial-table`).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ephymeris_sidecar.analytics import stream
from ephymeris_sidecar.analytics.stream import grammar2, legacy
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.rig.registry import Vocabulary
from ephymeris_sidecar.sessions import derived
from ephymeris_sidecar.sessions.writer import AnimalWriter
from ephymeris_sidecar.taskdef import generate
from ephymeris_sidecar.taskdef.model import TrialTypeDef
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.profile import TaskProfile, parse_profile
from tests.fixtures import task_definitions as presets

SEED = Vocabulary(registry.default_vocabulary_document())
#: Live and retired alike: the archive's terminators are retired now.
_CODES = {name: c for c, name in SEED.code_map().items()}
code = _CODES.__getitem__

# --- the reference sequences, by name (`TASKS.md#stream-grammar`) -------------

HEADER_R = "TRIAL_START TRIAL_GO_RIGHT TRIAL_TYPE_1"
HEADER_L = "TRIAL_START TRIAL_GO_LEFT TRIAL_TYPE_2"
HEADER_N = "TRIAL_START TRIAL_NO_GO TRIAL_TYPE_3"
SAMPLED_1 = "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF"
SAMPLED_3 = "LIGHTS_ON ODOR_POKE ODOR_3_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF"
SAMPLED_5 = "LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF"

CORRECT_R = f"{HEADER_R} {SAMPLED_1} WATER_POKE_R CORRECT FLUID_R STOP_FLUID_G_R WATER_UNPOKE_R END_TRIAL"
CORRECT_L = f"{HEADER_L} {SAMPLED_3} WATER_POKE_L CORRECT FLUID_L STOP_FLUID_G_L WATER_UNPOKE_L END_TRIAL"
WRONG_WELL = f"{HEADER_R} {SAMPLED_1} WATER_POKE_L WATER_POKE_ERROR_L END_TRIAL"
HOLD_FAILED = f"{HEADER_R} {SAMPLED_1} WATER_POKE_R WATER_UNPOKE_EARLY_R END_TRIAL"
NO_RESPONSE = f"{HEADER_L} {SAMPLED_3} RESP_OMIT END_TRIAL"
WITHHELD = f"{HEADER_N} {SAMPLED_5} WATER_POKE_NONE END_TRIAL"
FALSE_ALARM = f"{HEADER_N} {SAMPLED_5} WATER_POKE_R WATER_POKE_ERROR_R END_TRIAL"
LAZY = f"{HEADER_R} LIGHTS_ON LAZY_RAT LIGHTS_OFF INVALID_TRIAL END_TRIAL"
EARLY_BEFORE_ODOR = f"{HEADER_L} LIGHTS_ON ODOR_POKE ODOR_UNPOKE_EARLY LIGHTS_OFF INVALID_TRIAL END_TRIAL"
EARLY_SAMPLING = f"{HEADER_R} LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_UNPOKE_EARLY_SAMPLING LIGHTS_OFF INVALID_TRIAL END_TRIAL"
REPEATED_ERROR = f"{HEADER_R} {SAMPLED_1} WATER_POKE_L WATER_POKE_ERROR_L INVALID_TRIAL END_TRIAL"

EVERY = [CORRECT_R, CORRECT_L, WRONG_WELL, HOLD_FAILED, NO_RESPONSE, WITHHELD, FALSE_ALARM,
         LAZY, EARLY_BEFORE_ODOR, EARLY_SAMPLING, REPEATED_ERROR, CORRECT_R]

#: One grammar-1 trial, for the decoders' choice and the archive's sake.
GRAMMAR_1 = "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF WATER_POKE_R FLUID_R STOP_FLUID_G_R WATER_UNPOKE_R END_CORRECT_ITI"


def names_of(trials: list[str]) -> list[str]:
    return ["START_SESSION", *(n for t in trials for n in t.split()), "END_SESSION"]


def document(trials: list[str], **extra: Any) -> dict[str, Any]:
    names = names_of(trials)
    return {"rat": "r", "sketch": "GRGL", "stop_reason": stream.CLEAN_STOP_REASON, "trial_seed": 3,
            "ts_data": [[code(n), 100 * i] for i, n in enumerate(names)], **extra}


def generated_profile() -> TaskProfile:
    """What the generator writes for a go-right, go-left and no-go task."""
    registry.set_rig_source(None)
    task = replace(presets.instantiate("grgl_2odor", "probe"), trials=[
        TrialTypeDef("odor_line_1", "ODOR_1_ON", True, "right_well", "fluid_2", label="Go right"),
        TrialTypeDef("odor_line_3", "ODOR_3_ON", True, "left_well", "fluid_1", label="Go left"),
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
    ])
    return generate.build_profile(task)


def grammar1_profile() -> TaskProfile:
    """A profile saved before grammar 2: its metrics score the first well poked."""
    return parse_profile({
        "taskName": "old", "strobes": {str(c): n for c, n in SEED.code_map().items()},
        "liveMetrics": [
            {"id": "r1", "label": "P(R | 1)", "trigger": "ODOR_1_ON", "success": "WATER_POKE_R",
             "alternate": "WATER_POKE_L", "windowSize": 20},
            {"id": "l3", "label": "P(L | 3)", "trigger": "ODOR_3_ON", "success": "WATER_POKE_L",
             "alternate": "WATER_POKE_R", "windowSize": 20},
        ],
    }, vocabulary=SEED)


@pytest.fixture
def profile() -> TaskProfile:
    return generated_profile()


# --- which decoder --------------------------------------------------------------


def test_the_boards_word_picks_the_decoder(profile: TaskProfile) -> None:
    assert grammar2.grammar_of(document(EVERY, stream=2), profile) == 2
    assert grammar2.grammar_of(document([GRAMMAR_1], stream=1), profile) == 1
    # The token outranks the codes: a board that said 1 is read as 1 whatever it sent.
    assert grammar2.grammar_of(document(EVERY, stream=1), profile) == 1


def test_without_a_token_the_codes_decide(profile: TaskProfile) -> None:
    """A stream closed by grammar 1's terminators is grammar 1; one with the
    header is grammar 2; one with neither is the archive's grammar 1."""
    assert grammar2.grammar_of(document([GRAMMAR_1]), profile) == 1
    assert grammar2.grammar_of(document(EVERY), profile) == 2
    assert grammar2.grammar_of(document([CORRECT_R, GRAMMAR_1]), profile) == 1
    assert grammar2.grammar_of(document([]), profile) == 1
    assert grammar2.grammar_of(document(EVERY), None) == 1
    # The header alone is not the grammar: a phase-spine stream opens its
    # trials with TRIAL_START too, and never closes one with END_TRIAL.
    assert grammar2.grammar_of(document(["TRIAL_START LIGHTS_ON ODOR_POKE ODOR_1_ON"] * 3), profile) == 1


# --- every trial, read ------------------------------------------------------------


def rows(trials: list[str], profile: TaskProfile) -> list[grammar2.TrialRow]:
    return list(grammar2.rows_of(document(trials, stream=2), profile))


def test_every_reference_sequence_is_one_row_with_one_outcome(profile: TaskProfile) -> None:
    out = rows(EVERY, profile)
    assert len(out) == len(EVERY)
    assert [r.index for r in out] == list(range(len(EVERY)))
    assert all(r.end_ms is not None for r in out), "every trial ends with END_TRIAL"
    assert all(r.outcome is not None for r in out), "exactly one outcome code per trial"


@pytest.mark.parametrize(
    ("trial", "side", "slot", "odor", "sampled", "outcome", "klass", "correct", "response", "repeat"),
    [
        (CORRECT_R, "right", 1, 1, True, "CORRECT", "correct", True, "right", False),
        (CORRECT_L, "left", 2, 3, True, "CORRECT", "correct", True, "left", False),
        (WRONG_WELL, "right", 1, 1, True, "WATER_POKE_ERROR_L", "wrong_response", False, "left", False),
        (HOLD_FAILED, "right", 1, 1, True, "WATER_UNPOKE_EARLY_R", "hold_broken", False, "right", False),
        (NO_RESPONSE, "left", 2, 3, True, "RESP_OMIT", "omission", False, None, False),
        (WITHHELD, "no_go", 3, 5, True, "WATER_POKE_NONE", "withheld", True, None, False),
        (FALSE_ALARM, "no_go", 3, 5, True, "WATER_POKE_ERROR_R", "false_alarm", False, "right", False),
        (LAZY, "right", 1, None, False, "LAZY_RAT", "abort_before_stimulus", None, None, True),
        (EARLY_BEFORE_ODOR, "left", 2, None, False, "ODOR_UNPOKE_EARLY", "abort_before_stimulus", None, None, True),
        (EARLY_SAMPLING, "right", 1, 1, True, "ODOR_UNPOKE_EARLY_SAMPLING", "abort_during_sampling", None, None, True),
        (REPEATED_ERROR, "right", 1, 1, True, "WATER_POKE_ERROR_L", "wrong_response", False, "left", True),
    ],
    ids=lambda v: v if isinstance(v, str) and " " not in v else None,
)
def test_what_each_sequence_says(profile, trial, side, slot, odor, sampled, outcome, klass, correct, response, repeat):  # noqa: ANN001
    (row,) = rows([trial], profile)
    assert (row.side, row.type_slot, row.odor_line, row.sampled) == (side, slot, odor, sampled)
    assert (row.outcome, row.outcome_class, row.correct) == (outcome, klass, correct)
    assert (row.response, row.repeat) == (response, repeat)


def test_the_timestamps_are_the_strobes_that_say_so(profile: TaskProfile) -> None:
    (row,) = rows([CORRECT_R], profile)
    names = names_of([CORRECT_R])
    at = {n: 100 * i for i, n in enumerate(names)}
    assert row.start_ms == at["TRIAL_START"]
    assert row.light_on_ms == at["LIGHTS_ON"] and row.odor_poke_ms == at["ODOR_POKE"]
    assert row.odor_on_ms == at["ODOR_1_ON"] and row.odor_off_ms == at["ODOR_OFF"]
    assert row.odor_unpoke_ms == at["ODOR_UNPOKE"]
    assert row.response_ms == at["WATER_POKE_R"] and row.outcome_ms == at["CORRECT"]
    assert row.end_ms == at["END_TRIAL"]
    # The reaction time runs from the odor port's release to the first well poke.
    assert row.reaction_ms == at["WATER_POKE_R"] - at["ODOR_UNPOKE"]
    (lazy,) = rows([LAZY], profile)
    assert lazy.reaction_ms is None and lazy.odor_poke_ms is None and lazy.response_ms is None


def test_the_trial_table_reads_the_same_rows(profile: TaskProfile) -> None:
    """The wire's table (`ReplayTrial`), with the condition each trial opened,
    its outcome class, the verdict read from it, and the reaction time."""
    table = grammar2.table_of(document(EVERY, stream=2), profile)
    assert table.to_json()["kind"] == "grammar2" and table.gaps == ("phase-entries", "input-counts")
    by_index = {t.index: t for t in table.trials}
    first = by_index[0]
    assert (first.row, first.row_name) == ("p_correct_1", "P(correct | Go right)"), "the condition, as a legacy row names it"
    assert (first.outcome, first.correct, first.rewarded) == ("correct", True, True)
    assert first.reward_line == "FLUID_R" and first.reward_ms == 100
    assert first.response == "WATER_POKE_R" and first.latency_ms == 200, "ODOR_UNPOKE to the poke: two strobes apart"
    hold = by_index[EVERY.index(HOLD_FAILED)]
    assert (hold.outcome, hold.correct) == ("hold_broken", False)
    lazy = by_index[EVERY.index(LAZY)]
    assert (lazy.row, lazy.outcome, lazy.correct, lazy.presented) == (None, "abort_before_stimulus", None, True)
    alarm = by_index[EVERY.index(FALSE_ALARM)]
    assert (alarm.row, alarm.outcome, alarm.correct) == ("p_withhold_3", "false_alarm", False)
    # The trial after a repeated error is a correction trial; after an abort it is not.
    assert by_index[EVERY.index(REPEATED_ERROR) + 1].correction is True
    assert by_index[EVERY.index(LAZY) + 1].correction is False
    assert all(t.complete for t in table.trials)


def test_a_cut_off_last_trial_is_incomplete(profile: TaskProfile) -> None:
    cut = names_of([CORRECT_R, CORRECT_L])[:-6]  # the board dropped mid-trial
    doc = {"rat": "r", "ts_data": [[code(n), 100 * i] for i, n in enumerate(cut)], "stream": 2}
    table = grammar2.table_of(doc, profile)
    assert [t.complete for t in table.trials] == [True, False]


# --- the figures ------------------------------------------------------------------


def test_the_summary_scores_the_outcome_codes(profile: TaskProfile) -> None:
    summary = stream.summarize(document(EVERY, stream=2), profile)
    assert summary.status == "ok"
    by_id = {m.id: m for m in summary.metrics}
    # Odor 1: correct, wrong well, hold failed, early sampling (excluded),
    # the repeated error, and correct again: 2 of 5 counted, 1 excluded.
    right = by_id["p_correct_1"]
    assert (right.hits, right.counted, right.excluded, right.answer_side) == (2, 5, 1, "right")
    left = by_id["p_correct_2"]
    assert (left.hits, left.counted, left.excluded, left.answer_side) == (1, 2, 0, "left")
    withhold = by_id["p_withhold_3"]
    assert (withhold.hits, withhold.counted, withhold.answer_side) == (1, 2, "withhold")
    assert summary.outcomes is not None
    assert (summary.outcomes.rewarded, summary.outcomes.hold_failed, summary.outcomes.wrong_well) == (3, 1, 2)
    assert (summary.outcomes.no_response, summary.outcomes.withheld, summary.outcomes.false_alarm) == (1, 1, 1)
    assert summary.outcomes.aborted == 1 and summary.outcomes.administered == 9
    assert summary.engagement is not None
    assert (summary.engagement.presented, summary.engagement.poked, summary.engagement.odor_delivered) == (12, 11, 10)
    sides = {c.metric_id: c.answer_side for c in summary.conditions}
    assert sides == {"p_correct_1": "right", "p_correct_2": "left", "p_withhold_3": None}


def test_live_and_offline_agree(profile: TaskProfile) -> None:
    doc = document(EVERY, stream=2)
    live = {mid: (value, n) for mid, value, n in legacy.live_equivalent(profile, stream.codes_of(doc))}
    for metric in stream.summarize(doc, profile).metrics:
        assert live[metric.id] == (metric.p_window, min(metric.counted, metric.window_size))


def test_a_grammar_1_profile_still_scores_a_grammar_2_stream() -> None:
    """A task saved before grammar 2 scores the first well poked, which the
    stream still carries: reward-unconditional, as it always was, so a hold
    failure is a hit there and a miss on the outcome codes."""
    old = stream.summarize(document(EVERY, stream=2), grammar1_profile())
    assert old.status == "ok"
    right = next(m for m in old.metrics if m.id == "r1")
    assert (right.hits, right.counted) == (3, 5)


def test_the_curves_and_the_walk_read_a_grammar_2_run(profile: TaskProfile) -> None:
    doc = document(EVERY * 3, stream=2)
    series = {s.id: s for s in stream.series(doc, profile)}
    assert len(series["p_correct_1"].values) == 15
    assert stream.strategy_trail(doc, profile, min_window=2), "the headers give each condition its side"
    tape = stream.trials_of(doc, profile)
    assert {t.outcome for t in tape} >= {"rewarded", "withheld", "false_alarm", "aborted"}
    assert all(t.to_json()["outcome"] in ("rewarded", "hold-failed", "wrong-well", "no-response", "aborted",
                                          "withheld", "false-alarm") for t in tape)


def test_a_grammar_2_profile_scores_the_archive_by_the_first_well_poked(profile: TaskProfile) -> None:
    """A pre-app run resolves to the bundled GRGL profile through `legacyNames`
    and carries no snapshot: scored as declared it would count nothing, so the
    scorer re-expresses each condition as the archive's own metric, with the
    side read from the stream, and the numbers are the ones the archive always
    had (`ANALYTICS.md#stream-grammar-2`)."""
    from ephymeris_sidecar.analytics import scoring

    archive = document([GRAMMAR_1] * 4 + [
        "LIGHTS_ON ODOR_POKE ODOR_1_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF WATER_POKE_L WATER_POKE_ERROR_L END_INCORRECT_ITI",
        "LIGHTS_ON ODOR_POKE ODOR_3_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF WATER_POKE_L FLUID_L STOP_FLUID_G_L WATER_UNPOKE_L END_CORRECT_ITI",
        "LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF WATER_POKE_NONE END_CORRECT_ITI",
        "LIGHTS_ON ODOR_POKE ODOR_5_ON ODOR_OFF ODOR_UNPOKE LIGHTS_OFF WATER_POKE_R END_INCORRECT_ITI",
    ])
    assert grammar2.scores_grammar_2(profile) and not grammar2.scores_grammar_2(grammar1_profile())
    as_declared = {m.id: m for m in stream.summarize(archive, profile).metrics}
    declared_1 = as_declared["p_correct_1"]
    assert (declared_1.hits, declared_1.counted, declared_1.excluded) == (0, 1, 4), \
        "declared, CORRECT never comes: only the wrong well counts, as a miss"

    resolved = scoring._Resolved(profile, "sketch-current", "digest")
    settled, source, _ = scoring._settle(resolved, archive, scoring._Pass(SEED, remember=None))
    assert source == "sketch-current" and settled is not None
    by_id = {m.id: m for m in stream.summarize(archive, settled).metrics}
    assert (by_id["p_correct_1"].hits, by_id["p_correct_1"].counted, by_id["p_correct_1"].answer_side) == (4, 5, "right")
    assert (by_id["p_correct_2"].hits, by_id["p_correct_2"].counted, by_id["p_correct_2"].answer_side) == (1, 1, "left")
    assert (by_id["p_withhold_3"].hits, by_id["p_withhold_3"].counted) == (1, 2)
    # The same numbers the archive's own grammar-1 metrics give.
    old = {m.id: m for m in stream.summarize(archive, grammar1_profile()).metrics}
    assert (old["r1"].hits, old["r1"].counted) == (4, 5) and (old["l3"].hits, old["l3"].counted) == (1, 1)
    # A grammar-2 run is left as declared.
    settled2, _, _ = scoring._settle(resolved, document(EVERY, stream=2), scoring._Pass(SEED, remember=None))
    assert settled2 is not None and grammar2.scores_grammar_2(settled2)


def test_the_archive_still_decodes_as_grammar_1(profile: TaskProfile) -> None:
    doc = document([GRAMMAR_1] * 3)
    assert grammar2.grammar_of(doc, profile) == 1
    summary = stream.summarize(doc, grammar1_profile())
    assert summary.status == "ok" and next(m for m in summary.metrics if m.id == "r1").hits == 3
    assert stream.trial_table_of(doc, grammar1_profile())["kind"] == "legacy"


# --- the files ----------------------------------------------------------------------


def test_the_derived_block_is_the_per_trial_table(profile: TaskProfile) -> None:
    doc = document(EVERY, stream=2, interp=1, **{task_profile.SNAPSHOT_KEY: profile.to_json()})
    block = derived.derive(doc)
    assert block is not None and block["status"] == "ok" and block["grammar"] == 2
    assert block["interp"] == 1 and block["phases"] == []
    assert len(block["trials"]) == len(EVERY)
    first = block["trials"][0]
    assert first["type_slot"] == 1 and first["side"] == "right" and first["outcome"] == "CORRECT"
    assert set(first) == {f.name for f in __import__("dataclasses").fields(grammar2.TrialRow)}
    assert derived.derive(document([GRAMMAR_1])) is None, "a grammar-1 run has no block"


def test_a_run_without_a_snapshot_is_read_with_the_vocabulary() -> None:
    block = derived.derive(document(EVERY, stream=2))
    assert block is not None and block["grammar"] == 2 and block["trials"][0]["outcome"] == "CORRECT"


def test_the_writer_puts_the_table_in_both_files(tmp_path: Path, profile: TaskProfile) -> None:
    scipy = pytest.importorskip("scipy")
    session = tmp_path / "P" / "P_1_2026-11-06"
    tsv, json_path, mat = (session / "behavior.tsv" / "r.tsv", session / "behavior.json" / "r.json",
                           session / "behavior.mat" / "r.mat")
    writer = AnimalWriter(tsv, json_path, mat, core_metadata={"rat": "r", "sketch": "GRGL", "stream": 2, "interp": 1},
                          config_metadata={}, profile_snapshot=profile.to_json())
    writer.open_files()
    for i, name in enumerate(names_of(EVERY)):
        writer.record(code(name), 100 * i)
    writer.finalize(stream.CLEAN_STOP_REASON)

    written = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(written)[-1] == task_profile.DERIVED_KEY
    assert written[task_profile.DERIVED_KEY]["grammar"] == 2
    assert written[task_profile.DERIVED_KEY]["trials"][EVERY.index(LAZY)]["outcome"] == "LAZY_RAT"

    loaded = scipy.io.loadmat(str(mat))[task_profile.DERIVED_KEY][0, 0]
    assert float(loaded["grammar"].ravel()[0]) == 2
    trials = loaded["trials"]
    assert trials.shape == (len(EVERY), 1)
    assert str(trials["outcome"][0, 0][0]) == "CORRECT"
    assert float(trials["type_slot"][1, 0].ravel()[0]) == 2
    import math

    assert math.isnan(float(trials["reaction_ms"][EVERY.index(LAZY), 0].ravel()[0]))
    assert bool(trials["repeat"][EVERY.index(LAZY), 0].ravel()[0]) is True


def test_rederive_rewrites_a_grammar_2_run_and_leaves_a_grammar_1_run_alone(tmp_path: Path, profile: TaskProfile) -> None:
    pytest.importorskip("scipy")
    two = tmp_path / "two.json"
    two.write_text(json.dumps(document(EVERY, stream=2, interp=1, **{task_profile.SNAPSHOT_KEY: profile.to_json()})))
    one = tmp_path / "one.json"
    one.write_text(json.dumps(document([GRAMMAR_1], **{task_profile.SNAPSHOT_KEY: grammar1_profile().to_json()})))
    entry = derived.rederive_file(two)
    assert entry is not None and entry["status"] == "rewritten"
    assert json.loads(two.read_text())[task_profile.DERIVED_KEY]["grammar"] == 2
    assert derived.rederive_file(one) is None
