"""The offline named-event PSTH (`RECORDING.md#event-psth`) against a synthetic
RHX recording written byte for byte in RHX's own per-signal-type layout
(`FilePerSignalTypeSaveManager`), with events at known times: a mistake the
readers share with these writers would still have to survive the golden
header test, which spells the bytes out by hand."""

from __future__ import annotations

import json
import random
import struct
from array import array
from pathlib import Path

import pytest

from ephymeris_sidecar.intan import events as ev
from ephymeris_sidecar.intan import offline, rhx_files
from ephymeris_sidecar.intan.analysis import EdgeMatcher

FS = 30000
ODOR, POKE = 101, 222
NAMES = {ODOR: "ODOR_1_ON", POKE: "POKE_IN"}


# --- writing a recording as RHX does --------------------------------------------


def spike_file(path: Path, spikes: list[tuple[str, int]], *, snapshot: tuple[int, int] = (0, 0), names=("A-016", "A-017")) -> None:
    before, after = snapshot
    head = struct.pack("<IH", rhx_files.SPIKE_FILE_MAGIC, 1)
    head += b"rec_260901_090000\x00" + ",".join(names).encode() + b"\x00" + ",".join(names).encode() + b"\x00"
    head += struct.pack("<dII", float(FS), before, after)
    body = b"".join(
        struct.pack("<5siB", name.encode(), stamp, 1) + b"\x00\x00" * (before + after)
        for name, stamp in sorted(spikes, key=lambda s: s[1])
    )
    path.write_bytes(head + body)


def recording(folder: Path, seconds: int, high: dict[int, int], spikes: list[tuple[str, int]], *, first: int = 0) -> None:
    """`high`: sample -> digital word; held for 15 samples (a 500 us pulse)."""
    folder.mkdir(parents=True)
    n = seconds * FS
    (folder / "time.dat").write_bytes(array("i", range(first, first + n)).tobytes())
    words = array("H", bytes(2 * n))
    for sample, word in high.items():
        for k in range(sample - first, min(n, sample - first + 15)):
            words[k] |= word
    (folder / "digitalin.dat").write_bytes(words.tobytes())
    spike_file(folder / "spike.dat", spikes)


def run_document(tmp_path: Path, strobes: list[tuple[int, int]], *, din: int = 5, sync: str | None = None) -> Path:
    session = tmp_path / "data" / "2O-Bdisc_1_2026-09-01"
    (session / "behavior.json").mkdir(parents=True)
    document = {
        "rat": "R7",
        "ts_data": [[c, ms] for c, ms in strobes],
        "intan_recording": "rec_260901_090000",
        "intan_path": str(tmp_path / "ephys"),
        "intan_digital_in": din,
        "intan_port": "A",
        "intan_channels": "A-016:A-017",
        "intan_sample_rate": FS,
    }
    if sync:
        document["sync"] = sync
    path = session / "behavior.json" / "R7_2O-Bdisc_1_2026-09-01_090001.json"
    path.write_text(json.dumps(document))
    return path


def odor_session(tmp_path: Path, *, trials: int = 30, twitches: int = 0, drop: set[int] | None = None):
    """An odor onset every second, a poke 300 ms after it; box on DIN 5. A-016
    fires 20 ms after every onset; A-017 fires at random. The recording starts
    2 s before the board's clock, which started at 1000 ms."""
    origin = 2 * FS  # where the board's ms 0 lands on the recording
    sample_of = lambda ms: origin + ms * FS // 1000  # noqa: E731
    strobes, high, spikes = [], {}, []
    for k in range(trials):
        onset = 1000 + 1000 * k
        strobes += [(ODOR, onset), (POKE, onset + 300)]
        for ms in (onset, onset + 300):
            if not (drop and ms in drop):
                high[sample_of(ms)] = 1 << 4
        spikes.append(("A-016", sample_of(onset) + 600))
    rnd = random.Random(1)
    spikes += [("A-017", rnd.randrange(origin, sample_of(1000 * (trials + 1)))) for _ in range(trials * 3)]
    for t in range(twitches):  # the line twitching through a reset, before START
        high[FS // 2 + t * 900] = 1 << 4
    # Another box's input toggling must never be read as this box's.
    for s in range(0, (trials + 3) * FS, FS // 3):
        high[s] = high.get(s, 0) | (1 << 1)
    recording(tmp_path / "ephys" / "rec_260901_090000", trials + 3, high, spikes)
    return run_document(tmp_path, strobes), sample_of


# --- the files ------------------------------------------------------------------


def test_spike_header_spelled_out_byte_by_byte():
    data = (
        bytes.fromhex("4b47f818")  # magic 0x18f8474b, little-endian
        + b"\x01\x00"  # version 1
        + b"rec\x00" + b"A-000,A-001\x00" + b"tip,A-001\x00"
        + struct.pack("<d", 30000.0)
        + struct.pack("<II", 30, 60)  # snapshot: 1 ms before, 2 ms after
    )
    header = rhx_files.parse_spike_header(data)
    assert header.native_names == ("A-000", "A-001")
    assert header.sample_rate == 30000.0
    assert header.snapshot_samples == 90 and header.record_bytes == 10 + 180
    assert header.data_offset == len(data)
    with pytest.raises(rhx_files.RhxFileError):
        rhx_files.parse_spike_header(b"\x00" * 40)


def test_spike_records_with_snapshots_and_a_partial_last_one(tmp_path):
    path = tmp_path / "spike.dat"
    spike_file(path, [("A-016", 100), ("A-017", 150), ("A-016", 300)], snapshot=(30, 60))
    with path.open("ab") as handle:
        handle.write(b"A-016\x01\x02")  # RHX mid-write
    header, spikes = rhx_files.read_spikes(path)
    assert header.snapshot_samples == 90
    assert {c: list(s) for c, s in spikes.items()} == {"A-016": [100, 300], "A-017": [150]}
    _, only = rhx_files.read_spikes(path, {"A-017"})
    assert list(only) == ["A-017"]


def test_rising_edges_of_one_input_across_chunks(tmp_path, monkeypatch):
    monkeypatch.setattr(rhx_files, "CHUNK_SAMPLES", 1000)  # edges straddle chunk joins
    folder = tmp_path / "rec"
    high = {7000: 1 << 4, 7999: 1 << 4, 9500: 1 << 4, 8700: 1 << 1}
    recording(folder, 1, high, [], first=7000)
    # Sample 0 is high when the file opens: no edge. 999 rises across a chunk join.
    assert rhx_files.rising_edges(folder, 5) == [7999, 9500]
    assert rhx_files.rising_edges(folder, 2) == [8700]


# --- aligning -------------------------------------------------------------------


def test_a_whole_session_aligns_however_many_strobes_and_leading_twitches():
    """More strobes than `MAX_PENDING` and more twitches than the look-ahead:
    fed all at once, the matcher would give up on most of them."""
    strobes = [(ODOR, 1000 + 250 * k) for k in range(5 * EdgeMatcher.MAX_PENDING)]
    twitches = [100 + 50 * k for k in range(3 * ev.LOOK_AHEAD)]
    edges = twitches + [90_000 + ms * 30 for _, ms in strobes]
    aligned = ev.align(strobes, edges, FS, tick_pulsed=False)
    assert (aligned.matched, aligned.missed, aligned.stray) == (len(strobes), 0, len(twitches))
    assert [e.sample for e in aligned.events] == edges[len(twitches):]


def test_a_missing_pulse_costs_its_one_event():
    strobes = [(ODOR, 1000 * k) for k in range(1, 20)]
    edges = [ms * 30 for _, ms in strobes if ms != 7000]
    aligned = ev.align(strobes, edges, FS, tick_pulsed=False)
    assert (aligned.matched, aligned.missed) == (18, 1)
    assert next(e for e in aligned.events if e.ms == 7000).sample is None


def test_an_event_belongs_to_the_last_trial_that_opened_before_it():
    starts = [ev.TrialStart(1000, "Odor 1", "correct"), ev.TrialStart(5000, "Odor 2", "wrong")]
    assert [ev.trial_of(starts, ms) for ms in (500, 1000, 4999, 9000)] == [None, 0, 0, 1]


# --- end to end -----------------------------------------------------------------


def test_a_session_s_events_are_placed_and_its_responsive_site_found(tmp_path):
    run_path, sample_of = odor_session(tmp_path, twitches=4)
    loaded = offline.load_run(run_path, NAMES.get)
    assert (loaded.alignment.matched, loaded.alignment.missed, loaded.alignment.stray) == (60, 0, 4)

    view = offline.psth_view(loaded, ODOR, pre_ms=100, post_ms=200, bin_ms=10, split="none", raster_channel="a-016")
    assert [e["name"] for e in view["events"]] == ["ODOR_1_ON", "POKE_IN"]
    assert view["groups"] == [{"label": "all", "trials": 30}]
    by_site = {s["channel"]: s for s in view["sites"]}
    tip = by_site["A-016"]
    assert tip["counts"][0][12] == 30  # +20 ms: bin (100 + 20) / 10
    assert sum(tip["counts"][0]) == 30
    assert tip["responsive"] == "up"
    assert by_site["A-017"]["responsive"] == "none"
    assert view["rasters"] == [[[20.0]] * 30]

    # Written once beside the session, for the lab's own scripts.
    events_file = Path(view["eventsFile"])
    assert events_file == run_path.parent.parent / "events" / f"{run_path.stem}.events.json"
    written = json.loads(events_file.read_text())
    first = written["events"][0]
    assert (first["name"], first["ms"], first["sample"]) == ("ODOR_1_ON", 1000, sample_of(1000))
    assert events_file.with_name(f"{run_path.stem}.events.mat").is_file()


def test_split_by_outcome_puts_each_event_under_its_trial(tmp_path):
    run_path, _ = odor_session(tmp_path)
    loaded = offline.load_run(run_path, NAMES.get)
    loaded.trials = [ev.TrialStart(1000 + 1000 * k, "Odor 1", "correct" if k % 3 else "wrong") for k in range(30)]
    loaded.event_trials = [ev.trial_of(loaded.trials, e.ms) for e in loaded.alignment.events]
    view = offline.psth_view(loaded, ODOR, pre_ms=100, post_ms=200, bin_ms=10, split="outcome", raster_channel=None)
    assert view["groups"] == [{"label": "correct", "trials": 20}, {"label": "wrong", "trials": 10}]


def test_a_spine_run_s_trials_are_on_the_strobes_own_clock():
    """The board's clock restarts at START, and a replay's trial times are
    that clock: a trial opens at the ms of a strobe of the run, never shifted."""
    from tests.fixtures import spine as fixture

    fixture.install()
    try:
        from tests.test_spine_analytics import recorded_document

        document = recorded_document()
        strobes = offline._strobes(document)
        starts = offline._trial_starts(document, strobes)
        assert starts and {s.ms for s in starts} <= {ms for _, ms in strobes}
    finally:
        fixture.uninstall()


def test_a_run_that_cannot_be_read_says_why(tmp_path):
    run_path, _ = odor_session(tmp_path)
    (tmp_path / "ephys" / "rec_260901_090000" / "spike.dat").unlink()  # as a Traditional .rhd would leave it
    with pytest.raises(offline.NotRecorded, match="spike.dat"):
        offline.load_run(run_path)
    behavior = tmp_path / "plain.json"
    behavior.write_text(json.dumps({"ts_data": [[ODOR, 1000]]}))
    with pytest.raises(offline.NotRecorded, match="not recorded"):
        offline.load_run(behavior)


def test_a_loaded_run_is_kept_until_a_file_changes(tmp_path):
    run_path, _ = odor_session(tmp_path)
    runs = offline.OfflineRuns(NAMES.get)
    first = runs.get(str(run_path))
    assert runs.get(str(run_path)) is first
    spike = tmp_path / "ephys" / "rec_260901_090000" / "spike.dat"
    spike.write_bytes(spike.read_bytes())  # rewritten: a new time
    import os

    os.utime(spike, ns=(spike.stat().st_atime_ns, spike.stat().st_mtime_ns + 10_000_000))
    assert runs.get(str(run_path)) is not first


# --- over the wire ---------------------------------------------------------------


async def test_the_wire_finds_a_session_s_recorded_runs_and_serves_their_psth(tmp_path):
    from ephymeris_sidecar.protocol import validate
    from ephymeris_sidecar.sessions.models import SessionAnimalRun
    from tests.live_sidecar import Refused, animal
    from tests.test_utility import FakeTool
    from tests.wire import dispatch, running_app

    run_path, _ = odor_session(tmp_path)
    plain = run_path.with_name("R8_2O-Bdisc_1_2026-09-01_090002.json")
    plain.write_text(json.dumps({"rat": "R8", "ts_data": [[ODOR, 1000]]}))
    async with running_app(tmp_path / "app", tool=FakeTool()) as app:
        cohort = (await dispatch(
            app, "cohorts.create", name="Batch", dataFolder=str(tmp_path / "data"),
            animals=[animal("R7", box=1), animal("R8", box=2)],
        ))["cohort"]
        prefix = (await dispatch(app, "prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
        session = (await dispatch(
            app, "sessions.create", cohortId=cohort["id"], prefixId=prefix, sessionNumber="1", recording=True,
        ))["session"]
        for run_id, animal_id, box, path in (("r7", "a-R7", 1, run_path), ("r8", "a-R8", 2, plain)):
            app.sessions.record_animal_run(SessionAnimalRun(
                id=run_id, session_id=session["id"], animal_id=animal_id, box_number=box, sketch_path="/sk",
                file_path=str(path), started_at="2026-09-01T09:00:01+00:00", ended_at=None,
                stop_reason="end", profile_hash=None,
            ))

        assert (await dispatch(app, "intan.recordedRuns", sessionId=session["id"]))["runIds"] == ["r7"]
        view = await dispatch(
            app, "intan.eventPsth", runId="r7", code=ODOR, preMs=100, postMs=200, binMs=10, split="none",
        )
        assert validate(("ref", "EventPsth"), view) == []
        assert view["sync"]["matched"] == 60
        assert next(s for s in view["sites"] if s["channel"] == "A-016")["responsive"] == "up"

        with pytest.raises(Refused) as refused:
            await dispatch(app, "intan.eventPsth", runId="r8", preMs=100, postMs=200, binMs=10, split="none")
        assert refused.value.code == "RECORDING_UNREADABLE"
        assert "not recorded" in refused.value.message
