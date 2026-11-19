"""Readers take both shapes of a run's document — `DATA.md#the-json-document`.

A version-2 document is nested (ADR 0009); a version-1 one is flat. A file of
either shape scores, re-derives, adopts and moves the same, and one from a
newer build is refused whole.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import reader, stream
from ephymeris_sidecar.sessions import derived, matwriter
from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.tasks import profile as task_profile
from tests.fixtures import spine as fixture
from tests.test_analytics_adoption import LegacyRig
from tests.test_analytics_adoption import db as adoption_db  # noqa: F401 - a fixture
from tests.test_cohort_move import Lab
from tests.test_derived_trials import load_mat, read_json, run_through_writer
from tests.test_run_document import DOCUMENT
from tests.test_spine_analytics import recorded_document, rig, write_document  # noqa: F401 - rig is a fixture


@pytest.fixture(autouse=True)
def _issued_rig():
    fixture.install()
    yield
    fixture.uninstall()


# Where each flat field sits in version 2, written out by hand from the ADR.
RUN = {"rat": "animal", "serial_port": "serial_port", "session_id": "session_id",
       "stop_reason": "stop_reason", "n_events": "n_events"}
TASK = ("sketch", "stream", "interp", "free_ram", "sync", "trial_seed", "host_seed",
        "channel_set_hash", "channel_set_hash_version")
RECORDING = {"intan_recording": "name", "intan_path": "path", "intan_digital_in": "digital_in",
             "intan_port": "port", "intan_channels": "channels", "intan_sample_rate": "sample_rate"}
WHOLE = ("ts_data", "task_profile", "derived")


def version_2(flat: dict) -> dict:
    """The version-2 twin of a flat document, block by block as the ADR lays
    them out; a document the writer already wrote as version 2, as it is."""
    if flat.get("schema_version") == 2:
        return flat
    out: dict = {
        "schema_version": 2,
        "run": {new: flat[old] for old, new in RUN.items() if old in flat},
        "task": {key: flat[key] for key in TASK if key in flat},
        "params": {key: value for key, value in flat.items()
                   if key not in {*RUN, *TASK, *RECORDING, *WHOLE}},
    }
    recording = {new: flat[old] for old, new in RECORDING.items() if old in flat}
    if recording:
        out["recording"] = recording
    if "derived" in flat:
        out["trials"] = {("rows" if key == "trials" else key): value
                         for key, value in flat["derived"].items()}
    for key in ("ts_data", "task_profile"):
        if key in flat:
            out[key] = flat[key]
    return out


V2 = {
    "schema_version": 2,
    "run": {"animal": "remy1", "serial_port": "COM5", "session_id": "8O-Bdisc_09",
            "stop_reason": "BF_END_SESSION received", "n_events": 2},
    "task": {"sketch": "GRGL 8-Odor EZ", "interp": 1, "free_ram": 5120, "stream": 2, "sync": "tick",
             "channel_set_hash": "abc", "channel_set_hash_version": 2, "trial_seed": 7, "host_seed": 8},
    "params": {"num_trials": 1000, "error_delay": 20000},
    "recording": {"name": "rec_1", "path": "D:/rhx", "digital_in": 1, "port": "A",
                  "channels": "A-016:A-031", "sample_rate": 30000},
    "trials": {"status": "ok", "rows": []},
    "ts_data": [[221, 0], [222, 1001]],
    "task_profile": {"taskName": "GRGL 8-Odor EZ"},
}


def test_a_flat_document_lifts_to_the_version_2_shape() -> None:
    lifted = rd.lifted(DOCUMENT)
    assert lifted == V2
    assert list(lifted) == list(V2), "blocks in the ADR's order"
    assert rd.lifted(V2) is V2, "a version-2 document is already lifted"
    assert "rat" in DOCUMENT, "the original is left as it was"


FIELD_ACCESSORS = [
    rd.animal_of, rd.serial_port_of, rd.session_id_of, rd.sketch_of, rd.interp_of, rd.free_ram_of,
    rd.stream_of, rd.sync_of, rd.channel_set_hash_of, rd.channel_set_hash_version_of,
    rd.recording_name_of, rd.recording_path_of, rd.recording_digital_in_of, rd.recording_port_of,
    rd.recording_channels_of, rd.recording_sample_rate_of, rd.trial_seed_of, rd.host_seed_of,
    rd.snapshot_of, rd.stop_reason_of, rd.n_events_of, rd.strobes_of, rd.trial_table_of,
]


@pytest.mark.parametrize("accessor", FIELD_ACCESSORS, ids=lambda f: f.__name__)
def test_an_accessor_reads_the_same_from_either_shape(accessor) -> None:
    assert accessor(V2) == accessor(DOCUMENT) and accessor(DOCUMENT) is not None
    assert accessor({"schema_version": 2}) is None
    assert accessor({"schema_version": 2, "run": "torn", "task": None, "recording": []}) is None


def test_a_version_2_parameter_is_read_from_its_params_block() -> None:
    assert rd.has_param(V2, "num_trials") and rd.param_of(V2, "num_trials") == 1000
    assert not rd.has_param(V2, "run") and not rd.has_param(V2, "animal")
    assert not rd.has_param({"schema_version": 2}, "num_trials")
    with pytest.raises(KeyError):
        rd.param_of(V2, "reward_time_5")


def test_a_version_2_trial_table_is_stored_as_trials_with_its_rows_under_rows() -> None:
    bare = rd.without_trial_table(V2)
    assert "trials" not in bare and "trials" in V2
    block = {"status": "ok", "replay_version": 4, "trials": [{"index": 0}]}
    again = rd.with_trial_table(bare, block)
    assert again["trials"] == {"status": "ok", "replay_version": 4, "rows": [{"index": 0}]}
    assert list(again) == list(V2), "before ts_data, as the ADR orders the blocks"
    assert rd.trial_table_of(again) == block, "read back in the shape it was derived in"
    assert "derived" not in again


@pytest.mark.parametrize(("version", "says"), [
    (3, "newer"), (99, "newer"), (1, "not a version"), ("2", "not a version"), (True, "not a version"),
])
def test_only_this_builds_versions_are_readable(version, says) -> None:
    assert says in rd.unreadable_reason({"schema_version": version})
    assert str(version) in rd.unreadable_reason({"schema_version": version})


def test_a_flat_document_and_a_version_2_one_are_readable() -> None:
    assert rd.unreadable_reason(DOCUMENT) is None
    assert rd.unreadable_reason(V2) is None


# --- one run, written both ways, reads the same ------------------------------- #

def test_the_twins_give_the_same_summary_trial_table_and_hashes() -> None:
    flat = recorded_document()
    nested = version_2(flat)
    profile = task_profile.embedded_profile(nested)
    assert profile is not None
    assert profile.to_json() == task_profile.embedded_profile(flat).to_json()
    assert task_profile.profile_hash(profile) == task_profile.profile_hash(
        task_profile.embedded_profile(flat))

    config = task_profile.recorded_config(nested, profile)
    assert config and config == task_profile.recorded_config(flat, profile)
    assert task_profile.params_hash(config) == task_profile.params_hash(
        task_profile.recorded_config(flat, profile))

    assert stream.summarize(nested, profile).to_json() == stream.summarize(flat, profile).to_json()
    table = stream.trial_table_of(nested, profile)
    assert table is not None and table["trials"] and table == stream.trial_table_of(flat, profile)
    assert derived.derive(nested) == derived.derive(flat)


def test_the_reader_hands_back_version_2_whichever_shape_the_file_has(tmp_path: Path) -> None:
    flat = {**recorded_document(), "derived": {"status": "ok", "trials": []}}
    for name, document in (("flat.json", flat), ("nested.json", version_2(flat))):
        path = tmp_path / name
        path.write_text(json.dumps(document), encoding="utf-8")
        result = reader.read_run(path)
        assert result.ok, result.detail
        # ... with the odors table its snapshot gives: a spine tracer has none.
        assert result.document == rd.with_odors(version_2(recorded_document()), []), name


async def test_analytics_shows_a_version_2_run_as_it_shows_its_twin(rig) -> None:  # noqa: ANN001, F811
    flat = recorded_document()
    run_id = write_document(rig, flat)
    before = (await rig.service.summary(rig.cohort.id))["runs"][0]
    [series_before] = (await rig.service.series([run_id]))["series"]
    assert before["status"] == "ok" and before["paramsHash"] and before["profileHash"]

    path = Path(rig.sessions.runs_for(before["sessionId"])[0].file_path)
    path.write_text(json.dumps(version_2(flat)), encoding="utf-8")
    after = (await rig.service.summary(rig.cohort.id))["runs"][0]
    [series_after] = (await rig.service.series([run_id]))["series"]

    assert after == before
    assert series_after == series_before


# --- a newer build's file ----------------------------------------------------- #

def test_a_document_from_a_newer_build_is_unreadable_and_says_why(tmp_path: Path) -> None:
    path = tmp_path / "remy1.json"
    path.write_text(json.dumps({**version_2(recorded_document()), "schema_version": 3}), encoding="utf-8")
    result = reader.read_run(path)
    assert result.status == "unreadable" and result.document is None
    assert "remy1.json" in result.detail and "version 3" in result.detail and "newer" in result.detail


async def test_analytics_reports_a_newer_builds_run_unreadable(rig) -> None:  # noqa: ANN001, F811
    flat = recorded_document()
    write_document(rig, flat)
    row = (await rig.service.summary(rig.cohort.id))["runs"][0]
    path = Path(rig.sessions.runs_for(row["sessionId"])[0].file_path)
    path.write_text(json.dumps({**version_2(flat), "schema_version": 3}), encoding="utf-8")
    after = (await rig.service.summary(rig.cohort.id))["runs"][0]
    assert after["status"] == "unreadable" and "newer" in after["detail"]


# --- Re-derive, Recover, adoption and a move ---------------------------------- #

async def test_rederive_rewrites_a_version_2_runs_trials_block_in_place(rig) -> None:  # noqa: ANN001, F811
    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    nested = version_2(read_json(json_path))
    assert nested["trials"]["rows"], "the fixture has a table to lose"
    stale = {**nested, "trials": {**nested["trials"], "rows": [], "replay_version": 0}}
    json_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")

    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["rewritten"], result["failed"], result["skipped"]) == (1, 0, 0), result["entries"]
    after = read_json(json_path)
    assert after == nested and list(after) == list(nested), "still version 2, every other block as read"

    on_disk = load_mat(mat)
    assert on_disk["trials"]["rows"][0, 0].shape == (len(nested["trials"]["rows"]), 1)
    assert on_disk["run"]["animal"][0, 0][0] == "remy1"
    assert (await rig.archive.rederive(rig.cohort.id))["current"] == 1


async def test_rederive_reads_and_rewrites_an_old_files_derived_block_where_it_is(rig) -> None:  # noqa: ANN001, F811
    """A version-1 file keeps its shape: the same block, as `derived`, its rows
    under `trials`. A newer replay's block there is still left alone."""
    _, json_path, _ = run_through_writer(rig.root, recorded_document())
    flat = recorded_document()
    current = derived.derive(flat)
    assert current["trials"], "the fixture has a table to lose"
    stale = {**flat, "derived": {**current, "trials": [], "replay_version": 0}}
    json_path.write_text(json.dumps(stale, indent=2), encoding="utf-8")

    result = await rig.archive.rederive(rig.cohort.id)
    assert (result["rewritten"], result["failed"], result["skipped"]) == (1, 0, 0), result["entries"]
    after = read_json(json_path)
    assert after == {**flat, "derived": current} and "schema_version" not in after
    assert list(after)[-1] == "derived"
    assert load_mat(json_path.parent.parent / "behavior.mat" / "remy1.mat")["derived"]["trials"][0, 0].shape == (
        len(current["trials"]), 1)
    assert (await rig.archive.rederive(rig.cohort.id))["current"] == 1

    newer = {**flat, "derived": {**current, "trials": [], "replay_version": current["replay_version"] + 1}}
    json_path.write_text(json.dumps(newer, indent=2), encoding="utf-8")
    [entry] = (await rig.archive.rederive(rig.cohort.id))["entries"]
    assert entry["status"] == "skipped" and "newer replay" in entry["reason"]
    assert read_json(json_path) == newer


async def test_rederive_leaves_a_newer_builds_document_alone(rig) -> None:  # noqa: ANN001, F811
    _, json_path, mat = run_through_writer(rig.root, recorded_document())
    newer = json.dumps({**version_2(read_json(json_path)), "schema_version": 3}, indent=2)
    json_path.write_text(newer, encoding="utf-8")
    mat_bytes = mat.read_bytes()

    result = await rig.archive.rederive(rig.cohort.id)
    [entry] = result["entries"]
    assert entry["status"] == "skipped" and "newer" in entry["reason"]
    assert json_path.read_text(encoding="utf-8") == newer and mat.read_bytes() == mat_bytes


@pytest.mark.parametrize("version", [2, 3])
def test_recover_never_offers_a_log_whose_json_is_whole(rig, version: int) -> None:  # noqa: ANN001, F811
    tsv, json_path, _ = run_through_writer(rig.root, recorded_document())
    nested = {**version_2(read_json(json_path)), "schema_version": version}
    json_path.write_text(json.dumps(nested), encoding="utf-8")
    assert reader.walk_orphaned_tsvs(rig.root / "cohort", parse_json=True) == []
    assert tsv.is_file()


async def test_a_version_2_file_is_adopted_by_the_animal_it_names(adoption_db, tmp_path: Path) -> None:  # noqa: ANN001, F811
    legacy = LegacyRig(adoption_db, tmp_path)
    path = legacy.add_legacy_run("remy2", [101, 249, 101, 248])
    path.write_text(json.dumps(version_2(read_json(path))), encoding="utf-8")
    await legacy.archive.rescan(legacy.cohort.id)
    [adopted] = legacy.repo.adopted_for_cohort(legacy.cohort.id)
    assert adopted.animal_id == "a2" and adopted.sketch_name == "GRGL_2-Odor"


def test_a_version_2_file_moves_with_its_animal(adoption_db, tmp_path: Path) -> None:  # noqa: ANN001, F811
    lab = Lab(adoption_db, tmp_path)
    [json_path] = lab.folder("2", "2026-07-23").glob("behavior.json/*.json")
    nested = json.dumps(version_2(read_json(json_path)))
    json_path.write_text(nested, encoding="utf-8")
    lab.apply("slow1")
    [moved] = lab.folder("2", "2026-07-23", lab.b_root).glob("behavior.json/*.json")
    assert moved.read_text(encoding="utf-8") == nested and not json_path.exists()


# --- the .mat of a version-2 document ----------------------------------------- #

def test_a_version_2_mat_holds_each_block_as_a_struct(tmp_path: Path) -> None:
    path = tmp_path / "v2.mat"
    matwriter.savemat(str(path), V2)
    on_disk = load_mat(path)
    assert float(on_disk["schema_version"][0, 0]) == 2.0
    assert on_disk["run"]["animal"][0, 0][0] == "remy1"
    assert on_disk["params"]["num_trials"][0, 0][0, 0] == 1000.0
    assert on_disk["params"]["num_trials"][0, 0].dtype == float
    assert on_disk["ts_data"].shape == (2, 2)
    assert json.loads(on_disk["task_profile"][0]) == V2["task_profile"]


def test_a_version_2_animal_name_outside_the_bmp_is_refused_by_name() -> None:
    document = {**V2, "run": {**V2["run"], "animal": "remy🐭"}}
    assert matwriter.refusal(document) == "the animal name can't be written to a .mat"
    assert matwriter.refusal(V2) is None
    with pytest.raises(ValueError):
        matwriter.to_matlab(document)
