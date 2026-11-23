"""The spike export for Offline Sorter — `RECORDING.md#the-sort-export`.

Each recorded animal gets `sort/<run>.spikes.mat`: the three variables the
lab's own MATLAB functions write (`save_extracted_spikes.m`), restricted to
that animal's channels, so Offline Sorter's import is set up as it is now.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import numpy as np
import pytest
import scipy.io

from ephymeris_sidecar.intan import sort_export
from ephymeris_sidecar.intan.sort_export import export_run, export_spikes
from ephymeris_sidecar.sessions import run_document as rd

RATE = 30000.0


def spike_file(path: Path, records: list[tuple[str, int, int, list[int]]], *,
               names: list[str], pre: int = 30, post: int = 30, tail: bytes = b"") -> Path:
    """An RHX `spike.dat`: `records` are (native name, timestamp, id, snapshot counts)."""
    out = struct.pack("<IH", 0x18F8474B, 1)
    out += b"rec_260417_095743\x00" + ",".join(names).encode() + b"\x00" + ",".join(names).encode() + b"\x00"
    out += struct.pack("<fII", RATE, pre, post)
    for name, stamp, unit, snapshot in records:
        assert len(snapshot) == pre + post
        out += struct.pack("<5siB", name.encode(), stamp, unit) + struct.pack(f"<{pre + post}H", *snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out + tail)
    return path


def ramp(start: int, n: int = 60) -> list[int]:
    """A snapshot whose every sample is different: `start`, `start + 1`, …"""
    return [start + i for i in range(n)]


NAMES = ["A-000", "A-001", "A-002", "C-000"]
RECORDS = [
    ("A-000", 300, 1, ramp(32768)),
    ("C-000", 450, 1, ramp(1000)),
    ("A-001", 600, 1, ramp(40000)),
    ("A-000", 900, 128, ramp(20000)),   # RHX's artifact flag: kept, as the lab keeps it
    ("A-000", 1500, 1, ramp(32000)),
]


def load(path: Path) -> dict:
    return scipy.io.loadmat(str(path))


def cells(loaded: dict, name: str) -> list:
    return [loaded[name][k, 0] for k in range(loaded[name].shape[0])]


# --- the file ------------------------------------------------------------------ #

def test_the_export_holds_the_labs_three_variables_for_the_animals_channels(tmp_path: Path) -> None:
    spikes = spike_file(tmp_path / "rhx" / "spike.dat", RECORDS, names=NAMES)
    out = tmp_path / "sort" / "remy1.spikes.mat"
    result = export_spikes(spikes, out, ["A-000", "A-001", "A-002"])
    assert (result.status, result.reason, result.path) == ("written", None, out)
    assert (result.channels, result.spikes) == (2, 4)

    loaded = load(out)
    assert {k for k in loaded if not k.startswith("__")} == {"spiketimes", "spikewaves", "unique_ch"}
    for name in ("spiketimes", "spikewaves", "unique_ch"):
        assert loaded[name].shape == (2, 1) and loaded[name].dtype == object, "K×1 cell"
    # One whole native name per cell; a channel with no spikes (A-002) and
    # another animal's channel (C-000) are left out.
    assert [str(c[0]) for c in cells(loaded, "unique_ch")] == ["A-000", "A-001"]

    times = cells(loaded, "spiketimes")
    assert times[0].shape == (3, 1) and times[0].dtype == np.float64, "n×1 double, seconds"
    assert times[0].ravel().tolist() == [300 / RATE, 900 / RATE, 1500 / RATE], "file order, id 128 kept"
    assert times[1].ravel().tolist() == [600 / RATE]


def test_a_waveform_is_30_samples_in_microvolts_from_6_before_the_crossing_to_24_after(tmp_path: Path) -> None:
    """Samples 25:54 (1-based) of a snapshot with 30 pre-detect samples, as
    the lab has always sorted on; µV is 0.195 × (count − 32768)."""
    spikes = spike_file(tmp_path / "spike.dat", RECORDS, names=NAMES)
    out = tmp_path / "out.mat"
    export_spikes(spikes, out, ["A-000", "A-001"])
    waves = cells(load(out), "spikewaves")
    assert waves[0].shape == (3, 30) and waves[0].dtype == np.float64, "rows are spikes"
    counts = np.array([ramp(32768)[24:54], ramp(20000)[24:54], ramp(32000)[24:54]], dtype=np.float64)
    assert np.array_equal(waves[0], 0.195 * (counts - 32768.0))
    assert waves[0][0, 0] == 0.195 * 24 and waves[0][0, -1] == 0.195 * 53
    assert waves[1].shape == (1, 30)


def test_the_window_is_counted_from_the_crossing_for_another_lead_in(tmp_path: Path) -> None:
    """10 samples kept before a detection and 40 after: the same part of the spike."""
    record = ("A-000", 300, 1, ramp(32768, 50))
    spikes = spike_file(tmp_path / "spike.dat", [record], names=["A-000"], pre=10, post=40)
    out = tmp_path / "out.mat"
    assert export_spikes(spikes, out, ["A-000"]).status == "written"
    (wave,) = cells(load(out), "spikewaves")
    assert wave.shape == (1, 30)
    assert wave[0].tolist() == [0.195 * i for i in range(4, 34)], "samples 4..33: 6 before, 24 after"


def test_reading_in_small_chunks_gives_the_same_file(tmp_path: Path) -> None:
    many = [("A-000" if i % 3 else "A-001", 100 * i, 1, ramp(30000 + i)) for i in range(50)]
    spikes = spike_file(tmp_path / "spike.dat", many, names=NAMES, tail=b"\x00" * 17)  # a torn last record
    whole, chunked = tmp_path / "whole.mat", tmp_path / "chunked.mat"
    export_spikes(spikes, whole, ["A-000", "A-001"])
    export_spikes(spikes, chunked, ["A-000", "A-001"], chunk_records=7)
    a, b = load(whole), load(chunked)
    for name in ("spiketimes", "spikewaves"):
        for x, y in zip(cells(a, name), cells(b, name)):
            assert np.array_equal(x, y)
    assert sum(c.shape[0] for c in cells(a, "spiketimes")) == 50


# --- when there is nothing to write --------------------------------------------- #

def test_a_recording_with_no_snapshots_writes_no_file_and_says_why(tmp_path: Path) -> None:
    bare = [("A-000", 300, 1, [])]
    spikes = spike_file(tmp_path / "spike.dat", bare, names=["A-000"], pre=0, post=0)
    out = tmp_path / "sort" / "remy1.spikes.mat"
    result = export_spikes(spikes, out, ["A-000"])
    assert result.status == "skipped" and not out.exists() and not out.parent.exists()
    assert "no spike snapshots" in result.reason and "nothing to sort" in result.reason


@pytest.mark.parametrize(("pre", "post"), [(3, 30), (30, 10)])
def test_a_snapshot_too_short_for_the_window_writes_no_file(tmp_path: Path, pre: int, post: int) -> None:
    spikes = spike_file(tmp_path / "spike.dat", [("A-000", 1, 1, ramp(1, pre + post))], names=["A-000"],
                        pre=pre, post=post)
    result = export_spikes(spikes, tmp_path / "out.mat", ["A-000"])
    assert result.status == "skipped" and "6 samples before" in result.reason
    assert not (tmp_path / "out.mat").exists()


def test_no_spike_on_the_animals_channels_writes_no_file(tmp_path: Path) -> None:
    spikes = spike_file(tmp_path / "spike.dat", RECORDS, names=NAMES)
    result = export_spikes(spikes, tmp_path / "out.mat", ["A-002", "B-000"])
    assert result.status == "skipped" and "no spikes" in result.reason
    assert not (tmp_path / "out.mat").exists()


def test_a_missing_or_foreign_spike_file_fails_the_export_and_nothing_else(tmp_path: Path) -> None:
    missing = export_spikes(tmp_path / "nowhere" / "spike.dat", tmp_path / "out.mat", ["A-000"])
    assert missing.status == "failed" and "spike.dat" in missing.reason
    (tmp_path / "spike.dat").write_bytes(b"not an RHX file at all")
    foreign = export_spikes(tmp_path / "spike.dat", tmp_path / "out.mat", ["A-000"])
    assert foreign.status == "failed" and "magic" in foreign.reason
    assert not (tmp_path / "out.mat").exists()


def test_a_write_that_fails_leaves_no_file_under_the_real_name(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    spikes = spike_file(tmp_path / "spike.dat", RECORDS, names=NAMES)
    out = tmp_path / "sort" / "remy1.spikes.mat"

    def full_disk(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("No space left on device")

    monkeypatch.setattr(scipy.io, "savemat", full_disk)
    result = export_spikes(spikes, out, ["A-000"])
    assert result.status == "failed" and "No space left" in result.reason
    assert not out.exists() and list(out.parent.glob("*")) == [], "whole or not at all"


# --- one run -------------------------------------------------------------------- #

def run_document(folder: Path, recorded: bool = True) -> dict:
    fields = {"rat": "remy1", "sketch": "GRGL"}
    if recorded:
        fields |= {"intan_recording": folder.name, "intan_path": str(folder.parent), "intan_port": "A",
                   "intan_channels": "A-000:A-002", "intan_digital_in": 1, "intan_sample_rate": 30000,
                   "implant": None,
                   "channels": [{"native": n, "device_channel": k, "target": "", "x_um": None, "y_um": None}
                                for k, n in enumerate(["A-000", "A-001", "A-002"])]}
    return rd.build(fields, {}, None, [])


def write_run(session: Path, document: dict, stem: str = "remy1_P_1_2026-04-17_095743") -> Path:
    path = session / "behavior.json" / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_recorded_runs_export_lands_in_sort_beside_its_session_files(tmp_path: Path) -> None:
    folder = tmp_path / "ephys" / "rec_260417_095743"
    spike_file(folder / "spike.dat", RECORDS, names=NAMES)
    session = tmp_path / "cohort" / "P" / "P_1_2026-04-17"
    run = write_run(session, run_document(folder))

    result = export_run(run)
    assert result.status == "written"
    assert result.path == session / "sort" / "remy1_P_1_2026-04-17_095743.spikes.mat"
    assert [str(c[0]) for c in cells(load(result.path), "unique_ch")] == ["A-000", "A-001"]
    assert sort_export.sort_path(run) == result.path


def test_a_behavior_only_run_has_nothing_to_export(tmp_path: Path) -> None:
    session = tmp_path / "cohort" / "P" / "P_1_2026-04-17"
    run = write_run(session, run_document(tmp_path, recorded=False))
    result = export_run(run)
    assert result.status == "skipped" and "not recorded" in result.reason
    assert not (session / "sort").exists()


def test_an_export_never_raises_whatever_the_run_file_holds(tmp_path: Path) -> None:
    torn = tmp_path / "s" / "behavior.json" / "torn.json"
    torn.parent.mkdir(parents=True)
    torn.write_text("{", encoding="utf-8")
    assert export_run(torn).status == "failed"
    assert export_run(tmp_path / "nowhere.json").status == "failed"


def test_every_recorded_run_of_a_session_is_exported_and_one_failure_stops_no_other(tmp_path: Path) -> None:
    folder = tmp_path / "ephys" / "rec_260417_095743"
    spike_file(folder / "spike.dat", RECORDS, names=NAMES)
    session = tmp_path / "cohort" / "P" / "P_1_2026-04-17"
    good = write_run(session, run_document(folder), "remy1_P_1_2026-04-17_095743")
    lost = write_run(session, run_document(tmp_path / "ephys" / "gone"), "remy2_P_1_2026-04-17_095744")
    plain = write_run(session, run_document(folder, recorded=False), "remy3_P_1_2026-04-17_095745")

    results = sort_export.export_runs([good, lost, plain, None])
    assert [r.status for r in results] == ["written", "failed", "skipped"]
    assert results[0].path.is_file()


def test_only_the_runs_inside_the_recording_just_stopped_are_exported(tmp_path: Path) -> None:
    """A later round's stop does not write an earlier round's export again."""
    first, second = tmp_path / "ephys" / "rec_1", tmp_path / "ephys" / "rec_2"
    for folder in (first, second):
        spike_file(folder / "spike.dat", RECORDS, names=NAMES)
    session = tmp_path / "cohort" / "P" / "P_1_2026-04-17"
    earlier = write_run(session, run_document(first), "remy1_P_1_2026-04-17_095743")
    later = write_run(session, run_document(second), "remy1_P_1_2026-04-17_113000")

    results = sort_export.export_runs([earlier, later], "rec_2")
    assert [r.path for r in results] == [sort_export.sort_path(later)]
    assert not sort_export.sort_path(earlier).exists()


# --- against the lab's own script, on a real recording --------------------------- #

REAL = os.environ.get("EPHYMERIS_RHX_SAMPLE")
LAB = os.environ.get("EPHYMERIS_LAB_EXPORTS")


@pytest.mark.skipif(not (REAL and LAB), reason="set EPHYMERIS_RHX_SAMPLE to an RHX folder and "
                    "EPHYMERIS_LAB_EXPORTS to the folder ExtractIntanSpikes.py wrote for it")
@pytest.mark.parametrize("port", ["A", "C"])
def test_a_ports_export_equals_the_labs_own_value_for_value(tmp_path: Path, port: str) -> None:
    (lab_file,) = Path(LAB).glob(f"*_port_{port}.mat")
    lab = load(lab_file)
    names = [f"{port}-{n:03d}" for n in range(128)]
    result = export_spikes(Path(REAL) / "spike.dat", tmp_path / "ours.mat", names)
    assert result.status == "written", result.reason
    ours = load(result.path)
    assert [str(c[0]) for c in cells(ours, "unique_ch")] == [str(c[0]) for c in cells(lab, "unique_ch")]
    for name in ("spiketimes", "spikewaves"):
        for mine, theirs in zip(cells(ours, name), cells(lab, name)):
            assert mine.dtype == theirs.dtype and np.array_equal(mine, theirs), name
