"""Electrode impedance tracking (`RECORDING.md#impedance-tracking`): RHX's CSV,
each animal's history, and `intan.measureImpedance` end to end against the
fake RHX, whose `SaveImpedance` writes the file RHX writes."""

from __future__ import annotations

from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.intan.impedance import ImpedanceFileError, SiteImpedance, parse_csv
from ephymeris_sidecar.intan.impedance_store import ImpedanceStore, Measurement
from ephymeris_sidecar.intan.service import IntanNotReady
from tests.fake_rhx import FakeRhx
from tests.live_sidecar import Refused
from ephymeris_sidecar.intan.tests.test_intan_configure import _confirm_box_1, _recording_session, app, rhx  # noqa: F401
from ephymeris_sidecar.intan.tests.test_intan_service import rig  # noqa: F401
from tests.wire import dispatch

# --- the CSV ------------------------------------------------------------------


def test_rhx_s_csv_is_read_by_native_name_at_the_frequency_rhx_measured():
    """Golden text in RHX's format (`ImpedanceReader::saveImpedances`). The
    first column holds the NATIVE name, the second the custom one: reading the
    second would file a renamed channel under its label."""
    text = (
        "Channel Number,Channel Name,Port,Enabled,Impedance Magnitude at 1000.5 Hz (ohms),"
        "Impedance Phase at 1000.5 Hz (degrees),Series RC equivalent R (Ohms),"
        "Series RC equivalent C (Farads)\n"
        "A-000,tip,Port A,1,1.23e+05,-71,4.01e+04,1.33e-09\n"
        "a-001,A-001,Port A,0,5.60e+06,-12,5.48e+06,1.36e-10\n"
    )
    got = parse_csv(text)
    assert got.frequency_hz == 1000.5
    assert got.sites == (
        SiteImpedance("A-000", 123_000.0, -71.0),
        SiteImpedance("A-001", 5_600_000.0, -12.0),
    )


@pytest.mark.parametrize(
    "text",
    ["", "Channel,Name\nA-000,x\n", "Channel Number,Channel Name,Port,Enabled\nA-000,x,Port A,1\n"],
)
def test_a_file_that_is_not_rhx_s_is_refused(text):
    with pytest.raises(ImpedanceFileError):
        parse_csv(text)


# --- the history --------------------------------------------------------------


def _measurement(at: str, ohms: float, *, animal: str = "rat1") -> Measurement:
    return Measurement(
        animal_id=animal, measured_at=at, box=1, session_id="s1", frequency_hz=1000.0,
        csv_file=None, sites=(SiteImpedance("A-000", ohms, -70.0), SiteImpedance("A-001", ohms * 2, -65.0)),
    )


def test_an_animal_s_latest_and_the_one_before_it(tmp_path: Path):
    db = Database(tmp_path / "e.db")
    db.connect()
    store = ImpedanceStore(db)
    store.add([_measurement("2026-11-01T10:00:00.000+00:00", 1e5)])
    store.add([_measurement("2026-11-08T10:00:00.000+00:00", 2e5), _measurement("2026-11-08T10:00:00.000+00:00", 9e5, animal="rat2")])

    latest = store.latest("rat1")
    assert latest is not None and latest.measured_at.startswith("2026-11-08")
    assert {s.channel: s.ohms for s in latest.sites} == {"A-000": 2e5, "A-001": 4e5}
    before = store.latest("rat1", before=latest.measured_at)
    assert before is not None and before.measured_at.startswith("2026-11-01")
    assert store.latest("rat1", before=before.measured_at) is None
    assert store.latest("rat3") is None


# --- against RHX --------------------------------------------------------------


async def test_a_measurement_is_rhx_s_file_filtered_to_the_box(rig, tmp_path):  # noqa: F811
    h = await rig(impedances={"A-003": (2.2e6, -40.0)})
    reading, path = await h.service.measure_impedance(str(tmp_path / "ephys"), "impedance_x")
    assert path == tmp_path / "ephys" / "impedance_x.csv" and path.is_file()
    assert h.fake.executed[-2:] == ["measureimpedance", "saveimpedance"]
    assert h.fake.params["desiredimpedancefreqhertz"] == "1000"
    sites = {s.channel: s for s in reading.sites}
    assert len(sites) == 32  # every channel RHX has, filtered by the caller
    assert sites["A-003"].ohms == 2.2e6 and sites["A-000"].ohms == 1e5


async def test_rhx_left_running_is_stopped_to_measure(rig, tmp_path):  # noqa: F811
    h = await rig(params={"runmode": "Run"})
    await h.service.measure_impedance(str(tmp_path), "impedance_x")
    assert h.fake.params["runmode"] == "Stop"
    assert "measureimpedance" in h.fake.executed


async def test_rhx_recording_is_not_touched(rig, tmp_path):  # noqa: F811
    h = await rig(params={"runmode": "Record"})
    with pytest.raises(IntanNotReady, match="recording"):
        await h.service.measure_impedance(str(tmp_path), "impedance_x")
    assert "measureimpedance" not in h.fake.executed


async def test_a_file_rhx_never_wrote_is_said_not_parsed_as_empty(rig, tmp_path):  # noqa: F811
    h = await rig(saves_impedance=False)
    with pytest.raises(IntanNotReady, match="did not save"):
        await h.service.measure_impedance(str(tmp_path), "impedance_x")


async def test_a_stale_file_of_the_same_name_is_never_read(rig, tmp_path):  # noqa: F811
    (tmp_path / "impedance_x.csv").write_text("left from before\n")
    h = await rig(saves_impedance=False)
    with pytest.raises(IntanNotReady):
        await h.service.measure_impedance(str(tmp_path), "impedance_x")


# --- end to end ---------------------------------------------------------------


async def test_each_box_s_sites_are_kept_under_its_animal_and_compared(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001, F811
    session_id, cohort = await _recording_session(app, tmp_path / "Batch I")
    await _confirm_box_1(app, session_id, cohort)
    rat1 = next(a["id"] for a in cohort["animals"] if a["name"] == "rat1")
    box_1 = [{"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 3}]
    args = dict(sessionId=session_id, saveDirectory=str(tmp_path / "ephys"), boxes=box_1)

    first = (await dispatch(app, "intan.measureImpedance", **args))["measurements"]
    assert list(first) == [rat1]
    assert first[rat1]["previous"] is None
    current = first[rat1]["current"]
    assert current["box"] == 1 and current["frequencyHz"] == 1000.0
    assert sorted(current["sites"]) == ["A-000", "A-001", "A-002", "A-003"]  # the box's range only
    assert Path(current["file"]).is_file()

    rhx.impedances = {"A-002": (6.0e6, -20.0)}
    second = (await dispatch(app, "intan.measureImpedance", **args))["measurements"][rat1]
    assert second["previous"]["measuredAt"] == current["measuredAt"]
    assert second["current"]["sites"]["A-002"]["ohms"] == 6.0e6

    history = await dispatch(app, "intan.impedanceHistory", animalIds=[rat1, "nobody"])
    assert list(history["latest"]) == [rat1]
    assert history["latest"][rat1] == second


async def test_a_box_the_mapping_lacks_is_refused_before_rhx_measures(app, rhx: FakeRhx, tmp_path: Path) -> None:  # noqa: ANN001, F811
    session_id, cohort = await _recording_session(app, tmp_path / "Batch J")
    await _confirm_box_1(app, session_id, cohort)
    with pytest.raises(Refused) as refused:
        await dispatch(
            app, "intan.measureImpedance", sessionId=session_id,
            saveDirectory=str(tmp_path / "ephys"),
            boxes=[{"box": 3, "port": "A", "firstChannel": 16, "lastChannel": 31}],
        )
    assert refused.value.code == "SESSION_INVALID" and refused.value.detail == {"boxes": [3]}
    assert "measureimpedance" not in rhx.executed
