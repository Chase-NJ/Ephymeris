"""The cohort archive — `DATA.md#the-cohort-archive`.

One read of a cohort's recorded and recovered sessions, and the lock that
everything rewriting them holds. These drive it through `view` and
`exclusive` only: the readers built on it (Analytics, the session log,
`sessions.list`, tidy) have their own tests.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import ArchiveBusy, reader
from ephymeris_sidecar.cohorts.db import Database
from tests.test_analytics_adoption import LegacyRig
from tests.test_analytics_service import HIT_1, Rig

DAY = "2026-07-22"


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    r = Rig(db, tmp_path)
    r.write_sketch()
    return r


@pytest.fixture
def legacy(db: Database, tmp_path: Path) -> LegacyRig:
    return LegacyRig(db, tmp_path / "legacy")


def _recovered_file(rig: Rig, number: str, animal: str) -> Path:
    """A file in a session folder with no run record pointing at it."""
    folder = rig.root / "2O-Bdisc" / f"2O-Bdisc_{number}_{DAY}" / "behavior.json"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{animal}_2O-Bdisc_{number}_{DAY}_101500.json"
    path.write_text(
        json.dumps(
            {
                "rat": animal,
                "sketch": "GRGL_2-Odor",
                "stop_reason": "board end-of-session",
                "n_events": 2,
                "ts_data": [[101, 0], [249, 1000]],
            }
        ),
        encoding="utf-8",
    )
    return path


async def test_a_recovered_file_of_a_recorded_session_is_filed_under_it(rig: Rig) -> None:
    """Every reader sees one session holding both runs, and the summary the
    same session list as the view."""
    sid = rig.add_session("12", DAY)
    rig.add_run(sid, "a1", HIT_1)
    path = _recovered_file(rig, "12", "remy2")
    await rig.service.rescan(rig.cohort.id)

    view = rig.archive.view(rig.cohort.id)
    assert [s.id for s in view.sessions] == [sid]
    assert view.recovered == []
    assert {run.session_id for run in view.runs} == {sid}
    assert view.run_counts() == {sid: 2}
    assert str(path.parent.parent) in rig.archive.folders(rig.cohort.id)

    summary = await rig.service.summary(rig.cohort.id)
    assert [s["id"] for s in summary["sessions"]] == [s.id for s in view.sessions]


async def test_a_recovered_file_of_another_session_keeps_its_own(rig: Rig) -> None:
    sid = rig.add_session("12", DAY)
    rig.add_run(sid, "a1", HIT_1)
    _recovered_file(rig, "13", "remy2")
    await rig.service.rescan(rig.cohort.id)

    view = rig.archive.view(rig.cohort.id)
    [recovered] = view.recovered
    assert recovered.id.startswith("adopted:")
    assert view.run_counts() == {sid: 1, recovered.id: 1}


async def test_an_aborted_record_never_owns_a_recovered_file(rig: Rig) -> None:
    """It wrote nothing, whether or not the caller lists aborted records."""
    sid = rig.add_session("12", DAY)
    rig.sessions.set_status(sid, "aborted")
    _recovered_file(rig, "12", "remy2")
    await rig.service.rescan(rig.cohort.id)

    for include_aborted in (False, True):
        view = rig.archive.view(rig.cohort.id, include_aborted=include_aborted)
        [recovered] = view.recovered
        assert [run.session_id for run in view.recovered_runs] == [recovered.id]


async def test_a_filtered_summary_leaves_a_recovered_clock_where_it_was(
    legacy: LegacyRig,
) -> None:
    """A session's clock is the session's, not the selection's: narrowing a
    summary to one animal must not end the session at that animal's run."""
    legacy.add_legacy_run("remy1", HIT_1 * 5, time="120022")  # a 9 s stream
    legacy.add_legacy_run("remy2", HIT_1 * 8, time="120100")  # 15 s, ends last
    await legacy.service.rescan(legacy.cohort.id)
    whole = await legacy.service.summary(legacy.cohort.id)
    assert whole["sessions"][0]["clockEndedAt"] == "2026-06-16T12:01:15.000"

    narrowed = await legacy.service.summary(legacy.cohort.id, animal_ids=["a1"])
    assert narrowed["sessions"][0]["clockEndedAt"] == "2026-06-16T12:01:15.000"
    [listed] = legacy.archive.view(legacy.cohort.id).recovered
    assert listed.clock_ended_at == "2026-06-16T12:01:15.000"


async def test_a_run_recorded_while_a_rescan_walks_counts_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A box finalizing during a rescan: its `.json` lands and its record
    commits after the rescan read the records but before its walk returned.
    The walk adopts the file; every reader still sees one run."""
    sid = rig.add_session("12", DAY)
    # The session's folder is there from the start, as a live session's is.
    (Path(rig.sessions.get_session(sid).folder_path) / "behavior.tsv").mkdir(parents=True)
    walk = reader.walk_session_files

    def finalized_mid_walk(folder):  # noqa: ANN001, ANN202
        rig.add_run(sid, "a1", HIT_1)
        return walk(folder)

    monkeypatch.setattr(reader, "walk_session_files", finalized_mid_walk)
    await rig.service.rescan(rig.cohort.id)

    view = rig.archive.view(rig.cohort.id)
    assert [run.id for run in view.runs] == [f"r-{sid[:6]}-a1"]
    assert view.run_counts() == {sid: 1}
    assert len((await rig.service.summary(rig.cohort.id))["runs"]) == 1


async def test_a_writer_is_refused_while_the_archive_is_held(rig: Rig) -> None:
    """A rescan, a tidy, a relocate and a move each refuse rather than queue."""
    async with rig.archive.exclusive():
        with pytest.raises(ArchiveBusy):
            await rig.service.rescan(rig.cohort.id)
        with pytest.raises(ArchiveBusy):
            await rig.service.tidy(rig.cohort.id, apply=False, protect=set(), today=DAY)
        with pytest.raises(ArchiveBusy):
            await rig.archive.relocate(rig.cohort.id, str(rig.root / "elsewhere"), True)
        with pytest.raises(ArchiveBusy):
            await rig.archive.move_animals(object(), apply=False, busy=None)


async def test_a_summary_waits_for_the_archive(rig: Rig) -> None:
    rig.add_run(rig.add_session("12", DAY), "a1", HIT_1)
    release = asyncio.Event()

    async def hold() -> None:
        async with rig.archive.exclusive():
            await release.wait()

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0)
    summary = asyncio.create_task(rig.service.summary(rig.cohort.id))
    await asyncio.sleep(0.05)
    assert not summary.done()

    release.set()
    await holder
    assert len((await summary)["runs"]) == 1
