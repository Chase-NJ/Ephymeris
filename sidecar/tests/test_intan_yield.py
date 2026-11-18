"""Active-site yield (`RECORDING.md#active-site-yield`): each recorded run's
spike counts per site, counted live, kept with the run record, read back per
animal, and pruned with the run."""

from __future__ import annotations

import asyncio

from ephymeris_sidecar.intan.yield_store import RunSpikes, SpikeYieldStore
from ephymeris_sidecar.sessions.runner import ActiveRun, BoxConfig
from ephymeris_sidecar.tasks.start_command import build_start_command
from ephymeris_sidecar.intan.streams import FRAMES_PER_BLOCK, Spike, pack_spike
from tests.test_intan_service import FS, config, din_block, rig  # noqa: F401
from tests.test_session_lifecycle import db, recording_rig  # noqa: F401

# --- counted live -------------------------------------------------------------


async def test_a_run_s_counts_cover_every_site_the_box_records_and_how_long_the_stream_ran(rig, tmp_path):  # noqa: F811
    h = await rig()
    await h.service.configure("s1", config(tmp_path), "x")
    await h.service.start_recording()
    h.service.box_started(1, "R7")
    await asyncio.sleep(0)

    # Ten blocks: the parser believes a block once the next one's magic is in,
    # so nine are counted until a tenth's successor arrives.
    await h.fake.push_waveform(b"".join(din_block(f, {}) for f in range(0, 10 * FRAMES_PER_BLOCK, FRAMES_PER_BLOCK)))
    spikes = [Spike("A-003", 100, 1), Spike("A-003", 400, 1), Spike("A-003", 900, 1), Spike("A-020", 100, 1)]
    await h.fake.push_spikes(b"".join(pack_spike(s) for s in spikes))
    await h.until(lambda: h.service._samples_seen == 9 * FRAMES_PER_BLOCK)
    await h.until(lambda: h.service._runs[1].counts.get("A-003") == 3)

    counted = h.service.box_ended(1, "R7", "BF_END_SESSION received")
    assert counted is not None
    assert sorted(counted.counts) == [f"A-{n:03d}" for n in range(16)]  # box 1's range, silent sites included
    assert counted.counts["A-003"] == 3 and counted.counts["A-000"] == 0
    assert "A-020" not in counted.counts  # box 3's site
    assert counted.counted_seconds == round(9 * FRAMES_PER_BLOCK / FS, 3)
    assert counted.run_seconds >= 0
    assert counted.threshold == config(tmp_path)["threshold"]
    # Box 3 never started inside the recording: not counted, not a zero.
    assert h.service.box_ended(3, "R9", "end") is None


# --- kept with the run --------------------------------------------------------


async def test_the_lifecycle_keeps_a_recorded_run_s_counts_and_history_reads_them_per_animal(recording_rig, db) -> None:  # noqa: F811
    rig = recording_rig
    session = rig.session(recording=True)
    rig.intan.spikes = RunSpikes({"A-000": 30, "A-001": 0}, counted_seconds=60.0, run_seconds=61.0)
    config_ = BoxConfig(
        box=1, animal_id="C1-1", animal_name="remy1", sketch_path="/sk", sketch_name="sk",
        start_command=build_start_command(None, {}), config_metadata={}, profile=None,
    )
    run = ActiveRun(
        box=1, config=config_, run_id="r1", started_at="2026-10-10T10:00:00+00:00",
        address="/dev/fake1", session_id_label="P1_12", session_id=session.id,
    )
    await rig.lifecycle.animal_ended(run, "end")

    store = SpikeYieldStore(db)
    [kept] = store.history("C1-1", limit=10)
    assert (kept["runId"], kept["sessionId"], kept["box"]) == ("r1", session.id, 1)
    assert kept["counts"] == {"A-000": 30, "A-001": 0}
    assert (kept["countedSeconds"], kept["runSeconds"], kept["threshold"]) == (60.0, 61.0, None)
    assert store.history("C1-2", limit=10) == []

    # Pruned with its run: counts with no run mean nothing.
    rig.sessions.delete_runs(["r1"])
    with db.read() as q:
        assert q.execute("SELECT COUNT(*) FROM run_spike_counts").fetchone()[0] == 0


async def test_a_behavior_only_box_leaves_no_counts(recording_rig, db) -> None:  # noqa: F811
    rig = recording_rig
    session = rig.session(recording=True)
    rig.intan.spikes = None
    config_ = BoxConfig(
        box=2, animal_id="C1-2", animal_name="remy2", sketch_path="/sk", sketch_name="sk",
        start_command=build_start_command(None, {}), config_metadata={}, profile=None,
    )
    run = ActiveRun(
        box=2, config=config_, run_id="r2", started_at="2026-10-10T10:00:00+00:00",
        address="/dev/fake2", session_id_label="P1_12", session_id=session.id,
    )
    await rig.lifecycle.animal_ended(run, "end")
    assert SpikeYieldStore(db).history("C1-2", limit=10) == []


def test_history_is_the_most_recent_runs_oldest_first(db) -> None:  # noqa: F811
    from ephymeris_sidecar.cohorts.repository import CohortRepository
    from ephymeris_sidecar.sessions.models import SessionAnimalRun
    from ephymeris_sidecar.sessions.repository import SessionRepository

    cohorts, sessions = CohortRepository(db), SessionRepository(db)
    cohort = cohorts.create("C", "/tmp/c", animals=[{"id": "rat", "name": "rat", "boxNumber": 1}])
    prefix = sessions.create_prefix("P")
    store = SpikeYieldStore(db)
    for day in (1, 2, 3):
        s = sessions.create_session(cohort.id, prefix, str(day), f"2026-10-0{day}", f"/tmp/c/{day}")
        sessions.record_animal_run(SessionAnimalRun(
            id=f"r{day}", session_id=s.id, animal_id="rat", box_number=1, sketch_path="/sk",
            file_path=None, started_at=f"2026-10-0{day}T10:00:00+00:00", ended_at=None,
            stop_reason="end", profile_hash=None,
        ))
        store.add(f"r{day}", RunSpikes({"A-000": day}, counted_seconds=60.0, run_seconds=60.0))

    assert [r["runId"] for r in store.history("rat", limit=2)] == ["r2", "r3"]
