"""Alignment at session end — `RECORDING.md#alignment-at-session-end`.

Once RHX has closed its files, each recorded run is aligned without anyone
opening Analytics: its `recording.sync` gets the counts, its trial table's
`*_s` columns each event's time on the recording's clock, and its events file
is written. All against a synthetic recording in RHX's own layout
(`intan/tests/test_intan_event_psth.py`); no real run's strobes exist to test with.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import scipy.io

from ephymeris_sidecar.analytics.archive import RigInUse
from ephymeris_sidecar.intan import alignment, offline
from ephymeris_sidecar.sessions import run_document as rd
from ephymeris_sidecar.sessions.writer import AnimalWriter
from ephymeris_sidecar.analytics.tests import test_grammar2 as g2
from tests.fixtures.recorded import rig  # noqa: F401 - a fixture
from ephymeris_sidecar.intan.tests.test_intan_event_psth import FS, recording

RECORDING = "rec_260901_090000"
ORIGIN = 2 * FS   # where the board's ms 0 lands on the recording
STEP_MS = 100     # one strobe every 100 ms, from 1000 ms


def sample_of(ms: int) -> int:
    return ORIGIN + ms * FS // 1000


def strobes() -> list[tuple[int, int]]:
    """Every reference sequence of `test_grammar2`, as the board would send it."""
    return [(g2.code(name), 1000 + STEP_MS * i) for i, name in enumerate(g2.names_of(g2.EVERY))]


def record(tmp_path: Path, *, drop: set[int] = frozenset(), twitch: bool = True) -> None:
    """RHX's files for that run on digital input 5: a pulse per strobe, but
    for the board times in `drop`, after a start-up twitch of the line."""
    high = {sample_of(ms): 1 << 4 for _, ms in strobes() if ms not in drop}
    if twitch:
        high[131] = 1 << 4
    seconds = (strobes()[-1][1] // 1000) + 4
    recording(tmp_path / "ephys" / RECORDING, seconds, high, [])


def ticked() -> list[tuple[int, int]]:
    """The same run from a board that sends a tick's strobes together: each
    trial's three header codes share one millisecond."""
    out: list[tuple[int, int]] = []
    ms = 1000 - STEP_MS
    for name in g2.names_of(g2.EVERY):
        if not name.startswith(("TRIAL_GO_", "TRIAL_NO_GO", "TRIAL_TYPE_")):
            ms += STEP_MS
        out.append((g2.code(name), ms))
    return out


def fields(tmp_path: Path, recorded: bool = True, **more) -> dict:  # noqa: ANN003
    core = {"rat": "remy1", "sketch": "GRGL", "stream": 2, "interp": 1, **more}
    if recorded:
        core |= {"intan_recording": RECORDING, "intan_path": str(tmp_path / "ephys"), "intan_digital_in": 5,
                 "intan_port": "A", "intan_channels": "A-016:A-017", "intan_sample_rate": FS,
                 "implant": None,
                 "channels": [{"native": n, "device_channel": k, "target": "", "x_um": None, "y_um": None}
                              for k, n in enumerate(["A-016", "A-017"])]}
    return core


def finalized(tmp_path: Path, *, recorded: bool = True, stem: str = "remy1_P_1_2026-09-01_090001",
              sent: list[tuple[int, int]] | None = None, **more) -> Path:  # noqa: ANN003
    """The run as a session leaves it: written through the real writer. `sent`
    is what the board sent (`strobes()` by default), `more` further header fields."""
    session = tmp_path / "data" / "P" / "P_1_2026-09-01"
    json_path = session / "behavior.json" / f"{stem}.json"
    writer = AnimalWriter(session / "behavior.tsv" / f"{stem}.tsv", json_path,
                          session / "behavior.mat" / f"{stem}.mat", fields(tmp_path, recorded, **more), {},
                          profile_snapshot=g2.generated_profile().to_json())
    writer.open_files()
    for code, ms in strobes() if sent is None else sent:
        writer.record(code, ms)
    writer.finalize("BF_END_SESSION received")
    return json_path


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def mat_of(json_path: Path) -> Path:
    return json_path.parent.parent / "behavior.mat" / f"{json_path.stem}.mat"


def time_columns(row: dict) -> list[str]:
    return [key for key in row if key.endswith("_s")]


# --- the run's own files -------------------------------------------------------- #

def test_an_aligned_run_holds_its_counts_and_every_events_time_in_seconds(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    before = read(json_path)
    assert rd.recording_sync_of(before) is None
    assert all(row[c] is None for row in before["trials"]["rows"] for c in time_columns(row)), "not aligned yet"

    entry = alignment.align_file(json_path)
    assert entry["status"] == "aligned", entry

    after = read(json_path)
    assert after["recording"]["sync"] == {"matched": len(strobes()), "missed": 0, "stray": 1}
    rows = after["trials"]["rows"]
    assert len(rows) == len(g2.EVERY)
    for row in rows:
        for column in time_columns(row):
            ms = row[column[:-2] + "_ms"]
            if ms is None:
                assert row[column] is None, "no event, no time"
            else:
                # `*_ms` is from the run's first strobe, which was sent at 1000 ms.
                assert row[column] == sample_of(1000 + ms) / FS, column
    assert rows[0]["odor_on_s"] is not None and rows[0]["reward_on_s"] is not None


def test_every_other_block_is_written_back_as_it_was_read(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    before = read(json_path)
    alignment.align_file(json_path)
    after = read(json_path)

    assert list(after) == list(before), "the same blocks, in the same order"
    for block in before:
        if block not in ("recording", "trials"):
            assert json.dumps(after[block]) == json.dumps(before[block]), block
    assert {k: v for k, v in after["recording"].items() if k != "sync"} == before["recording"]
    strip = lambda rows: [{k: v for k, v in r.items() if not k.endswith("_s")} for r in rows]  # noqa: E731
    assert strip(after["trials"]["rows"]) == strip(before["trials"]["rows"])
    assert {k: v for k, v in after["trials"].items() if k != "rows"} == \
        {k: v for k, v in before["trials"].items() if k != "rows"}


def test_the_times_in_the_run_match_its_events_file(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    entry = alignment.align_file(json_path)
    events_file = offline.events_path(json_path)
    assert str(events_file) in entry["written"] and events_file.is_file()
    events = read(events_file)
    assert events["sync"] == read(json_path)["recording"]["sync"]

    placed = {(e["name"], e["ms"]): e["sample"] / FS for e in events["events"] if e["sample"] is not None}
    first = read(json_path)["trials"]["rows"][0]
    assert first["start_s"] == placed[("TRIAL_START", 1000 + first["start_ms"])]
    assert first["odor_on_s"] == placed[("ODOR_1_ON", 1000 + first["odor_on_ms"])]
    assert first["reward_on_s"] == placed[("FLUID_R", 1000 + first["reward_on_ms"])]


def test_the_mat_holds_the_counts_and_the_times_too(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    entry = alignment.align_file(json_path)
    assert str(mat_of(json_path)) in entry["written"]
    loaded = scipy.io.loadmat(str(mat_of(json_path)))
    sync = loaded["recording"]["sync"][0, 0]
    assert float(sync["matched"][0, 0][0, 0]) == len(strobes()) and float(sync["stray"][0, 0][0, 0]) == 1.0
    rows = loaded["trials"]["rows"][0, 0]
    first = read(json_path)["trials"]["rows"][0]
    assert float(rows["odor_on_s"][0, 0].ravel()[0]) == first["odor_on_s"]
    lazy = g2.EVERY.index(g2.LAZY)
    assert math.isnan(float(rows["odor_on_s"][lazy, 0].ravel()[0])), "no odor that trial: NaN, never []"


def test_an_event_whose_pulse_never_came_has_no_time_and_the_counts_say_so(tmp_path: Path) -> None:
    onset_ms = next(ms for code, ms in strobes() if code == g2.code("ODOR_1_ON"))
    record(tmp_path, drop={onset_ms})
    json_path = finalized(tmp_path)
    alignment.align_file(json_path)
    after = read(json_path)
    assert after["recording"]["sync"]["missed"] == 1
    assert after["recording"]["sync"]["matched"] == len(strobes()) - 1
    first = after["trials"]["rows"][0]
    assert first["odor_on_ms"] is not None and first["odor_on_s"] is None
    assert first["odor_off_s"] is not None, "the events around it are still placed"


def test_a_second_pass_writes_nothing(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    alignment.align_file(json_path)
    stamps = (json_path.stat().st_mtime_ns, mat_of(json_path).stat().st_mtime_ns)
    again = alignment.align_file(json_path)
    assert (again["status"], again["written"]) == ("current", [])
    assert (json_path.stat().st_mtime_ns, mat_of(json_path).stat().st_mtime_ns) == stamps, \
        "one rewrite per alignment: the score cache re-reads the run once"


def test_the_tsv_is_never_opened(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    tsv = json_path.parent.parent / "behavior.tsv" / f"{json_path.stem}.tsv"
    log_bytes = tsv.read_bytes()
    tsv.chmod(0)  # unreadable: an attempt to open it would fail the pass
    try:
        assert alignment.align_file(json_path)["status"] == "aligned"
    finally:
        tsv.chmod(0o644)
    assert tsv.read_bytes() == log_bytes


# --- when there is nothing to align, or nothing to align with -------------------- #

def test_an_unrecorded_runs_files_are_left_alone_and_its_times_stay_empty(tmp_path: Path) -> None:
    json_path = finalized(tmp_path, recorded=False)
    before = (json_path.read_bytes(), mat_of(json_path).read_bytes())
    entry = alignment.align_file(json_path)
    assert entry["status"] == "skipped" and "not recorded" in entry["reason"]
    assert (json_path.read_bytes(), mat_of(json_path).read_bytes()) == before
    assert all(row["odor_on_s"] is None for row in read(json_path)["trials"]["rows"])


def test_rhx_files_that_are_not_there_leave_the_run_exactly_as_finalization_wrote_it(tmp_path: Path) -> None:
    json_path = finalized(tmp_path)   # RHX never wrote a thing
    before = (json_path.read_bytes(), mat_of(json_path).read_bytes())
    entry = alignment.align_file(json_path)
    assert entry["status"] == "failed" and "recording folder" in entry["reason"]
    assert entry["written"] == []
    assert (json_path.read_bytes(), mat_of(json_path).read_bytes()) == before

    # ... and the pass can be run again once RHX's files are there.
    record(tmp_path)
    assert alignment.align_file(json_path)["status"] == "aligned"


def test_a_version_1_file_is_never_rewritten(tmp_path: Path) -> None:
    record(tmp_path)
    flat = {"rat": "remy1", "ts_data": [[c, ms] for c, ms in strobes()], "intan_recording": RECORDING,
            "intan_path": str(tmp_path / "ephys"), "intan_digital_in": 5, "intan_channels": "A-016:A-017",
            "intan_sample_rate": FS}
    path = tmp_path / "data" / "P" / "P_1_2026-09-01" / "behavior.json" / "old.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(flat), encoding="utf-8")
    entry = alignment.align_file(path)
    assert entry["status"] == "skipped" and "first viewed" in entry["reason"]
    assert read(path) == flat


def test_a_run_that_cannot_be_read_fails_alone(tmp_path: Path) -> None:
    record(tmp_path)
    good = finalized(tmp_path)
    torn = good.with_name("torn.json")
    torn.write_text("{", encoding="utf-8")
    entries = alignment.align_runs([torn, good, None])
    assert [e["status"] for e in entries] == ["failed", "aligned"]


def test_a_box_that_starts_leaves_the_remaining_runs_for_later(tmp_path: Path) -> None:
    record(tmp_path)
    first = finalized(tmp_path, stem="remy1_P_1_2026-09-01_090001")
    second = finalized(tmp_path, stem="remy2_P_1_2026-09-01_090002")
    asked = iter([False, True])
    entries = alignment.align_runs([first, second], stop=lambda: next(asked))
    assert [e["status"] for e in entries] == ["aligned", "skipped"]
    assert "box started" in entries[1]["reason"]
    assert rd.recording_sync_of(read(second)) is None


def test_only_the_runs_inside_the_recording_are_aligned(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    assert alignment.align_runs([json_path], "another_recording") == []
    assert [e["status"] for e in alignment.align_runs([json_path], RECORDING)] == ["aligned"]


# --- one alignment, shared with the first view ----------------------------------- #

def test_the_first_view_and_the_pass_align_the_same_way(tmp_path: Path) -> None:
    record(tmp_path)
    json_path = finalized(tmp_path)
    viewed = offline.align_run(json_path)
    assert viewed.filled is False, "the run's own files do not hold it yet"
    events_at_first_view = offline.events_path(json_path).read_bytes()

    alignment.align_file(json_path)
    assert offline.events_path(json_path).read_bytes() == events_at_first_view
    again = offline.align_run(json_path)
    assert again.filled is True and again.alignment == viewed.alignment
    assert read(json_path)["recording"]["sync"] == {
        "matched": viewed.alignment.matched, "missed": viewed.alignment.missed, "stray": viewed.alignment.stray}


def test_rederive_keeps_an_alignment_it_knows_nothing_about(tmp_path: Path) -> None:
    from ephymeris_sidecar.sessions import derived

    record(tmp_path)
    json_path = finalized(tmp_path)
    alignment.align_file(json_path)
    aligned = json_path.read_bytes()
    entry = derived.rederive_file(json_path)
    assert entry is not None and entry["status"] == "current", entry
    assert json_path.read_bytes() == aligned


# --- through the archive --------------------------------------------------------- #

async def test_the_archive_aligns_and_queues_what_it_wrote_for_backup(rig, tmp_path: Path) -> None:  # noqa: ANN001, F811
    record(tmp_path)
    json_path = finalized(tmp_path)
    [entry] = await rig.archive.align_recorded([str(json_path)], RECORDING)
    assert entry["status"] == "aligned"
    assert set(rig.changes[-1].files_to_back_up) == {
        str(json_path), str(mat_of(json_path)), str(offline.events_path(json_path))}


async def test_the_archive_refuses_while_a_box_is_running(rig, tmp_path: Path) -> None:  # noqa: ANN001, F811
    record(tmp_path)
    json_path = finalized(tmp_path)
    before = json_path.read_bytes()
    rig.lifecycle.writing = True
    with pytest.raises(RigInUse):
        await rig.archive.align_recorded([str(json_path)], RECORDING)
    assert json_path.read_bytes() == before


def test_a_run_pulsed_once_per_tick_places_every_strobe_of_the_tick(tmp_path: Path) -> None:
    """A board that announced `SYNC=TICK` pulses once per tick that strobes:
    every strobe of a tick takes that tick's pulse."""
    sent = ticked()
    ticks = sorted({ms for _, ms in sent})
    assert len(ticks) == len(sent) - 2 * len(g2.EVERY), "three header codes a tick"
    recording(tmp_path / "ephys" / RECORDING, ticks[-1] // 1000 + 4, {sample_of(ms): 1 << 4 for ms in ticks}, [])
    json_path = finalized(tmp_path, sent=sent, sync="tick")
    assert rd.sync_of(read(json_path)) == "tick"

    entry = alignment.align_file(json_path)
    assert entry["status"] == "aligned", entry
    after = read(json_path)
    assert after["recording"]["sync"] == {"matched": len(sent), "missed": 0, "stray": 0}
    rows = after["trials"]["rows"]
    assert len(rows) == len(g2.EVERY)
    for row in rows:
        for column in time_columns(row):
            ms = row[column[:-2] + "_ms"]
            assert row[column] == (None if ms is None else sample_of(1000 + ms) / FS), column
    assert rows[0]["start_s"] is not None and rows[0]["odor_on_s"] is not None


def test_a_run_another_interpreter_recorded_gets_its_counts_and_keeps_its_table(tmp_path: Path) -> None:
    """This build derives no table for it, so the one it holds is left as it
    was; the counts still land."""
    from ephymeris_sidecar.sessions import derived

    record(tmp_path)
    ours = read(finalized(tmp_path, stem="remy2_P_1_2026-09-01_090002"))
    json_path = finalized(tmp_path, interp=8)
    written = read(json_path)
    assert "trials" not in written and derived.derive(written) is None
    theirs = {**ours["trials"], "interp": 8}
    json_path.write_text(json.dumps(rd.with_trial_table(written, theirs), indent=2), encoding="utf-8")

    entry = alignment.align_file(json_path)
    assert entry["status"] == "aligned", entry
    after = read(json_path)
    assert after["recording"]["sync"] == {"matched": len(strobes()), "missed": 0, "stray": 1}
    assert after["trials"] == theirs


# --- a run the pass did not reach ----------------------------------------------- #

async def test_the_first_view_of_a_run_the_pass_missed_fills_its_files(tmp_path: Path) -> None:
    """RHX was away, or a box was running, when the recording ended: viewing
    the run aligns it, and then writes what it found into the run's files."""
    import asyncio
    import struct

    from ephymeris_sidecar.sessions.models import SessionAnimalRun
    from tests.live_sidecar import animal
    from tests.test_utility import FakeTool
    from tests.wire import dispatch, running_app

    record(tmp_path)
    # A PSTH needs spikes: one on each of the run's channels, with a 1 ms snapshot each side.
    folder = tmp_path / "ephys" / RECORDING
    head = (folder / "spike.dat").read_bytes()
    (folder / "spike.dat").write_bytes(
        head + b"".join(struct.pack("<5siB", name, sample_of(1500), 1) for name in (b"A-016", b"A-017")))
    json_path = finalized(tmp_path)
    assert rd.recording_sync_of(read(json_path)) is None

    async with running_app(tmp_path / "app", tool=FakeTool()) as app:
        cohort = (await dispatch(app, "cohorts.create", name="Batch", dataFolder=str(tmp_path / "data"),
                                 animals=[animal("remy1", box=1)]))["cohort"]
        prefix = (await dispatch(app, "prefixes.create", name="P"))["prefix"]["id"]
        session = (await dispatch(app, "sessions.create", cohortId=cohort["id"], prefixId=prefix,
                                  sessionNumber="1", recording=True))["session"]
        app.sessions.record_animal_run(SessionAnimalRun(
            id="r1", session_id=session["id"], animal_id="a-remy1", box_number=1, sketch_path="/sk",
            file_path=str(json_path), started_at="2026-09-01T09:00:01+00:00", ended_at=None,
            stop_reason="end", profile_hash=None))

        view = await dispatch(app, "intan.eventPsth", runId="r1", preMs=100, postMs=200, binMs=10, split="none")
        assert view["sync"]["matched"] == len(strobes())
        await asyncio.gather(*list(app._aligning))

        after = read(json_path)
        assert after["recording"]["sync"] == {"matched": len(strobes()), "missed": 0, "stray": 1}
        assert after["trials"]["rows"][0]["odor_on_s"] is not None
        # The next view finds the run aligned, and starts nothing.
        await dispatch(app, "intan.eventPsth", runId="r1", preMs=100, postMs=200, binMs=10, split="none")
        assert not app._aligning
