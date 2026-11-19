"""A recorded run knows its implant and its channels — `RECORDING.md#what-is-written`.

Beside its `recording` block, a recorded run's document carries a copy of
the animal's implant as it stood on the run's date, and a `channels` table:
one row per recorded channel, joining RHX's native name to the channel's
number on the device and to its target.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import scipy.io

from ephymeris_sidecar.cohorts import implants
from ephymeris_sidecar.intan import probemap
from ephymeris_sidecar.sessions import matwriter, recovery
from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.sessions.writer import AnimalWriter
from tests.scripted_board import Bench
from tests.test_implants import implant
from tests.test_session_runner import _short_seed_window, bench, make_runner, wait_until  # noqa: F401 - fixtures

LOWERED = implants.parse_implant(implant(
    probeMapPath="C:/maps/remy1.xml",
    lowerings=[{"date": "2026-12-14", "mm": 0.25}],
))


def natives(port: str, first: int, last: int) -> list[str]:
    return [f"{port}-{n:03d}" for n in range(first, last + 1)]


# --- the implant as it stood on a date ------------------------------------------ #

def test_a_runs_copy_resolves_each_targets_depth_on_its_date() -> None:
    before = implants.on_date(LOWERED, "2026-12-10")
    assert before == {
        "device": "custom 32-channel electrode", "surgery_date": "2026-11-30",
        "probe_map": "C:/maps/remy1.xml",
        "targets": [
            {"name": "OFC", "region": "orbitofrontal cortex", "hemisphere": "left",
             "ap_mm": 3.2, "ml_mm": 2.4, "dv_mm": 4.6, "depth_set_on": "2026-11-30", "channels": "0-15"},
            {"name": "DMS", "region": "dorsomedial striatum", "hemisphere": "left",
             "ap_mm": 0.2, "ml_mm": 2.4, "dv_mm": 4.0, "depth_set_on": "2026-11-30", "channels": "16-31"},
        ],
    }
    after = implants.on_date(LOWERED, "2026-12-20")
    assert [(t["dv_mm"], t["depth_set_on"]) for t in after["targets"]] == [
        (4.85, "2026-12-14"), (4.25, "2026-12-14")]
    assert "lowerings" not in after, "a run holds the depth in force, not the history"
    assert implants.on_date(None, "2026-12-20") is None


# --- the channels table --------------------------------------------------------- #

def test_device_channel_k_is_the_native_name_at_the_range_start_plus_k() -> None:
    """A box on A-016 to A-047: the device's channel 0 is A-016."""
    rows = implants.channel_rows(natives("A", 16, 47), implants.on_date(LOWERED, "2026-12-20"))
    assert len(rows) == 32
    assert rows[0] == {"native": "A-016", "device_channel": 0, "target": "OFC", "x_um": None, "y_um": None}
    assert rows[15]["native"] == "A-031" and rows[15]["target"] == "OFC"
    assert rows[16] == {"native": "A-032", "device_channel": 16, "target": "DMS", "x_um": None, "y_um": None}
    assert [r["device_channel"] for r in rows] == list(range(32))


def test_a_channel_no_target_claims_and_an_animal_with_no_implant_have_an_empty_target() -> None:
    half = implants.on_date(implants.parse_implant(implant(targets=[implant()["targets"][0]])), "2026-12-01")
    rows = implants.channel_rows(natives("B", 0, 31), half)
    assert {r["target"] for r in rows[:16]} == {"OFC"} and {r["target"] for r in rows[16:]} == {""}
    bare = implants.channel_rows(natives("B", 0, 3), None)
    assert [(r["native"], r["device_channel"], r["target"]) for r in bare] == [
        ("B-000", 0, ""), ("B-001", 1, ""), ("B-002", 2, ""), ("B-003", 3, "")]


PROBE_XML = """<?xml version="1.0"?>
<ProbeMapSettings>
  <Page name="shank">
    <Port name="A">
      <ElectrodeSite channelNumber="16" x="0" y="0"/>
      <ElectrodeSite channelNumber="17" x="12.5" y="-20"/>
    </Port>
  </Page>
</ProbeMapSettings>
"""


def test_a_probe_map_gives_each_site_its_position() -> None:
    positions = probemap.positions(probemap.parse(PROBE_XML))
    assert positions == {"A-016": (0.0, 0.0), "A-017": (12.5, -20.0)}
    rows = implants.channel_rows(natives("A", 16, 18), None, positions)
    assert [(r["x_um"], r["y_um"]) for r in rows] == [(0.0, 0.0), (12.5, -20.0), (None, None)]
    assert probemap.positions(None) == {}


# --- in the document ------------------------------------------------------------ #

RECORDING = {"intan_recording": "0423_7", "intan_path": "D:/rhx", "intan_digital_in": 1,
             "intan_port": "A", "intan_channels": "A-016:A-047", "intan_sample_rate": 30000}


def files(tmp_path: Path) -> tuple[Path, Path, Path]:
    session = tmp_path / "cohort" / "P" / "P_1_2026-12-20"
    return (session / "behavior.tsv" / "remy1.tsv", session / "behavior.json" / "remy1.json",
            session / "behavior.mat" / "remy1.mat")


def written(tmp_path: Path, copy: dict | None) -> tuple[Path, Path, Path]:
    tsv, json_path, mat = files(tmp_path)
    core = {"rat": "remy1", "sketch": "GRGL", "stream": 1, **RECORDING,
            "implant": copy, "channels": implants.channel_rows(natives("A", 16, 47), copy)}
    writer = AnimalWriter(tsv, json_path, mat, core, {"num_trials": 10})
    writer.open_files()
    writer.record(221, 0)
    writer.finalize("BF_END_SESSION received")
    return tsv, json_path, mat


def test_the_blocks_sit_after_the_recording_and_never_in_the_parameters(tmp_path: Path) -> None:
    copy = implants.on_date(LOWERED, "2026-12-20")
    _, json_path, _ = written(tmp_path, copy)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert list(document) == ["schema_version", "run", "task", "params", "odors", "recording",
                              "implant", "channels", "ts_data"]
    assert document["implant"] == copy and len(document["channels"]) == 32
    assert document["params"] == {"num_trials": 10}
    assert rd.implant_of(document) == copy and rd.channels_of(document) == document["channels"]
    assert rd.implant_of({"rat": "remy1"}) is None and rd.channels_of({"rat": "remy1"}) is None


def test_a_recovered_recorded_run_keeps_its_implant_and_channels(tmp_path: Path) -> None:
    tsv, json_path, _ = written(tmp_path, implants.on_date(LOWERED, "2026-12-20"))
    header = tsv.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith('# implant: {"device":') for line in header)
    assert any(line.startswith('# channels: [{"native":"A-016"') for line in header)
    finalized = json.loads(json_path.read_text(encoding="utf-8"))
    json_path.unlink()
    assert recovery.recover_file(tsv)["status"] == "recovered"
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered["implant"] == finalized["implant"] and recovered["channels"] == finalized["channels"]
    assert list(recovered)[:8] == list(finalized)[:8]


def test_an_animal_with_no_implant_records_with_a_null_implant_and_recovers_so(tmp_path: Path) -> None:
    tsv, json_path, _ = written(tmp_path, None)
    document = json.loads(json_path.read_text(encoding="utf-8"))
    assert "implant" in document and document["implant"] is None
    assert {row["target"] for row in document["channels"]} == {""}
    json_path.unlink()
    recovery.recover_file(tsv)
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered["implant"] is None and recovered["channels"] == document["channels"]


def test_a_tsv_whose_header_names_a_parameter_called_channels_is_not_misread(tmp_path: Path) -> None:
    """Only a version-2 header carries the blocks; an older one is all parameters."""
    tsv, json_path, _ = files(tmp_path)
    tsv.parent.mkdir(parents=True)
    tsv.write_text("# rat: remy1\n# channels: 16\n# implant: none\n221\t0\n", encoding="utf-8")
    recovery.recover_file(tsv)
    recovered = json.loads(json_path.read_text(encoding="utf-8"))
    assert recovered["params"] == {"channels": 16, "implant": "none"}
    assert "implant" not in recovered and "channels" not in recovered


def test_the_mat_holds_the_implant_as_a_struct_and_the_channels_as_a_table(tmp_path: Path) -> None:
    _, _, mat = written(tmp_path, implants.on_date(LOWERED, "2026-12-20"))
    loaded = scipy.io.loadmat(str(mat))
    held = loaded["implant"][0, 0]
    assert str(held["device"][0]) == "custom 32-channel electrode"
    assert str(held["probe_map"][0]) == "C:/maps/remy1.xml"
    targets = held["targets"]
    assert targets.shape == (2, 1), "N×1, so struct2table(S.implant.targets) is one row per target"
    assert str(targets[0, 0]["name"][0]) == "OFC" and float(targets[0, 0]["dv_mm"][0, 0]) == 4.85
    assert str(targets[1, 0]["depth_set_on"][0]) == "2026-12-14"
    channels = loaded["channels"]
    assert channels.shape == (32, 1)
    assert str(channels[16, 0]["native"][0]) == "A-032" and float(channels[16, 0]["device_channel"][0, 0]) == 16.0
    assert str(channels[16, 0]["target"][0]) == "DMS"
    assert str(float(channels[0, 0]["x_um"][0, 0])) == "nan", "no probe map: NaN, never []"


def test_a_null_implant_is_an_empty_struct_of_the_same_fields_in_the_mat(tmp_path: Path) -> None:
    path = tmp_path / "none.mat"
    document = rd.build({"rat": "remy1", **RECORDING, "implant": None,
                         "channels": implants.channel_rows(natives("A", 16, 17), None)}, {})
    matwriter.savemat(str(path), document)
    held = scipy.io.loadmat(str(path))["implant"][0, 0]
    assert held["device"].size == 0 and held["targets"].shape == (0, 1)
    assert set(held["targets"].dtype.names) >= {"name", "dv_mm", "depth_set_on", "channels"}


# --- from a run on a box -------------------------------------------------------- #

async def record_a_run(tmp_path: Path, bench: Bench, date: str, held: dict | None, folder: str) -> dict:  # noqa: F811
    runner, _events, ended = make_runner(tmp_path / folder, bench)
    [config] = runner.box_configs()
    config.implant = held
    runner.configure(tmp_path / folder, "2O-Bdisc_25", [config], session_id="s1",
                     cohort_name="The Remy's", session_date=date)
    runner.recording_fields = lambda box: dict(RECORDING)
    runner.recording_positions = lambda box: {"A-016": (0.0, 0.0)}
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t10")
    await wait_until(lambda: bool(ended))
    return json.loads(next((tmp_path / folder / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))


async def test_a_recorded_run_copies_the_implant_as_it_stood_that_day(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    held = json.loads(json.dumps(LOWERED))
    document = await record_a_run(tmp_path, bench, "2026-12-10", held, "before")
    assert document["recording"]["channels"] == "A-016:A-047"
    assert [t["dv_mm"] for t in document["implant"]["targets"]] == [4.6, 4.0]
    assert document["channels"][0] == {"native": "A-016", "device_channel": 0, "target": "OFC",
                                       "x_um": 0.0, "y_um": 0.0}
    assert len(document["channels"]) == 32 and document["channels"][31]["target"] == "DMS"

    # Editing the implant afterwards changes no file already written.
    held["lowerings"].append({"date": "2026-12-11", "mm": 9})
    again = json.loads(next((tmp_path / "before" / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))
    assert again == document


async def test_a_run_after_a_lowering_copies_the_deeper_depth(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    document = await record_a_run(tmp_path, bench, "2026-12-20", LOWERED, "after")
    assert [(t["dv_mm"], t["depth_set_on"]) for t in document["implant"]["targets"]] == [
        (4.85, "2026-12-14"), (4.25, "2026-12-14")]


async def test_an_animal_with_no_implant_records_normally(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    document = await record_a_run(tmp_path, bench, "2026-12-20", None, "none")
    assert document["implant"] is None
    assert len(document["channels"]) == 32 and {r["target"] for r in document["channels"]} == {""}


async def test_a_behavior_only_run_has_neither_block(tmp_path: Path, bench: Bench) -> None:  # noqa: F811
    runner, _events, ended = make_runner(tmp_path, bench)
    [config] = runner.box_configs()
    config.implant = LOWERED
    runner.start_box(1)
    board = await bench.run_handshake(1)
    await board.said("246\t10")
    await wait_until(lambda: bool(ended))
    document = json.loads(next((tmp_path / "behavior.json").glob("*.json")).read_text(encoding="utf-8"))
    assert "implant" not in document and "channels" not in document and "recording" not in document
