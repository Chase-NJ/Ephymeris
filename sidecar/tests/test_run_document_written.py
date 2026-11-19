"""New runs are written as version 2 — `DATA.md#the-json-document`.

The writer, Recover and every in-memory builder make the nested document
through `sessions/run_document.py`; the `.tsv` header carries the same facts,
so a recovered run is the document finalization would have written.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.sessions import recovery
from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.sessions.runner import CLEAN_STOP_REASON
from ephymeris_sidecar.sessions.writer import AnimalWriter
from ephymeris_sidecar.tasks import profile as task_profile
from ephymeris_sidecar.tasks.profile import parse_profile
from tests.scripted_board import Bench
from tests.test_cohort_move import Lab
from tests.test_session_runner import GRGL, _short_seed_window, bench, make_runner, wait_until  # noqa: F401 - fixtures

SNAPSHOT = {"taskName": "GRGL 8-Odor EZ", "config": [
    {"metadataKey": "num_trials", "wireKey": "NT", "label": "Trials", "type": "int", "default": 1000},
    {"metadataKey": "lazy_escalation", "wireKey": "LAZY", "label": "Lazy", "type": "bool", "default": True},
]}

FIELDS = {
    "rat": "remy1", "cohort": "The Remy's", "box": 2, "session_id": "8O-Bdisc_09",
    "date": "2026-10-30", "run_of_day": 1, "started_at": "2026-10-30T11:29:26-05:00",
    "serial_port": "COM5", "sketch": "GRGL 8-Odor EZ", "stream": 1, "interp": 1, "free_ram": 5120,
    "trial_seed": 1987552345, "host_seed": 1987552345,
    "channel_set_hash": "0123", "channel_set_hash_version": 2,
    "intan_recording": "0423_7", "intan_path": "D:/rhx", "intan_digital_in": 1, "intan_port": "A",
    "intan_channels": "A-016:A-031", "intan_sample_rate": 30000,
}
PARAMS = {"num_trials": 1000, "lazy_escalation": True}
STROBES = [[221, 0], [222, 1001]]

#: The document those make, block by block and key by key as the ADR writes it.
WRITTEN = {
    "schema_version": 2,
    "run": {"animal": "remy1", "cohort": "The Remy's", "box": 2, "session_id": "8O-Bdisc_09",
            "date": "2026-10-30", "run_of_day": 1, "started_at": "2026-10-30T11:29:26-05:00",
            "serial_port": "COM5", "stop_reason": "BF_END_SESSION received", "n_events": 2},
    "task": {"sketch": "GRGL 8-Odor EZ", "stream": 1, "interp": 1, "free_ram": 5120,
             "trial_seed": 1987552345, "host_seed": 1987552345,
             "channel_set_hash": "0123", "channel_set_hash_version": 2},
    "params": {"num_trials": 1000, "lazy_escalation": True},
    "recording": {"path": "D:/rhx", "name": "0423_7", "port": "A", "channels": "A-016:A-031",
                  "digital_in": 1, "sample_rate": 30000},
    "ts_data": [[221, 0], [222, 1001]],
    "task_profile": SNAPSHOT,
}


def keys(document: dict) -> list:
    """Every key of a document and of its blocks, in order."""
    return [(key, list(value) if isinstance(value, dict) and key != "task_profile" else None)
            for key, value in document.items()]


# --- building and editing ------------------------------------------------------ #

def test_a_document_is_built_block_by_block_in_the_adrs_order() -> None:
    shuffled = dict(reversed(list(FIELDS.items())))
    built = rd.build({**shuffled, "stop_reason": "BF_END_SESSION received", "n_events": 2},
                     PARAMS, SNAPSHOT, STROBES)
    assert built == WRITTEN
    assert keys(built) == keys(WRITTEN), "the order is the module's, never the caller's"


def test_a_behavior_only_run_has_no_recording_block_and_no_field_it_was_not_given() -> None:
    built = rd.build({"rat": "remy1", "sketch": "T"}, {}, None, [])
    assert built == {"schema_version": 2, "run": {"animal": "remy1"}, "task": {"sketch": "T"},
                     "params": {}, "ts_data": []}
    assert "ts_data" not in rd.build({"rat": "remy1"}, {})


def test_a_parameter_named_like_a_core_field_sits_beside_it() -> None:
    built = rd.build({"rat": "remy1", "sketch": "T"}, {"rat": 300, "sketch": 5, "box": 9})
    assert rd.animal_of(built) == "remy1" and rd.sketch_of(built) == "T"
    assert rd.params_of(built) == {"rat": 300, "sketch": 5, "box": 9}
    assert "box" not in built["run"]


def test_a_field_is_replaced_and_removed_in_a_copy() -> None:
    edited = rd.replaced(WRITTEN, rat="canary", stop_reason="host stopped", sync="tick")
    assert rd.animal_of(edited) == "canary" and rd.stop_reason_of(edited) == "host stopped"
    assert rd.sync_of(edited) == "tick" and rd.animal_of(WRITTEN) == "remy1"
    assert keys(rd.replaced(WRITTEN, rat="canary")) == keys(WRITTEN)
    seedless = rd.without_field(WRITTEN, "trial_seed")
    assert rd.trial_seed_of(seedless) is None and "trial_seed" not in seedless["task"]
    assert rd.trial_seed_of(WRITTEN) == 1987552345
    with pytest.raises(KeyError):
        rd.replaced(WRITTEN, num_trials=3)


def test_strobes_are_set_in_their_place() -> None:
    header = rd.build(FIELDS, PARAMS, SNAPSHOT)
    filled = rd.with_strobes(header, STROBES)
    assert rd.strobes_of(filled) == STROBES and "ts_data" not in header
    assert list(filled)[-2:] == ["ts_data", "task_profile"]


def test_the_same_edits_work_on_a_flat_document() -> None:
    flat = {"rat": "remy1", "trial_seed": 7, "ts_data": []}
    assert rd.replaced(flat, rat="canary") == {"rat": "canary", "trial_seed": 7, "ts_data": []}
    assert rd.without_field(flat, "trial_seed") == {"rat": "remy1", "ts_data": []}
    assert rd.with_strobes(flat, STROBES)["ts_data"] == STROBES


# --- the writer ---------------------------------------------------------------- #

def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    session = tmp_path / "cohort" / "8O-Bdisc" / "8O-Bdisc_09_2026-10-30"
    stem = "remy1_8O-Bdisc_09_2026-10-30_112926"
    return (session / "behavior.tsv" / f"{stem}.tsv", session / "behavior.json" / f"{stem}.json",
            session / "behavior.mat" / f"{stem}.mat")


def written(tmp_path: Path, fields: dict = FIELDS, params: dict = PARAMS, *,
            finalize: bool = True) -> tuple[Path, Path, Path]:
    tsv, json_path, mat = files(tmp_path)
    writer = AnimalWriter(tsv, json_path, mat, fields, params, profile_snapshot=SNAPSHOT)
    writer.open_files()
    for code, ts in STROBES:
        writer.record(code, ts)
    if finalize:
        writer.finalize("BF_END_SESSION received")
    return tsv, json_path, mat


def test_a_finalized_run_is_the_version_2_document(tmp_path: Path) -> None:
    _, json_path, _ = written(tmp_path)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert document == WRITTEN
    assert keys(document) == keys(WRITTEN)


def test_the_tsv_header_carries_the_run_facts_and_the_parameters(tmp_path: Path) -> None:
    tsv, _, _ = written(tmp_path)
    lines = tsv.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# schema_version: 2"
    header = lines[: lines.index("221\t0")]
    for line in ("# rat: remy1", "# cohort: The Remy's", "# box: 2", "# date: 2026-10-30",
                 "# run_of_day: 1", "# started_at: 2026-10-30T11:29:26-05:00",
                 '# params: {"num_trials":1000,"lazy_escalation":true}'):
        assert line in header, line
    assert header[-1].startswith("# task_profile: {"), "the snapshot is still the last header line"
    assert lines[-2:] == ["# stop_reason: BF_END_SESSION received", "# n_events: 2"]


def test_recover_rebuilds_the_identical_document_from_the_tsv_alone(tmp_path: Path) -> None:
    tsv, json_path, mat = written(tmp_path)
    finalized = json.loads(json_path.read_text(encoding="utf-8"))
    json_path.unlink()
    mat.unlink()

    entry = recovery.recover_file(tsv)
    assert entry["status"] == "recovered", entry
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered == finalized
    assert keys(recovered) == keys(finalized)
    assert mat.is_file()


def test_a_crashed_run_recovers_with_its_facts_and_its_own_stop_reason(tmp_path: Path) -> None:
    tsv, json_path, _ = written(tmp_path, finalize=False)
    assert recovery.recover_file(tsv)["status"] == "recovered"
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered == rd.replaced(WRITTEN, stop_reason=recovery.RECOVERED_STOP_REASON)


def test_a_parameter_named_like_a_core_field_survives_recovery(tmp_path: Path) -> None:
    params = {"rat": 300, "box": 9, "label": "007", "ratio": 0.5}
    tsv, json_path, _ = written(tmp_path, params=params)
    finalized = json.loads(json_path.read_text(encoding="utf-8"))
    assert finalized["params"] == params and finalized["run"]["animal"] == "remy1"
    json_path.unlink()
    recovery.recover_file(tsv)
    assert json.loads(json_path.read_text(encoding="utf-8")) == finalized


OLD_TSV = """# rat: remy1
# serial_port: COM5
# session_id: 8O-Bdisc_09
# sketch: GRGL 8-Odor EZ
# interp: 1
# num_trials: 1000
# box: 9
# trial_seed: 77
# task_profile: {"taskName":"GRGL 8-Odor EZ"}
221\t0
222\t1001
# stop_reason: BF_END_SESSION received
# n_events: 2
"""


def test_a_tsv_from_before_version_2_recovers_with_the_missing_facts_null(tmp_path: Path) -> None:
    tsv, json_path, _ = files(tmp_path)
    tsv.parent.mkdir(parents=True)
    tsv.write_text(OLD_TSV, encoding="utf-8")
    assert recovery.recover_file(tsv)["status"] == "recovered"
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered == {
        "schema_version": 2,
        "run": {"animal": "remy1", "cohort": None, "box": None, "session_id": "8O-Bdisc_09",
                "date": None, "run_of_day": None, "started_at": None, "serial_port": "COM5",
                "stop_reason": "BF_END_SESSION received", "n_events": 2},
        "task": {"sketch": "GRGL 8-Odor EZ", "interp": 1, "trial_seed": 77},
        # Its flat `box` line was a parameter: that header had no run facts.
        "params": {"num_trials": 1000, "box": 9},
        "ts_data": [[221, 0], [222, 1001]],
        "task_profile": {"taskName": "GRGL 8-Odor EZ"},
    }


def test_a_written_runs_hashes_are_those_of_its_parameters_and_profile(tmp_path: Path) -> None:
    _, json_path, _ = written(tmp_path)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    profile = task_profile.embedded_profile(document)
    assert task_profile.profile_hash(profile) == task_profile.profile_hash(parse_profile(SNAPSHOT))
    flat = {**FIELDS, **PARAMS, "task_profile": SNAPSHOT}
    assert task_profile.recorded_config(document, profile) == task_profile.recorded_config(flat, profile)
    assert task_profile.params_hash(task_profile.recorded_config(document, profile)) == \
        task_profile.params_hash(PARAMS)


def test_a_profile_may_name_a_parameter_like_a_core_field() -> None:
    entry = {"metadataKey": "rat", "wireKey": "RT", "label": "Rat", "type": "int", "default": 1}
    assert parse_profile({"taskName": "T", "config": [entry]}).config[0].metadata_key == "rat"


# --- the runner ---------------------------------------------------------------- #

async def test_a_run_on_a_box_writes_the_adrs_blocks(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    runner, _events, ended = make_runner(tmp_path, bench)
    asked: list[str] = []
    runner.configure(tmp_path, "2O-Bdisc_25", runner.box_configs(), session_id="s1",
                     cohort_name="The Remy's", session_date="2026-10-30",
                     earlier_runs=lambda animal_id: asked.append(animal_id) or 1)
    runner.start_box(1)
    board = await bench.run_handshake(1, seed=288577176)
    await board.said("101\t0", "249\t100", "246\t3523555")
    await wait_until(lambda: bool(ended))

    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))
    assert list(document) == ["schema_version", "run", "task", "params", "ts_data", "task_profile"]
    run = document["run"]
    assert list(run) == ["animal", "cohort", "box", "session_id", "date", "run_of_day", "started_at",
                         "serial_port", "stop_reason", "n_events"]
    assert (run["animal"], run["cohort"], run["box"], run["date"]) == ("remy1", "The Remy's", 1, "2026-10-30")
    assert run["run_of_day"] == 2 and asked == ["a1"], "one earlier run of the day, so this is the second"
    assert run["stop_reason"] == CLEAN_STOP_REASON and run["n_events"] == 3
    # ISO 8601 with its offset, to the second, and the time the file is named for.
    stem = next((tmp_path / "behavior.json").glob("*.json")).stem
    assert run["started_at"][10] == "T" and run["started_at"][-6] in "+-"
    assert run["started_at"][11:19].replace(":", "") == stem[-6:]
    assert document["task"]["sketch"] == "GRGL_2-Odor"
    assert document["task"]["trial_seed"] == 288577176 and "host_seed" in document["task"]
    assert document["params"] == {"correction_left": 0, "lazy_escalation": True}
    assert document["ts_data"] == [[101, 0], [249, 100], [246, 3523555]]


async def test_a_runner_told_no_facts_writes_them_null(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    runner, _events, ended = make_runner(tmp_path, bench)
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t10")
    await wait_until(lambda: bool(ended))
    run = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))["run"]
    assert (run["cohort"], run["date"], run["run_of_day"]) == (None, None, None)
    assert run["box"] == 1 and run["started_at"]


# --- run_of_day ----------------------------------------------------------------- #

@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


def test_earlier_runs_counts_the_animals_runs_of_that_date_in_the_cohort(db: Database, tmp_path: Path) -> None:
    lab = Lab(db, tmp_path)  # session 1 (07-22): remy1, remy2, slow1; session 2 (07-23): slow1
    count = lab.sessions.earlier_runs_of_day
    assert count(lab.a.id, "slow1", "2026-07-22") == 1
    assert count(lab.a.id, "slow1", "2026-07-23") == 1
    assert count(lab.a.id, "remy1", "2026-07-23") == 0, "none that day: the next is run 1"
    assert count(lab.b.id, "slow1", "2026-07-22") == 0, "another cohort's runs are not this one's"
    lab.add_session("3", "2026-07-22", ["slow1"])
    assert count(lab.a.id, "slow1", "2026-07-22") == 2, "a second session of one date counts too"
