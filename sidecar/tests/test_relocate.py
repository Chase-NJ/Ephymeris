"""Relocating a cohort's data folder — `DATA.md#data-folder`.

The bug this exists to prevent: "Change data folder…" with "Move existing
contents" moved the files and repointed the cohort, but every run record,
recovered run and session record kept its absolute path at the old folder. The
next Rescan read those files as deleted and pruned the records.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService, CohortArchive
from ephymeris_sidecar.analytics.repository import AdoptedRun, AnalyticsRepository, CacheKey, CachedRun
from ephymeris_sidecar.analytics.service import _orphan_run_id
from ephymeris_sidecar.cohorts import relocate
from ephymeris_sidecar.cohorts.db import DATA_PATHS, OTHER_PATHS, Database
from ephymeris_sidecar.cohorts.folders import DataFolderError, relative_below
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.sessions.models import SessionAnimalRun
from ephymeris_sidecar.sessions.repository import SessionRepository
from tests.conftest import fine_mtime
from tests.live_sidecar import LiveSidecar, Refused, animal
from tests.test_analytics_service import Changes, Lifecycle

SESSION = "2O-Bdisc_1_2026-09-01"


class Archive:
    """One cohort, one session, one recorded run and one recovered run, with
    their files and a cache row each."""

    def __init__(self, db: Database, root: Path) -> None:
        self.db = db
        self.root = root
        self.old = root / "data" / "Batch A"
        self.new = root / "elsewhere" / "Batch A"
        self.cohorts = CohortRepository(db)
        self.sessions = SessionRepository(db)
        self.cohort_archive = CohortArchive(
            db=db, cohorts=self.cohorts, sessions=self.sessions,
            rig=Lifecycle(), on_changed=Changes(),
        )
        self.cohort = self.cohorts.create(
            "Batch A",
            str(self.old),
            groups=[{"id": "g", "name": "G", "order": 0}],
            animals=[{"id": "a1", "name": "remy1", "groupId": "g", "boxNumber": 2}],
        )
        folder = self.old / "2O-Bdisc" / SESSION
        prefix = self.sessions.create_prefix("2O-Bdisc")
        session = self.sessions.create_session(self.cohort.id, prefix, "1", "2026-09-01", str(folder))
        self.sessions.set_status(session.id, "completed")
        self.session_id = session.id
        recorded = self.write(folder, f"remy1_{SESSION}_090001")
        recovered = self.write(folder, f"remy1_{SESSION}_110000")
        self.sessions.record_animal_run(
            SessionAnimalRun(
                id="run-1", session_id=session.id, animal_id="a1", box_number=2,
                sketch_path="GRGL", file_path=str(recorded), started_at="2026-09-01T09:00:01+00:00",
                stop_reason="BF_END_SESSION received",
            )
        )
        # The id a rescan would give it: a hash of the cohort and run identity.
        self.adopted_id = _orphan_run_id(self.cohort.id, recovered)
        self.analytics = AnalyticsRepository(db)
        self.analytics.store_adopted([
            AdoptedRun(
                id=self.adopted_id, cohort_id=self.cohort.id, animal_id="a1",
                file_path=str(recovered), prefix_name="2O-Bdisc", session_number="1",
                date="2026-09-01", started_at="2026-09-01T11:00:00", sketch_name=None,
                sketch_path=None,
            )
        ])
        self.analytics.store([
            CachedRun(
                run_id=run_id, status="ok", detail=None, profile_hash=None,
                profile_source="snapshot", params_hash=None, config=None, summary={},
                key=CacheKey(file_path=str(path), mtime_ns=1, size=1, profile_hash=None, codec_version=1),
            )
            for run_id, path in (("run-1", recorded), (self.adopted_id, recovered))
        ])

    @staticmethod
    def write(folder: Path, stem: str) -> Path:
        (folder / "behavior.json").mkdir(parents=True, exist_ok=True)
        (folder / "behavior.tsv").mkdir(parents=True, exist_ok=True)
        (folder / "behavior.tsv" / f"{stem}.tsv").write_text("101\t0\n", encoding="utf-8")
        path = folder / "behavior.json" / f"{stem}.json"
        path.write_text(json.dumps({"rat": "remy1", "ts_data": [[101, 0]]}), encoding="utf-8")
        return path

    def stored_paths(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT folder_path FROM sessions UNION ALL SELECT file_path FROM session_animal_runs"
            " UNION ALL SELECT file_path FROM adopted_runs UNION ALL"
            " SELECT file_path FROM run_metrics_cache"
        ).fetchall()
        return [r[0] for r in rows]

    def all_under(self, folder: Path) -> bool:
        return all(Path(p).exists() and str(folder) in p for p in self.stored_paths())

    def journal(self) -> str:
        return self.db.conn.execute("SELECT state FROM folder_moves").fetchone()[0]

    def record(self) -> str:
        """Two recorded group runs: one saved in the default place, under the
        session folder, and one under a save root of its own. Returns the
        second, which no relocate of this cohort may touch."""
        ephys = self.old / "2O-Bdisc" / SESSION / "ephys"
        (ephys / "rec_260901_090000").mkdir(parents=True)
        (ephys / "rec_260901_090000" / "info.rhd").write_bytes(b"rhd")
        elsewhere = str(self.root / "rhx" / SESSION)
        self.sessions.set_recording(
            self.session_id,
            {"runs": [{"groupId": "g", "path": str(ephys)}, {"groupId": "h", "path": elsewhere}]},
        )
        return elsewhere

    def recording_paths(self) -> list[str]:
        recording = self.sessions.get_session(self.session_id).recording or {}
        return [run["path"] for run in recording["runs"]]


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def archive(db: Database, tmp_path: Path) -> Archive:
    return Archive(db, tmp_path)


@pytest.fixture(params=["same-volume", "other-volume"])
def volume(request: pytest.FixtureRequest, archive: Archive, other_volume) -> str:
    """Both paths: a folder rename, and copy-commit-delete onto another drive."""
    if request.param == "other-volume":
        other_volume(archive.new.parent)
    return request.param


# --- the relocate ------------------------------------------------------------------


def test_moving_the_contents_moves_every_stored_path(archive: Archive, volume: str) -> None:
    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert not archive.old.exists()
    assert archive.cohorts.get(archive.cohort.id).data_folder == str(archive.new)
    assert archive.all_under(archive.new), archive.stored_paths()
    assert archive.journal() == "done"


def test_the_records_survive_the_next_rescan(archive: Archive, volume: str) -> None:
    """The point: before, this rescan pruned every record."""
    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    async def broadcast(_message: dict) -> None:
        return None

    service = AnalyticsService(
        db=archive.db,
        cohorts=archive.cohorts,
        sessions=archive.sessions,
        broadcast=broadcast,
        archive=archive.cohort_archive,
    )
    result = asyncio.run(service.rescan(archive.cohort.id))

    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    assert result["rehomed"] == 0
    [run] = archive.sessions.runs_for_cohort(archive.cohort.id)
    assert (run.box_number, run.stop_reason) == (2, "BF_END_SESSION received")


def test_a_recording_saved_in_the_session_folder_moves_with_it(
    archive: Archive, volume: str
) -> None:
    elsewhere = archive.record()

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    ephys = archive.new / "2O-Bdisc" / SESSION / "ephys"
    assert archive.recording_paths() == [str(ephys), elsewhere]
    assert (ephys / "rec_260901_090000" / "info.rhd").is_file()


def stored_in(archive: Archive, table: str, column: str) -> list[str]:
    values = [v for (v,) in archive.db.conn.execute(f"SELECT {column} FROM {table}") if v]
    if column == "recording_json":
        return [run["path"] for v in values for run in json.loads(v)["runs"]]
    return values


def test_every_path_column_is_rebased(archive: Archive, volume: str) -> None:
    """Driven by `DATA_PATHS`, so a column added there is checked here: the
    fixture must store a path below the old folder in each, and after the
    relocate none is left there."""
    archive.record()
    recorded = archive.old / "2O-Bdisc" / SESSION / "behavior.json" / f"remy1_{SESSION}_090001.json"
    archive.db.conn.execute(
        "INSERT INTO strobe_scan_cache (file_path, file_mtime_ns, file_size, codes_json)"
        " VALUES (?, 1, 1, '[101]')",
        (str(recorded),),
    )
    archive.db.conn.commit()
    for table, column in DATA_PATHS:
        assert any(
            relative_below(p, archive.old) is not None for p in stored_in(archive, table, column)
        ), f"the fixture stores no path below the old folder in {table}.{column}"

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    for table, column in DATA_PATHS:
        paths = stored_in(archive, table, column)
        assert not [p for p in paths if relative_below(p, archive.old) is not None], (table, column)
        assert any(relative_below(p, archive.new) is not None for p in paths), (table, column)


def test_every_column_that_could_hold_a_path_is_classified(db: Database) -> None:
    """A new column naming a path, or JSON that might carry one (as
    `recording_json` does), must be in `DATA_PATHS`, which a relocate rebases,
    or in `OTHER_PATHS` with the reason it doesn't."""
    columns = {
        (table, row[1])
        for (table,) in db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        for row in db.conn.execute(f"PRAGMA table_info({table})")
    }
    looks_like_a_path = {
        (t, c)
        for t, c in columns
        if any(word in c for word in ("path", "folder", "json")) or c in ("source", "target")
    }
    classified = set(DATA_PATHS) | set(OTHER_PATHS)
    assert looks_like_a_path - classified == set()
    assert classified - columns == set(), "a listed column no longer exists"


def test_pointing_without_moving_rewrites_nothing(archive: Archive) -> None:
    before = archive.stored_paths()
    archive.new.mkdir(parents=True)
    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), False)
    assert archive.stored_paths() == before
    assert archive.cohorts.get(archive.cohort.id).data_folder == str(archive.new)


def test_a_full_destination_is_refused(archive: Archive) -> None:
    archive.new.mkdir(parents=True)
    (archive.new / "someone else's.txt").write_text("x", encoding="utf-8")
    with pytest.raises(DataFolderError):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    assert archive.all_under(archive.old)


def test_a_destination_inside_the_folder_is_refused(archive: Archive) -> None:
    with pytest.raises(DataFolderError):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.old / "inner"), True)
    assert archive.all_under(archive.old)


def test_a_failed_commit_puts_the_files_back(archive: Archive, volume: str) -> None:
    """The commit's last write is refused, after every path in it was rewritten."""
    archive.db.conn.execute(
        "CREATE TEMP TRIGGER refuse_commit BEFORE UPDATE OF data_folder ON cohorts"
        " BEGIN SELECT RAISE(ABORT, 'disk full'); END"
    )
    before = archive.stored_paths()
    with pytest.raises(sqlite3.IntegrityError, match="disk full"):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert archive.stored_paths() == before
    assert archive.all_under(archive.old)
    assert not any(p.is_file() for p in archive.new.rglob("*")) if archive.new.exists() else True
    assert archive.journal() == "rolled-back"


# --- freshness keys and durability ----------------------------------------------------


def rescan(archive: Archive) -> dict:
    async def broadcast(_message: dict) -> None:
        return None

    service = AnalyticsService(
        db=archive.db,
        cohorts=archive.cohorts,
        sessions=archive.sessions,
        broadcast=broadcast,
        archive=archive.cohort_archive,
    )
    return asyncio.run(service.rescan(archive.cohort.id))


def cache_key(archive: Archive, run_id: str) -> tuple[int | None, int | None]:
    """The stat a cached summary is vouched for by."""
    key = archive.analytics.load_cached([run_id])[run_id].key
    return key.mtime_ns, key.size


def adoption_key(archive: Archive, run_id: str) -> tuple[int | None, int | None]:
    """The stat an adoption was taken from."""
    adopted = archive.analytics.adopted_by_id(run_id)
    return adopted.file_mtime_ns, adopted.file_size


def test_a_recovered_run_keeps_its_animal_on_a_coarser_volume(
    archive: Archive, coarse_volume: None, other_volume
) -> None:
    """The copy's mtime is rounded, so a key left at the original's sent the
    recovered run back to being matched by name — and the name it carries
    had since passed to another animal."""
    other_volume(archive.new.parent)
    fine_mtime(*archive.old.rglob("*_110000.*"))
    rescan(archive)  # adopted from the file, with its stat
    archive.cohorts.update(archive.cohort.id, {"animals": [
        {"id": "a1", "name": "remy-A", "groupId": "g", "boxNumber": 2},
        {"id": "a2", "name": "remy1", "groupId": "g", "boxNumber": 3},
    ]})

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    result = rescan(archive)

    [adopted] = archive.analytics.adopted_for_cohort(archive.cohort.id)
    assert adopted.animal_id == "a1"
    assert (result["adopted"], result["orphans"]) == (0, [])
    assert adoption_key(archive, archive.adopted_id) == (
        Path(adopted.file_path).stat().st_mtime_ns,
        Path(adopted.file_path).stat().st_size,
    )


def test_only_a_key_fresh_for_the_original_is_carried(
    archive: Archive, volume: str, coarse_volume: None
) -> None:
    """A row already stale must stay stale: carried, the copy would vouch for
    a summary of content the file no longer has."""
    recorded = next(archive.old.rglob("*_090001.json"))
    fine_mtime(recorded)
    fresh = archive.analytics.load_cached(["run-1"])["run-1"]
    archive.analytics.store([replace(fresh, key=replace(
        fresh.key, mtime_ns=recorded.stat().st_mtime_ns, size=recorded.stat().st_size
    ))])  # the recovered run's row keeps its stale (1, 1)

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    copy = next(archive.new.rglob("*_090001.json")).stat()
    assert cache_key(archive, "run-1") == (copy.st_mtime_ns, copy.st_size)
    assert cache_key(archive, archive.adopted_id) == (1, 1)


def test_every_copy_is_flushed_before_an_original_goes(
    archive: Archive, monkeypatch: pytest.MonkeyPatch, other_volume
) -> None:
    other_volume(archive.new.parent)
    originals = [p for p in archive.old.rglob("*") if p.is_file()]
    real = os.fsync
    flushed: list[bool] = []

    def fsync(fd: int) -> None:
        flushed.append(all(p.is_file() for p in originals))
        real(fd)

    monkeypatch.setattr(os, "fsync", fsync)
    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert flushed == [True] * len(originals)
    assert not archive.old.exists()


# --- sessions while it moves --------------------------------------------------------


def test_an_open_session_refuses_the_move(archive: Archive, volume: str) -> None:
    """Its runner was given, or will be given, a folder at the old place."""
    archive.sessions.set_status(archive.session_id, "configuring")
    before = archive.stored_paths()

    with pytest.raises(DataFolderError, match="still open"):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert archive.stored_paths() == before
    assert archive.all_under(archive.old)
    assert archive.db.conn.execute("SELECT count(*) FROM folder_moves").fetchone()[0] == 0


def test_a_session_recorded_during_the_copy_abandons_the_move(
    archive: Archive, other_volume, hung_volume
) -> None:
    """Its file is written at the old place after the copy passed it. Moving
    its records anyway pointed them at nothing, and the next Rescan pruned
    the run."""
    other_volume(archive.new.parent)
    drive = hung_volume(archive.new.parent)
    late_folder = archive.old / "2O-Bdisc" / "2O-Bdisc_2_2026-09-02"
    outcome: list[BaseException] = []

    def move() -> None:
        try:
            relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
        except BaseException as exc:  # noqa: BLE001 - handed back to the test thread
            outcome.append(exc)

    mover = threading.Thread(target=move)
    mover.start()
    try:
        assert drive.entered.wait(5), "the relocate never began copying"
        [prefix] = archive.sessions.list_prefixes()
        session = archive.sessions.create_session(
            archive.cohort.id, prefix, "2", "2026-09-02", str(late_folder)
        )
        path = Archive.write(late_folder, "remy1_2O-Bdisc_2_2026-09-02_090001")
        archive.sessions.record_animal_run(
            SessionAnimalRun(
                id="run-late", session_id=session.id, animal_id="a1", box_number=2,
                sketch_path="GRGL", file_path=str(path), started_at="2026-09-02T09:00:01+00:00",
                stop_reason="BF_END_SESSION received",
            )
        )
        archive.sessions.set_status(session.id, "completed")
    finally:
        drive.release()
        mover.join(10)

    [error] = outcome
    assert isinstance(error, DataFolderError)
    assert "while its data was being copied" in str(error)
    assert archive.cohorts.get(archive.cohort.id).data_folder == str(archive.old)
    assert archive.all_under(archive.old), archive.stored_paths()
    assert not any(p.is_file() for p in archive.new.rglob("*"))
    assert archive.journal() == "rolled-back"
    assert rescan(archive)["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}


async def test_a_session_cannot_be_set_up_while_the_folder_moves(
    sidecar: LiveSidecar, tmp_path: Path, other_volume, hung_volume
) -> None:
    """`sessions.create` refuses: the folder it makes would be at the old place
    while the records move to the new one. Once the move is done, it can."""
    old, new = tmp_path / "data" / "Batch A", tmp_path / "elsewhere" / "Batch A"
    created = await sidecar.call(
        "cohorts.create", name="Batch A", dataFolder=str(old),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[animal("remy1", "g1", box=1)],
    )
    cohort_id = created["cohort"]["id"]
    prefix_id = (await sidecar.call("prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
    (old / "notes.txt").write_text("a file for the move to copy", encoding="utf-8")
    other_volume(new.parent)
    drive = hung_volume(new.parent)

    moving = await sidecar.send(
        "cohorts.setDataFolder", id=cohort_id, path=str(new), moveExisting=True
    )
    try:
        assert await asyncio.to_thread(drive.entered.wait, 5), "the move never began copying"
        with pytest.raises(Refused) as refused:
            await sidecar.call(
                "sessions.create", cohortId=cohort_id, prefixId=prefix_id, sessionNumber="1"
            )
        assert refused.value.code == "SESSION_INVALID"
        assert "being moved" in refused.value.message
    finally:
        drive.release()

    assert (await sidecar.reply(moving))["cohort"]["dataFolder"] == str(new)
    session = await sidecar.call(
        "sessions.create", cohortId=cohort_id, prefixId=prefix_id, sessionNumber="1"
    )
    assert Path(session["session"]["folderPath"]).is_relative_to(new)


# --- crashes -----------------------------------------------------------------------


def journal(archive: Archive, state: str) -> None:
    archive.db.conn.execute(
        "INSERT INTO folder_moves (id, cohort_id, source, target, state, created_at, updated_at)"
        " VALUES ('j', ?, ?, ?, ?, 'now', 'now')",
        (archive.cohort.id, str(archive.old), str(archive.new), state),
    )
    archive.db.conn.commit()


def test_a_crash_after_the_rename_is_finished_at_the_next_start(archive: Archive) -> None:
    journal(archive, "moving")
    archive.new.parent.mkdir(parents=True)
    os.rename(archive.old, archive.new)  # ... and the process dies here

    assert relocate.resume(archive.db) == 1

    assert archive.all_under(archive.new)
    assert archive.cohorts.get(archive.cohort.id).data_folder == str(archive.new)
    assert archive.journal() == "done"


def test_a_crash_before_the_rename_is_rolled_back(archive: Archive) -> None:
    journal(archive, "moving")
    relocate.resume(archive.db)
    assert archive.all_under(archive.old)
    assert archive.journal() == "rolled-back"


def test_a_crash_while_copying_removes_the_copy(archive: Archive) -> None:
    journal(archive, "copying")
    shutil.copytree(archive.old, archive.new)  # ... and the process dies here

    relocate.resume(archive.db)

    assert not any(p.is_file() for p in archive.new.rglob("*"))
    assert archive.all_under(archive.old)
    assert archive.journal() == "rolled-back"


def test_a_crash_mid_file_does_not_block_the_retry(
    archive: Archive, other_volume, power_cut
) -> None:
    """A copy straight to the real name left a partial file the size-checked
    undo kept, and the target was then not empty: the retry was refused until
    someone deleted it by hand. Through `.part`, all a crash leaves is a
    `.part`, and the undo removes it."""
    other_volume(archive.new.parent)
    power_cut("copy2", archive.new, nth=2)
    with pytest.raises(SystemExit):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    assert any(p.name.endswith(".part") for p in archive.new.rglob("*"))

    relocate.resume(archive.db)
    assert not any(p.is_file() for p in archive.new.rglob("*"))

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    assert archive.all_under(archive.new), archive.stored_paths()
    assert not archive.old.exists()


def test_a_crash_after_the_commit_finishes_deleting_the_originals(
    archive: Archive, other_volume, power_cut
) -> None:
    other_volume(archive.new.parent)
    power_cut("unlink", archive.old)  # the first original to go
    with pytest.raises(SystemExit):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    assert archive.all_under(archive.new)
    assert any(p.is_file() for p in archive.old.rglob("*")), "originals still there"

    relocate.resume(archive.db)

    assert not archive.old.exists()
    assert archive.journal() == "done"


def commit_then_cut(archive: Archive, other_volume, power_cut) -> None:
    """A relocate onto another volume that committed, then lost the power
    at the first original it deleted."""
    other_volume(archive.new.parent)
    power_cut("unlink", archive.old)
    with pytest.raises(SystemExit):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)


def test_a_resume_that_cannot_reach_the_originals_leaves_the_journal_to_retry(
    archive: Archive, other_volume, power_cut, unreachable_volume,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B18: with the old folder unreachable at start-up, the resume deleted
    nothing and still marked the journal `done`, so the originals stayed
    behind with nothing left to finish them. It stays `committed` instead,
    and the next start with the folder back deletes them."""
    commit_then_cut(archive, other_volume, power_cut)
    unreachable_volume(archive.old)

    relocate.resume(archive.db)
    assert archive.journal() == "committed"

    monkeypatch.undo()  # the share answers again (and every other fake goes)
    assert any(p.is_file() for p in archive.old.rglob("*")), "nothing was deleted"
    assert archive.all_under(archive.new)

    relocate.resume(archive.db)

    assert not archive.old.exists()
    assert archive.journal() == "done"


def test_originals_left_to_a_later_start_do_not_hold_up_a_session(
    archive: Archive, other_volume, power_cut, unreachable_volume
) -> None:
    """Once committed, the cohort's folder is the new one, and a session set
    up there is never in the way of deleting the old one. The old drive may
    not come back for weeks; the cohort must not wait for it."""
    commit_then_cut(archive, other_volume, power_cut)
    unreachable_volume(archive.old)
    relocate.resume(archive.db)
    assert archive.journal() == "committed"

    assert not relocate.moving(archive.db, archive.cohort.id)


def test_a_relocate_that_loses_the_old_folder_after_its_copy_leaves_the_journal_to_retry(
    archive: Archive, other_volume, unreachable_volume, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B18 on the live path: the share drops between the verified copy and
    the deletes. The records follow the copy, but nothing could be deleted,
    so the journal stays `committed` for the next start rather than `done`."""
    other_volume(archive.new.parent)
    copy_tree = relocate._copy_tree

    def copy_then_drop(source: Path, target: Path):  # noqa: ANN202
        copies = copy_tree(source, target)
        unreachable_volume(archive.old)  # the share stops answering here
        return copies

    monkeypatch.setattr(relocate, "_copy_tree", copy_then_drop)

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert archive.journal() == "committed"
    assert archive.cohorts.get(archive.cohort.id).data_folder == str(archive.new)
    monkeypatch.undo()  # the share answers again (and every other fake goes)
    assert any(p.is_file() for p in archive.old.rglob("*")), "nothing was deleted"

    relocate.resume(archive.db)

    assert not archive.old.exists()
    assert archive.journal() == "done"


def test_a_relocate_still_deleting_holds_up_a_session(
    archive: Archive, other_volume, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While this process deletes the originals, a session set up from the
    cohort as read just before the commit would make its folder at the old
    place, under what is being emptied, and `rmdir` could take it."""
    other_volume(archive.new.parent)
    delete_sources = relocate._delete_sources
    seen: list[tuple[str, bool]] = []

    def delete_and_look(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        seen.append((archive.journal(), relocate.moving(archive.db, archive.cohort.id)))
        return delete_sources(*args, **kwargs)

    monkeypatch.setattr(relocate, "_delete_sources", delete_and_look)

    relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert seen == [("committed", True)]
    assert not relocate.moving(archive.db, archive.cohort.id)


def test_originals_a_previous_run_left_in_reach_do_not_hold_up_a_session(
    archive: Archive, other_volume, power_cut
) -> None:
    """A journal an earlier process left `committed`, with its old folder
    back, is finished only by the next start's `resume`. Its commit came
    before this process read anything, so no session here can hold a stale
    folder; counting it would refuse the cohort until a restart."""
    commit_then_cut(archive, other_volume, power_cut)
    assert archive.journal() == "committed"

    assert not relocate.moving(archive.db, archive.cohort.id)


def test_a_delete_that_raises_does_not_leave_the_cohort_held_up(
    archive: Archive, other_volume, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_volume(archive.new.parent)

    def fail(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise OSError("the delete failed")

    monkeypatch.setattr(relocate, "_delete_sources", fail)

    with pytest.raises(OSError, match="the delete failed"):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert archive.journal() == "committed"
    assert not relocate.moving(archive.db, archive.cohort.id)


def test_a_missing_path_under_a_folder_that_errors_is_out_of_reach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absence is read as deletion only while a folder above it answers. One
    that errors says nothing either way, as the prune's
    `_storage_is_reachable` reads it: here the path itself reports not-found,
    but the share holding it fails, so its absence proves nothing."""
    share = tmp_path / "share"
    share.mkdir()
    gone = share / "Batch A" / "behavior.json"
    assert not relocate.out_of_reach(gone), "a missing path below a readable folder is gone"

    real = os.stat

    def stat(path, *args, **kwargs):  # noqa: ANN001, ANN202
        if Path(path) == share:
            raise OSError(errno.EIO, os.strerror(errno.EIO), str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)

    assert relocate.out_of_reach(gone)


def test_a_resume_after_the_originals_are_all_gone_is_done(
    archive: Archive, other_volume, power_cut
) -> None:
    """The old folder absent with its parent readable is a clean-up that
    finished before the crash, not an unreachable one: nothing is left to
    retry."""
    other_volume(archive.new.parent)
    power_cut("unlink", archive.old)
    with pytest.raises(SystemExit):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    shutil.rmtree(archive.old)  # the rest of the clean-up, before the power went

    relocate.resume(archive.db)

    assert archive.journal() == "done"


# --- repairing a relocate from before this fix ---------------------------------------


def old_way(archive: Archive) -> None:
    """What the buggy relocate did: move the folder, repoint the cohort, and
    leave every record at the old place."""
    archive.new.parent.mkdir(parents=True)
    shutil.move(str(archive.old), str(archive.new))
    archive.cohorts.set_data_folder(archive.cohort.id, str(archive.new))


def test_rescan_re_points_records_an_old_relocate_left_behind(archive: Archive) -> None:
    old_way(archive)

    async def broadcast(_message: dict) -> None:
        return None

    service = AnalyticsService(
        db=archive.db,
        cohorts=archive.cohorts,
        sessions=archive.sessions,
        broadcast=broadcast,
        archive=archive.cohort_archive,
    )
    result = asyncio.run(service.rescan(archive.cohort.id))

    assert result["rehomed"] == 3  # the session, the recorded run, the recovered one
    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    # The recovered run is the same row, not a second adoption of its file.
    assert [a.id for a in archive.analytics.adopted_for_cohort(archive.cohort.id)] == [archive.adopted_id]
    assert archive.all_under(archive.new), archive.stored_paths()
    [run] = archive.sessions.runs_for_cohort(archive.cohort.id)
    assert run.stop_reason == "BF_END_SESSION received"


def test_rescan_re_points_a_recording_an_old_relocate_left_behind(archive: Archive) -> None:
    elsewhere = archive.record()
    old_way(archive)

    async def broadcast(_message: dict) -> None:
        return None

    service = AnalyticsService(
        db=archive.db,
        cohorts=archive.cohorts,
        sessions=archive.sessions,
        broadcast=broadcast,
        archive=archive.cohort_archive,
    )
    asyncio.run(service.rescan(archive.cohort.id))

    assert archive.recording_paths() == [
        str(archive.new / "2O-Bdisc" / SESSION / "ephys"),
        elsewhere,
    ]


def test_a_record_whose_file_is_not_at_the_new_place_is_left_for_the_prune(
    archive: Archive,
) -> None:
    old_way(archive)
    lost = next((archive.new / "2O-Bdisc" / SESSION / "behavior.json").glob("*090001.json"))
    lost.unlink()
    (lost.parent.parent / "behavior.tsv" / f"{lost.stem}.tsv").unlink()

    assert relocate.rehome(archive.db, archive.cohort.id) == 2
    [recorded] = [r.file_path for r in archive.sessions.runs_for(archive.session_id) if r.id == "run-1"]
    assert str(archive.old) in recorded


def test_rehome_leaves_a_healthy_cohort_alone(archive: Archive) -> None:
    before = archive.stored_paths()
    assert relocate.rehome(archive.db, archive.cohort.id) == 0
    assert archive.stored_paths() == before


def test_a_summary_waiting_on_a_relocate_reads_the_new_paths(
    archive: Archive, other_volume, hung_volume
) -> None:
    """A summary that arrives mid-relocate waits for it, then reads the records
    the relocate left — not the ones it found before waiting, whose files
    have just left."""
    other_volume(archive.new.parent)
    drive = hung_volume(archive.new.parent)

    async def broadcast(_message: dict) -> None:
        return None

    service = AnalyticsService(
        db=archive.db,
        cohorts=archive.cohorts,
        sessions=archive.sessions,
        broadcast=broadcast,
        archive=archive.cohort_archive,
    )

    async def scenario() -> dict:
        moving = asyncio.create_task(
            archive.cohort_archive.relocate(archive.cohort.id, str(archive.new), True)
        )
        # Mid-copy, holding the archive lock.
        assert await asyncio.to_thread(drive.entered.wait, 5), "the relocate never began copying"
        summary = asyncio.create_task(service.summary(archive.cohort.id))
        await asyncio.sleep(0.2)  # long enough for any read taken before waiting
        drive.release()
        await moving
        return await summary

    result = asyncio.run(scenario())

    assert result["dataFolder"] == str(archive.new)
    assert result["warnings"] == []
    # The earlier run is set aside as a false start; staleness is the point.
    runs = result["runs"] + result["falseStarts"]
    assert len(runs) == 2
    assert not any(run["stale"] for run in runs)
    assert archive.all_under(archive.new), archive.stored_paths()
