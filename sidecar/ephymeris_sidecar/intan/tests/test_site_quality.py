"""Each site's signal over a recorded run — `RECORDING.md#unit-like-sites`.

Measured from the snapshots RHX saved, in the same pass as the spike export:
the noise from each snapshot's lead-in, every spike's amplitude over it, and
the artifacts set aside. Kept per run, sent with the cohort's log, pruned with
the run. Nothing here judges a site; the webview does.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.intan import site_quality, sort_export
from ephymeris_sidecar.intan.quality_store import SiteQualityStore
from ephymeris_sidecar.intan.site_quality import SNR_EDGES, RunQuality, SiteQuality
from ephymeris_sidecar.intan.sort_export import SortExport, export_run, export_spikes
from ephymeris_sidecar.intan.yield_store import RunSpikes, SpikeYieldStore
from ephymeris_sidecar.logbook.service import LogbookService
from ephymeris_sidecar.protocol import validate_command_result
from ephymeris_sidecar.analytics.tests.test_analytics_service import HIT_1
from ephymeris_sidecar.analytics.tests.test_analytics_service import Rig as LogRig
from ephymeris_sidecar.sessions.tests.test_session_lifecycle import db, recording_rig  # noqa: F401
from ephymeris_sidecar.intan.tests.test_sort_export import RATE, cells, load, run_document, spike_file, write_run

NOISE_UV = 10.0
BIN = {edge: k for k, edge in enumerate(SNR_EDGES)}


def counts_of(uv: np.ndarray) -> list[int]:
    return (np.rint(uv / site_quality.UV_PER_COUNT) + site_quality.ADC_ZERO).astype(int).tolist()


def snapshot(rng: np.random.Generator, trough_uv: float, *, pre: int = 30, post: int = 30,
             noise_uv: float = NOISE_UV) -> list[int]:
    """Noise, with a spike whose trough is at the crossing: a short rise, the
    trough, and a slower positive rebound, as an extracellular spike has."""
    wave = rng.normal(0.0, noise_uv, pre + post)
    wave[pre - 1] += 0.4 * trough_uv
    wave[pre] = trough_uv
    wave[pre + 1] = 0.6 * trough_uv
    wave[pre + 8:pre + 14] -= 0.3 * trough_uv
    return counts_of(wave)


# --- the pieces ---------------------------------------------------------------


def test_the_noise_is_measured_from_the_lead_in_left_clear_of_the_spike() -> None:
    assert site_quality.lead_samples(30) == 18, "RHX's default 1 ms: 30 samples, less the 12 nearest the crossing"
    assert site_quality.lead_samples(24) == site_quality.MIN_LEAD_SAMPLES == 12
    assert site_quality.lead_samples(23) == 0 and site_quality.lead_samples(6) == 0
    assert site_quality.Gatherer.measurable(30, 30) and not site_quality.Gatherer.measurable(20, 40)


def test_the_robust_sd_is_the_noise_s_and_ignores_an_offset_and_outliers() -> None:
    rng = np.random.default_rng(7)
    levels = np.rint(rng.normal(0.0, NOISE_UV / site_quality.UV_PER_COUNT, 200_000)).astype(int)
    clean = np.bincount(levels + site_quality.ADC_ZERO, minlength=site_quality.ADC_LEVELS)
    assert site_quality.robust_sd(np, clean) == pytest.approx(NOISE_UV, rel=0.03)

    # Riding a slow artifact: offset, the spread unchanged.
    offset = np.bincount(levels + site_quality.ADC_ZERO + 400, minlength=site_quality.ADC_LEVELS)
    assert site_quality.robust_sd(np, offset) == pytest.approx(NOISE_UV, rel=0.03)

    # A tenth of the samples wildly off: a plain SD triples, the robust one barely moves.
    wild = clean.copy()
    wild[site_quality.ADC_ZERO + 2000] += 20_000
    assert site_quality.robust_sd(np, wild) == pytest.approx(NOISE_UV, rel=0.25)

    assert site_quality.robust_sd(np, np.zeros(site_quality.ADC_LEVELS, dtype=np.int64)) == 0.0


def test_spikes_on_half_the_fired_sites_at_once_are_coincident() -> None:
    reach = int(site_quality.COINCIDENT_S * RATE)  # 15 samples
    lone = [np.array([1000 * (k + 1)], dtype=np.int32) for k in range(8)]
    marks = site_quality.coincident(np, lone, RATE)
    assert not any(m.any() for m in marks), "eight sites, each alone"

    # Four of eight sites (half) within the window: all four are set aside.
    together = [np.array([50_000 + k], dtype=np.int32) for k in range(4)]
    stamps = [np.concatenate([lone[k], together[k]]) if k < 4 else lone[k] for k in range(8)]
    marks = site_quality.coincident(np, stamps, RATE)
    assert [m.tolist() for m in marks[:4]] == [[False, True]] * 4
    assert not any(m.any() for m in marks[4:])

    # Three of eight is not half; and just outside the window is not together.
    three = [np.array([50_000 + k], dtype=np.int32) if k < 3 else lone[k] for k in range(8)]
    assert not any(m.any() for m in site_quality.coincident(np, three, RATE))
    spread = [np.array([50_000 + k * (reach + 1)], dtype=np.int32) if k < 4 else lone[k] for k in range(8)]
    assert not any(m.any() for m in site_quality.coincident(np, spread, RATE))


def test_too_few_fired_sites_are_never_coincident() -> None:
    """Three sites firing together are the minimum of four short: a small
    implant's neurons are not thrown out for being its only ones."""
    stamps = [np.array([100, 5000], dtype=np.int32) for _ in range(3)]
    assert not any(m.any() for m in site_quality.coincident(np, stamps, RATE))


def test_spikes_are_binned_by_amplitude_over_noise() -> None:
    amplitude = np.array([39.0, 40.0, 55.0, 79.9, 80.0, 240.0, 1000.0])
    counts = site_quality.snr_counts(np, amplitude, 10.0)
    assert len(counts) == len(SNR_EDGES) and sum(counts) == 6, "3.9 SDs is under the first edge: in no bin"
    assert counts[BIN[4.0]] == 1 and counts[BIN[5.0]] == 1 and counts[BIN[7.0]] == 1
    assert counts[BIN[8.0]] == 1 and counts[BIN[24.0]] == 2, "an edge is its bin's own; the last bin is open-ended"


def test_a_site_whose_noise_could_not_be_measured_has_counts_of_nothing() -> None:
    site = site_quality.measure_site(np, "A-000", np.array([100.0, 200.0]), np.array([False, True]), 0.0)
    assert (site.spikes, site.artifacts, site.noise_uv, site.snr_counts) == (2, 1, None, None)
    assert site.to_json() == {"channel": "A-000", "spikes": 2, "artifacts": 1, "noiseUv": None, "snrCounts": None}


# --- through the export, on a recording made up for it --------------------------


NAMES = [f"A-{n:03d}" for n in range(7)] + ["C-000"]
ANIMAL = NAMES[:7]
CLEAN, NOISY = 200, 200
SECONDS = 600


def recording(tmp_path: Path, *, pre: int = 30, post: int = 30) -> Path:
    """Seven sites of one animal over ten minutes:

    A-000  a clean unit, 150 µV on 10 µV of noise; one spike RHX flagged
    A-001  noise crossings, 45 µV; one 1200 µV swing
    A-002…A-005  a few noise crossings each
    A-006  silent
    and ten moments where A-000…A-005 all cross together (chewing).
    C-000 is another animal's, and holds the recording's first and last spike.
    """
    rng = np.random.default_rng(11)
    records = [("C-000", 0, 1, snapshot(rng, -80.0, pre=pre, post=post)),
               ("C-000", int(SECONDS * RATE), 1, snapshot(rng, -80.0, pre=pre, post=post))]
    # Each site's own spikes sit on its own offset of a coarse grid: never together.
    for i in range(CLEAN):
        records.append(("A-000", 100_000 + i * 6000, 1, snapshot(rng, -150.0, pre=pre, post=post)))
    for i in range(NOISY):
        records.append(("A-001", 100_000 + i * 6000 + 600, 1, snapshot(rng, -45.0, pre=pre, post=post)))
    for k in (2, 3, 4, 5):
        for i in range(20):
            records.append((f"A-{k:03d}", 100_000 + i * 6000 + 600 * k, 1, snapshot(rng, -45.0, pre=pre, post=post)))
    records.append(("A-000", 2_000_000 + 300, 128, snapshot(rng, -150.0, pre=pre, post=post)))
    records.append(("A-001", 2_000_000 + 4300, 1, snapshot(rng, -1200.0, pre=pre, post=post)))
    for i in range(10):
        for k in range(6):
            records.append((f"A-{k:03d}", 5_000_000 + i * 30_000 + k, 1, snapshot(rng, -300.0, pre=pre, post=post)))
    records.sort(key=lambda r: r[1])
    return spike_file(tmp_path / "rhx" / "spike.dat", records, names=NAMES, pre=pre, post=post)


def test_the_export_measures_every_site_of_the_animal(tmp_path: Path) -> None:
    result = export_spikes(recording(tmp_path), tmp_path / "sort" / "out.mat", ANIMAL)
    assert result.status == "written"
    quality = result.quality
    assert quality is not None and quality.edges == SNR_EDGES
    assert quality.recorded_seconds == SECONDS, "the file's first spike to its last, any channel"
    assert [s.channel for s in quality.sites] == ANIMAL, "RHX's order, the silent site included, C-000 not"
    by = {s.channel: s for s in quality.sites}

    clean = by["A-000"]
    assert clean.spikes == CLEAN + 10 + 1 and clean.artifacts == 10 + 1, "ten coincident, one RHX flagged"
    assert clean.noise_uv == pytest.approx(NOISE_UV, rel=0.1)
    assert sum(clean.snr_counts) == CLEAN, "artifacts are in no bin"
    assert sum(clean.snr_counts[BIN[12.0]:]) == CLEAN, "150 µV on 10 µV of noise: 15 SDs"

    noisy = by["A-001"]
    assert noisy.spikes == NOISY + 10 + 1 and noisy.artifacts == 10 + 1, "ten coincident, one past the cap"
    assert noisy.noise_uv == pytest.approx(NOISE_UV, rel=0.1)
    assert sum(noisy.snr_counts) == NOISY and sum(noisy.snr_counts[BIN[6.0]:]) == 0
    assert noisy.snr_counts[BIN[4.0]] == NOISY, "45 µV crossings: 4.5 SDs, just over the threshold"

    for name in ("A-002", "A-003", "A-004", "A-005"):
        assert (by[name].spikes, by[name].artifacts) == (30, 10)
    silent = by["A-006"]
    assert (silent.spikes, silent.artifacts, silent.noise_uv) == (0, 0, None)
    assert silent.snr_counts == (0,) * len(SNR_EDGES), "no spikes is a count of none, not an unknown"


def test_the_measurement_changes_nothing_in_the_file(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    spikes = recording(tmp_path)
    with_it, without = tmp_path / "with.mat", tmp_path / "without.mat"
    assert export_spikes(spikes, with_it, ANIMAL, chunk_records=97).quality is not None
    monkeypatch.setattr(site_quality.Gatherer, "measurable", staticmethod(lambda _before, _after: False))
    bare = export_spikes(spikes, without, ANIMAL)
    assert bare.status == "written" and bare.quality is None
    a, b = load(with_it), load(without)
    assert [str(c[0]) for c in cells(a, "unique_ch")] == [str(c[0]) for c in cells(b, "unique_ch")]
    for name in ("spiketimes", "spikewaves"):
        for x, y in zip(cells(a, name), cells(b, name), strict=True):
            assert np.array_equal(x, y)


def test_reading_in_small_chunks_measures_the_same(tmp_path: Path) -> None:
    spikes = recording(tmp_path)
    whole = export_spikes(spikes, tmp_path / "whole.mat", ANIMAL).quality
    chunked = export_spikes(spikes, tmp_path / "chunked.mat", ANIMAL, chunk_records=53).quality
    assert whole == chunked


def test_a_snapshot_with_too_short_a_lead_in_is_exported_but_not_measured(tmp_path: Path) -> None:
    """20 samples before a detection leave 8 clear of the spike, under the 12
    the noise needs: the file is written as ever, with no measurements."""
    short = export_spikes(recording(tmp_path / "short", pre=20, post=40), tmp_path / "short.mat", ANIMAL)
    assert short.status == "written" and short.quality is None
    enough = export_spikes(recording(tmp_path / "enough", pre=24, post=36), tmp_path / "enough.mat", ANIMAL)
    assert enough.quality is not None
    assert {s.channel: s for s in enough.quality.sites}["A-000"].noise_uv == pytest.approx(NOISE_UV, rel=0.15)


def test_a_measurement_that_fails_costs_only_itself(tmp_path: Path, monkeypatch, caplog) -> None:  # noqa: ANN001
    def broken(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("no")

    monkeypatch.setattr(site_quality.Gatherer, "add", broken)
    result = export_spikes(recording(tmp_path), tmp_path / "out.mat", ANIMAL)
    assert result.status == "written" and result.path.is_file() and result.quality is None
    assert "site signal not measured" in caplog.text


def test_nothing_written_means_nothing_measured(tmp_path: Path) -> None:
    spikes = recording(tmp_path)
    assert export_spikes(spikes, tmp_path / "out.mat", ["B-000"]).quality is None
    assert export_spikes(tmp_path / "nowhere" / "spike.dat", tmp_path / "out.mat", ANIMAL).quality is None


def test_a_run_s_export_says_which_run_it_is_of(tmp_path: Path) -> None:
    folder = tmp_path / "ephys" / "rec_260417_095743"
    folder.mkdir(parents=True)
    recording(tmp_path).replace(folder / "spike.dat")
    session = tmp_path / "cohort" / "P" / "P_1_2026-04-17"
    run = write_run(session, run_document(folder))

    result = export_run(run)
    assert result.status == "written" and result.source == run
    assert [s.channel for s in result.quality.sites] == ["A-000", "A-001", "A-002"], "the run's own channels"
    # Whatever came of it, a result names its run.
    plain = write_run(session, run_document(folder, recorded=False), "remy2_P_1_2026-04-17_095744")
    assert export_run(plain).source == plain
    [only] = sort_export.export_runs([run])
    assert only.source == run


# --- kept with the run, sent with the log ---------------------------------------


QUALITY = RunQuality(
    600.0,
    (
        SiteQuality("A-000", 211, 11, 10.14, (0, 0, 0, 0, 0, 0, 150, 50, 0)),
        SiteQuality("A-001", 0, 0, None, (0,) * len(SNR_EDGES)),
    ),
)


@pytest.fixture
def log_rig(db: Database, tmp_path: Path) -> LogRig:  # noqa: F811
    r = LogRig(db, tmp_path)
    r.write_sketch()
    return r


@pytest.fixture
def logbook(log_rig: LogRig) -> LogbookService:
    async def broadcast(message: dict) -> None:
        log_rig.events.append(message)

    return LogbookService(
        db=log_rig.db, cohorts=log_rig.cohorts, sessions=log_rig.sessions,
        profiles=log_rig.profiles, archive=log_rig.archive, broadcast=broadcast,
    )


async def test_a_cohort_s_log_carries_each_recorded_run_s_signal(log_rig: LogRig, logbook: LogbookService) -> None:
    sid = log_rig.add_session("1", "2026-07-22")
    both = log_rig.add_run(sid, "a1", HIT_1, run_id="both")
    counted = log_rig.add_run(sid, "a2", HIT_1, run_id="counted-only")
    later = log_rig.add_session("2", "2026-07-23")
    measured = log_rig.add_run(later, "a1", HIT_1, run_id="measured-only")
    log_rig.add_run(later, "a2", HIT_1, run_id="behavior-only")

    threshold = {"mode": "rms", "multiple": -4.0}
    counts, quality = SpikeYieldStore(log_rig.db), SiteQualityStore(log_rig.db)
    # A-010 before A-002 as stored, and one site the measurement never saw.
    counts.add(both, RunSpikes({"A-010": 4, "A-001": 0, "A-000": 6300}, 598.0, 600.0, threshold))
    quality.add(both, QUALITY)
    counts.add(counted, RunSpikes({"C-000": 12}, 60.0, 61.0))
    quality.add(measured, QUALITY)

    cohort = await logbook.cohort(log_rig.cohort.id)
    assert validate_command_result("logbook.cohort", cohort) == []
    signals = {s["runId"]: s for s in cohort["signals"]}
    assert sorted(signals) == ["both", "counted-only", "measured-only"], "a behavior-only run has no signal"

    run = signals["both"]
    assert (run["sessionId"], run["animalId"], run["box"]) == (sid, "a1", 1)
    assert (run["countedSeconds"], run["runSeconds"], run["threshold"]) == (598.0, 600.0, threshold)
    assert run["recordedSeconds"] == 600.0 and run["snrEdges"] == list(SNR_EDGES)
    assert [s["channel"] for s in run["sites"]] == ["A-000", "A-001", "A-010"], "RHX's order"
    assert run["sites"][0] == {
        "channel": "A-000", "crossings": 6300, "spikes": 211, "artifacts": 11, "noiseUv": 10.14,
        "snrCounts": [0, 0, 0, 0, 0, 0, 150, 50, 0],
    }
    assert run["sites"][1]["snrCounts"] == [0] * len(SNR_EDGES) and run["sites"][1]["noiseUv"] is None
    assert run["sites"][2] == {
        "channel": "A-010", "crossings": 4, "spikes": None, "artifacts": None, "noiseUv": None, "snrCounts": None,
    }

    # What a source lacks is null, never zero.
    only_counted = signals["counted-only"]
    assert only_counted["recordedSeconds"] is None and only_counted["countedSeconds"] == 60.0
    assert only_counted["sites"] == [
        {"channel": "C-000", "crossings": 12, "spikes": None, "artifacts": None, "noiseUv": None, "snrCounts": None}
    ]
    only_measured = signals["measured-only"]
    assert (only_measured["countedSeconds"], only_measured["runSeconds"], only_measured["threshold"]) == (None,) * 3
    assert [s["crossings"] for s in only_measured["sites"]] == [None, None]
    assert only_measured["sessionId"] == later

    # Another cohort's runs are not this one's.
    other = log_rig.cohorts.create("Batch B", str(log_rig.root.parent / "Batch B"))
    assert (await logbook.cohort(other.id))["signals"] == []


def test_signals_come_oldest_first_and_a_second_measurement_replaces_the_first(db: Database) -> None:  # noqa: F811
    from ephymeris_sidecar.cohorts.repository import CohortRepository
    from ephymeris_sidecar.sessions.models import SessionAnimalRun
    from ephymeris_sidecar.sessions.repository import SessionRepository

    cohorts, sessions = CohortRepository(db), SessionRepository(db)
    cohort = cohorts.create("C", "/tmp/c", animals=[{"id": "rat", "name": "rat", "boxNumber": 1}])
    prefix = sessions.create_prefix("P")
    store = SiteQualityStore(db)
    for day in (3, 1, 2):
        s = sessions.create_session(cohort.id, prefix, str(day), f"2026-10-0{day}", f"/tmp/c/{day}")
        sessions.record_animal_run(SessionAnimalRun(
            id=f"r{day}", session_id=s.id, animal_id="rat", box_number=1, sketch_path="/sk",
            file_path=None, started_at=f"2026-10-0{day}T10:00:00+00:00", ended_at=None,
            stop_reason="end", profile_hash=None,
        ))
        store.add(f"r{day}", QUALITY)
    assert [s["runId"] for s in store.cohort_signals(cohort.id)] == ["r1", "r2", "r3"]

    store.add("r2", RunQuality(30.0, (SiteQuality("A-000", 1, 0, 9.0, (1,) + (0,) * 8),)))
    again = {s["runId"]: s for s in store.cohort_signals(cohort.id)}["r2"]
    assert again["recordedSeconds"] == 30.0 and [s["spikes"] for s in again["sites"]] == [1]

    # Pruned with its run: measurements with no run mean nothing.
    sessions.delete_runs(["r1", "r2"])
    assert [s["runId"] for s in store.cohort_signals(cohort.id)] == ["r3"]
    with db.read() as q:
        assert q.execute("SELECT COUNT(*) FROM run_site_quality").fetchone()[0] == 1


# --- the after-stop pass keeps them (RECORDING.md#alignment-at-session-end) -------


class Announced:
    def __init__(self) -> None:
        self.refreshed: list[tuple[str, list[str] | None]] = []

    async def refresh(self, cohort_id: str, session_ids: list[str] | None = None) -> None:
        self.refreshed.append((cohort_id, session_ids))


def recorded_runs(rig, session) -> list[str]:  # noqa: ANN001
    """Two finished runs of the session with files, as `animal_ended` records
    them; their ids, in order."""
    from ephymeris_sidecar.sessions.models import SessionAnimalRun

    ids = []
    for box, animal in enumerate(rig.cohorts.get(session.cohort_id).animals, start=1):
        run_id = f"run-{box}"
        rig.sessions.record_animal_run(SessionAnimalRun(
            id=run_id, session_id=session.id, animal_id=animal.id, box_number=box, sketch_path="/sk",
            file_path=str(rig.root / "s" / "behavior.json" / f"{animal.name}.json"),
            started_at=f"2026-10-10T10:00:0{box}+00:00", ended_at=None, stop_reason="end", profile_hash=None,
        ))
        ids.append(run_id)
    return ids


async def test_a_stopped_recording_s_measurements_are_kept_under_their_runs_and_announced(
    recording_rig, db  # noqa: ANN001, F811
) -> None:
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    rig.lifecycle._logbook = announced = Announced()
    gate = threading.Event()

    def export(files: list[str], _recording: str) -> list[SortExport]:
        gate.wait(5)
        # The first run was measured; the second's recording saved no snapshots;
        # and one result is of a file that is no run of this session.
        return [
            SortExport("written", None, Path("x.mat"), 1, 211, QUALITY, Path(files[0])),
            SortExport("skipped", "no snapshots", source=Path(files[1])),
            SortExport("written", None, Path("y.mat"), 1, 1, QUALITY, Path("/elsewhere/stray.json")),
        ]

    rig.lifecycle.export_spikes = export
    session = rig.session(recording=True)
    await rig.run_round(session)
    first, _second = recorded_runs(rig, session)
    ended = await rig.lifecycle.end(session.id)
    assert ended.status == "completed", "the end waited for none of it"
    assert SiteQualityStore(db).cohort_signals(session.cohort_id) == []
    before = len(announced.refreshed)
    gate.set()
    await rig.lifecycle.exports_settled()

    [kept] = SiteQualityStore(db).cohort_signals(session.cohort_id)
    assert kept["runId"] == first and kept["recordedSeconds"] == 600.0
    assert [s["snrCounts"] for s in kept["sites"]][0] == [0, 0, 0, 0, 0, 0, 150, 50, 0]
    assert announced.refreshed[before:] == [(session.cohort_id, [session.id])], "an open Logbook refetches, once"


@pytest.mark.parametrize("returned", [None, "nothing", [object()], [SortExport("failed", "disk on fire")]])
async def test_an_export_with_nothing_measured_keeps_nothing_and_costs_nothing(
    recording_rig, db, returned  # noqa: ANN001, F811
) -> None:
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    rig.lifecycle._logbook = announced = Announced()
    rig.lifecycle.export_spikes = lambda _files, _recording: returned
    session = rig.session(recording=True)
    await rig.run_round(session)
    recorded_runs(rig, session)
    ended = await rig.lifecycle.end(session.id)
    before = len(announced.refreshed)
    await rig.lifecycle.exports_settled()
    assert ended.status == "completed"
    assert SiteQualityStore(db).cohort_signals(session.cohort_id) == []
    assert len(announced.refreshed) == before, "nothing new to show"


async def test_measurements_that_cannot_be_kept_cost_the_session_nothing(
    recording_rig, db, monkeypatch, caplog  # noqa: ANN001, F811
) -> None:
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}

    def full_disk(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("database or disk is full")

    monkeypatch.setattr(SiteQualityStore, "add", full_disk)
    rig.lifecycle.export_spikes = lambda files, _recording: [
        SortExport("written", None, Path("x.mat"), 1, 211, QUALITY, Path(files[0]))
    ]
    session = rig.session(recording=True)
    await rig.run_round(session)
    recorded_runs(rig, session)
    ended = await rig.lifecycle.end(session.id)
    await rig.lifecycle.exports_settled()
    assert ended.status == "completed"
    assert "couldn't keep the site measurements" in caplog.text
    assert SiteQualityStore(db).cohort_signals(session.cohort_id) == []
