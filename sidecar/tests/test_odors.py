"""The odors table — `DATA.md#the-odors-table`.

One row per odor line a trial type presents: which odor, which well, how
much. Built from the run's own profile snapshot (its `trialTypes`,
`TASKS.md#trial-types-in-the-profile`) and its merged parameters, so a
recovered or copied file has it too.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import scipy.io

from ephymeris_sidecar.analytics import reader
from ephymeris_sidecar.analytics.stream import odors
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.sessions import matwriter, recovery
from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.sessions.writer import AnimalWriter
from ephymeris_sidecar.taskdef import generate, store
from ephymeris_sidecar.taskdef.model import TaskDefinition, TrialTypeDef
from ephymeris_sidecar.tasks.profile import TaskProfile, parse_profile, profile_hash
from tests.fixtures import spine as spine_fixture
from tests.fixtures import task_definitions as presets
from tests.test_grammar2 import grammar1_profile
from tests.test_taskdef import library  # noqa: F401 - a fixture


@pytest.fixture(autouse=True)
def _shipped_wiring():
    registry.set_rig_source(None)
    yield
    registry.set_rig_source(None)


def code(name: str) -> int:
    """A strobe's code, from the vocabulary by name."""
    return registry.vocabulary().get(name).code


#: Eight odors: (line, the operator's name, well, reward ms, weight).
EIGHT = [
    (1, "GR-Sandalwood", "right", 100, 1), (2, "GL-Lemon", "left", 100, 1),
    (3, "GR-Clove", "right", 250, 2), (4, "GL-Mint", "left", 50, 1),
    (5, "GR-Anise", "right", 100, 3), (6, "GL-Pine", "left", 400, 1),
    (7, "GR-Cumin", "right", 100, 1), (8, "GL-Rose", "left", 100, 4),
]


def eight_odor_task(**edits) -> TaskDefinition:  # noqa: ANN003
    trials = [
        TrialTypeDef(f"odor_line_{line}", f"ODOR_{line}_ON", True, f"{side}_well",
                     "fluid_2" if side == "right" else "fluid_1", weight=weight, label=name,
                     reward_time=reward)
        for line, name, side, reward, weight in EIGHT
    ]
    return replace(presets.instantiate("grgl_2odor", "probe"), **{"name": "GRGL 8-Odor", "trials": trials, **edits})


def defaults(profile: TaskProfile) -> dict:
    """The parameters a run of `profile` records when nothing is overridden."""
    return {f.metadata_key: f.default for f in profile.config}


def expected_rows() -> list[dict]:
    return [{"line": line, "name": name, "onset_code": code(f"ODOR_{line}_ON"), "side": side,
             "reward_ms": reward, "pool_weight": weight}
            for line, name, side, reward, weight in EIGHT]


# --- trial types in the profile -------------------------------------------------- #

def test_the_generator_writes_each_trial_type_into_the_profile() -> None:
    task = replace(eight_odor_task(), trials=[
        *eight_odor_task().trials[:2],
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
    ])
    assert generate.profile_json(task)["trialTypes"] == [
        {"slot": 1, "name": "GR-Sandalwood", "onset": "ODOR_1_ON", "side": "right",
         "weightKey": "pool_weight_1", "rewardKey": "reward_time_1"},
        {"slot": 2, "name": "GL-Lemon", "onset": "ODOR_2_ON", "side": "left",
         "weightKey": "pool_weight_2", "rewardKey": "reward_time_2"},
        # A no-go row answers at no well and pays nothing: no reward key.
        {"slot": 3, "name": "Withhold", "onset": "ODOR_5_ON", "side": "no_go",
         "weightKey": "pool_weight_3"},
    ]


def test_a_dropped_row_has_no_trial_type_and_the_rest_keep_their_parameter_keys() -> None:
    """`slot` is the row's place in the table the board runs (its
    `TRIAL_TYPE_<n>` header); the keys are the definition's, which do not move."""
    trials = eight_odor_task().trials
    task = eight_odor_task(trials=[trials[0], replace(trials[1], odor_channel="odor_line_99"), trials[2]])
    assert [(t["slot"], t["name"], t["rewardKey"]) for t in generate.profile_json(task)["trialTypes"]] == [
        (1, "GR-Sandalwood", "reward_time_1"), (2, "GR-Clove", "reward_time_3"),
    ]


def test_trial_types_never_move_the_profile_hash() -> None:
    """Left out of `profile_hash` as `exposed` is, so writing it splits no
    task's run history (`TASKS.md#profile-and-params-hashes`)."""
    declared = generate.profile_json(eight_odor_task())
    without = {key: value for key, value in declared.items() if key != "trialTypes"}
    renamed = {**declared, "trialTypes": [{**t, "name": "other"} for t in declared["trialTypes"]]}
    vocabulary = registry.vocabulary()
    hashes = {profile_hash(parse_profile(raw, vocabulary=vocabulary)) for raw in (declared, without, renamed)}
    assert len(hashes) == 1


def test_the_snapshot_round_trips_with_its_trial_types_and_without() -> None:
    """`DATA.md#the-embedded-task-profile`: byte for byte through `parse_profile`."""
    profile = generate.build_profile(eight_odor_task())
    snapshot = profile.to_json()
    assert snapshot["trialTypes"] == generate.profile_json(eight_odor_task())["trialTypes"]
    again = parse_profile(json.loads(json.dumps(snapshot))).to_json()
    assert json.dumps(again, sort_keys=True) == json.dumps(snapshot, sort_keys=True)

    older = {key: value for key, value in snapshot.items() if key != "trialTypes"}
    parsed = parse_profile(older)
    assert parsed.trial_types is None and "trialTypes" not in parsed.to_json()


def test_the_rebuild_gives_a_stored_task_its_trial_types_and_leaves_its_firmware_alone(
    tmp_path: Path, library: Path  # noqa: F811
) -> None:
    """A task saved by a build from before the key gets it at the next rebuild,
    which every startup runs (`TASKS.md#task-definitions`). Only `task.json`
    changes: nothing the board is compiled from."""
    tasks = store.TaskStore(tmp_path, library_root=library)
    definition = eight_odor_task(id="probe")
    assert tasks.save(definition) == []
    folder = tasks.sketch_dir(definition)
    profile_path = folder / "task.json"
    older = json.loads(profile_path.read_text(encoding="utf-8"))
    declared = older.pop("trialTypes")
    profile_path.write_text(json.dumps(older), encoding="utf-8")
    firmware = {p.name: p.read_bytes() for p in folder.iterdir() if p.name != "task.json"}

    assert tasks.regenerate_all() == 1

    assert json.loads(profile_path.read_text(encoding="utf-8"))["trialTypes"] == declared
    assert len(declared) == 8
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.name != "task.json"} == firmware


@pytest.mark.parametrize("wrong", ["rows", [1], [{"slot": 1}], [{"onset": 3, "side": "left"}]])
def test_trial_types_of_the_wrong_shape_are_refused(wrong) -> None:  # noqa: ANN001
    from ephymeris_sidecar.tasks.profile import TaskProfileError

    with pytest.raises(TaskProfileError, match="trialTypes"):
        parse_profile({"taskName": "T", "trialTypes": wrong})


# --- the table ------------------------------------------------------------------- #

def test_an_8_odor_run_has_8_rows_that_agree_with_its_profile_and_parameters() -> None:
    profile = generate.build_profile(eight_odor_task())
    assert odors.odor_table(profile, defaults(profile)) == expected_rows()


def test_a_runs_own_parameters_win_over_the_profiles_defaults() -> None:
    profile = generate.build_profile(eight_odor_task())
    params = {**defaults(profile), "reward_time_3": 500, "pool_weight_8": 9}
    table = odors.odor_table(profile, params)
    assert (table[2]["reward_ms"], table[7]["pool_weight"]) == (500, 9)
    assert table[0] == expected_rows()[0]


def test_a_no_go_odor_pays_nothing_and_a_missing_value_is_null() -> None:
    task = eight_odor_task(trials=[
        eight_odor_task().trials[0],
        TrialTypeDef("odor_line_5", "ODOR_5_ON", is_go=False, label="Withhold"),
    ])
    profile = generate.build_profile(task)
    go, no_go = odors.odor_table(profile, {})
    assert no_go == {"line": 5, "name": "Withhold", "onset_code": code("ODOR_5_ON"), "side": "no_go",
                     "reward_ms": 0, "pool_weight": None}
    assert (go["reward_ms"], go["pool_weight"]) == (None, None), "the run recorded neither"


def test_a_task_with_no_odor_conditions_has_an_empty_table() -> None:
    assert odors.odor_table(None, {}) == []
    assert odors.odor_table(parse_profile({"taskName": "T"}), {"x": 1}) == []
    spine_fixture.install()
    try:
        from tests.test_spine_analytics import recorded_document
        from ephymeris_sidecar.tasks.profile import embedded_profile

        tracer = recorded_document()
        assert odors.odor_table(embedded_profile(tracer), tracer) == []
    finally:
        spine_fixture.uninstall()


def test_a_snapshot_without_trial_types_gives_what_its_success_codes_prove() -> None:
    """A profile from before grammar 2 scores the first well poked, so its
    success code names the side. Nothing is read from the stream."""
    assert odors.odor_table(grammar1_profile(), {"reward_time_1": 80}) == [
        {"line": 1, "name": "1", "onset_code": code("ODOR_1_ON"), "side": "right",
         "reward_ms": None, "pool_weight": None},
        {"line": 3, "name": "3", "onset_code": code("ODOR_3_ON"), "side": "left",
         "reward_ms": None, "pool_weight": None},
    ]


def test_a_snapshot_whose_metrics_prove_no_side_gives_an_empty_table() -> None:
    profile = generate.build_profile(eight_odor_task())
    older = replace(profile, trial_types=None)  # scores CORRECT: it names no well
    assert odors.odor_table(older, defaults(profile)) == []


# --- in the files ---------------------------------------------------------------- #

def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    session = tmp_path / "cohort" / "8O" / "8O_1_2026-11-18"
    return (session / "behavior.tsv" / "remy1.tsv", session / "behavior.json" / "remy1.json",
            session / "behavior.mat" / "remy1.mat")


def written(tmp_path: Path, profile: TaskProfile | None, params: dict) -> tuple[Path, Path, Path]:
    tsv, json_path, mat = files(tmp_path)
    writer = AnimalWriter(tsv, json_path, mat, {"rat": "remy1", "sketch": "GRGL 8-Odor", "stream": 1},
                          params, profile_snapshot=profile.to_json() if profile else None)
    writer.open_files()
    writer.record(code("START_SESSION"), 0)
    writer.finalize("BF_END_SESSION received")
    return tsv, json_path, mat


def test_a_written_run_lists_its_odors_after_its_parameters(tmp_path: Path) -> None:
    profile = generate.build_profile(eight_odor_task())
    _, json_path, _ = written(tmp_path, profile, {**defaults(profile), "reward_time_3": 500})
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(document)[:4] == ["schema_version", "run", "task", "params"] and list(document)[4] == "odors"
    assert document["odors"] == [{**row, "reward_ms": 500} if row["line"] == 3 else row
                                 for row in expected_rows()]


def test_a_run_with_no_odor_conditions_writes_an_empty_table_not_a_missing_key(tmp_path: Path) -> None:
    _, json_path, mat = written(tmp_path, None, {})
    assert json.loads(json_path.read_text(encoding="utf-8"))["odors"] == []
    empty = scipy.io.loadmat(str(mat))["odors"]
    assert empty.shape == (0, 1)
    assert set(empty.dtype.names) == {"line", "name", "onset_code", "side", "reward_ms", "pool_weight"}


def test_recover_rebuilds_the_same_table_from_the_tsv_alone(tmp_path: Path) -> None:
    profile = generate.build_profile(eight_odor_task())
    tsv, json_path, _ = written(tmp_path, profile, defaults(profile))
    finalized = json.loads(json_path.read_text(encoding="utf-8"))
    json_path.unlink()
    assert recovery.recover_file(tsv)["status"] == "recovered"
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered["odors"] == finalized["odors"] == expected_rows()
    assert list(recovered) == list(finalized)


def test_the_mat_holds_the_odors_as_a_struct_array(tmp_path: Path) -> None:
    profile = generate.build_profile(eight_odor_task())
    _, _, mat = written(tmp_path, profile, defaults(profile))
    table = scipy.io.loadmat(str(mat))["odors"]
    assert table.shape == (8, 1), "N×1, so struct2table(S.odors) is one row per odor"
    third = table[2, 0]
    assert float(third["line"][0, 0]) == 3.0 and third["line"].dtype == float
    assert str(third["name"][0]) == "GR-Clove" and str(third["side"][0]) == "right"
    assert float(third["onset_code"][0, 0]) == float(code("ODOR_3_ON"))
    assert float(third["reward_ms"][0, 0]) == 250.0 and float(third["pool_weight"][0, 0]) == 2.0


def test_a_null_in_the_mat_is_nan_or_empty_text(tmp_path: Path) -> None:
    rows = [{"line": None, "name": None, "onset_code": 7, "side": None, "reward_ms": None,
             "pool_weight": None}]
    path = tmp_path / "nulls.mat"
    matwriter.savemat(str(path), rd.with_odors(rd.build({"rat": "remy1"}, {}), rows))
    row = scipy.io.loadmat(str(path))["odors"][0, 0]
    for name in ("line", "reward_ms", "pool_weight"):
        assert str(float(row[name][0, 0])) == "nan", name
    for name in ("name", "side"):
        assert row[name].size == 0 and row[name].dtype.kind == "U", name


def test_a_flat_file_read_in_gets_the_table_its_profile_allows(tmp_path: Path) -> None:
    profile = generate.build_profile(eight_odor_task())
    flat = {"rat": "remy1", "sketch": "GRGL 8-Odor", **defaults(profile),
            "task_profile": profile.to_json(), "ts_data": []}
    old = {"rat": "remy1", "sketch": "old", "task_profile": grammar1_profile().to_json(), "ts_data": []}
    bare = {"rat": "remy1", "sketch": "none", "ts_data": []}
    tables = []
    for name, document in (("new.json", flat), ("old.json", old), ("bare.json", bare)):
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        tables.append(rd.odors_of(reader.read_run(path).document))
    assert tables[0] == expected_rows()
    assert [(row["line"], row["side"]) for row in tables[1]] == [(1, "right"), (3, "left")]
    assert tables[2] == []


def test_a_version_2_file_keeps_the_table_it_was_written_with(tmp_path: Path) -> None:
    """The reader fills in a table only where the file has none."""
    profile = generate.build_profile(eight_odor_task())
    _, json_path, _ = written(tmp_path, profile, defaults(profile))
    document = json.loads(json_path.read_text(encoding="utf-8"))
    document["odors"] = document["odors"][:1]
    json_path.write_text(json.dumps(document), encoding="utf-8")
    assert rd.odors_of(reader.read_run(json_path).document) == expected_rows()[:1]
