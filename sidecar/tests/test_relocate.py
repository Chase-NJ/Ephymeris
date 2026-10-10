"""Relocating a cohort's data folder — `DATA.md#data-folder`.

The bug this exists to prevent: "Change data folder…" with "Move existing
contents" moved the files and repointed the cohort, but every run record,
recovered run and session record kept its absolute path at the old folder. The
next Rescan read those files as deleted and pruned the records.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService
from ephymeris_sidecar.analytics.service import _orphan_run_id
from ephymeris_sidecar.cohorts import relocate
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.folders import DataFolderError
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.sessions.models import SessionAnimalRun
from ephymeris_sidecar.sessions.repository import SessionRepository

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
        # The id a rescan would give it: a hash of the run identity.
        self.adopted_id = _orphan_run_id(recovered)
        db.conn.execute(
            "INSERT INTO adopted_runs (id, cohort_id, animal_id, file_path, prefix_name,"
            " session_number, date, started_at, adopted_at) VALUES (?, ?, 'a1', ?,"
            " '2O-Bdisc', '1', '2026-09-01', '2026-09-01T11:00:00', 'now')",
            (self.adopted_id, self.cohort.id, str(recovered)),
        )
        for run_id, path in (("run-1", recorded), (self.adopted_id, recovered)):
            db.conn.execute(
                "INSERT INTO run_metrics_cache (run_id, file_path, file_mtime_ns, file_size,"
                " profile_source, codec_version, computed_at, status, summary_json)"
                " VALUES (?, ?, 1, 1, 'snapshot', 1, 'now', 'ok', '{}')",
                (run_id, str(path)),
            )
        db.conn.commit()

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
def volume(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """Both paths: a folder rename, and copy-commit-delete. A temp dir is one
    volume, so the second is forced."""
    if request.param == "other-volume":
        monkeypatch.setattr(relocate, "_same_volume", lambda _s, _t: False)
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
        db=archive.db, cohorts=archive.cohorts, sessions=archive.sessions, broadcast=broadcast
    )
    result = asyncio.run(service.rescan(archive.cohort.id))

    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    assert result["rehomed"] == 0
    [run] = archive.sessions.runs_for_cohort(archive.cohort.id)
    assert (run.box_number, run.stop_reason) == (2, "BF_END_SESSION received")


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


def test_a_failed_commit_puts_the_files_back(
    archive: Archive, volume: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(relocate, "_commit_records", fail)
    with pytest.raises(RuntimeError):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)

    assert archive.all_under(archive.old)
    assert not any(p.is_file() for p in archive.new.rglob("*")) if archive.new.exists() else True
    assert archive.journal() == "rolled-back"


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


def test_a_crash_after_the_commit_finishes_deleting_the_originals(
    archive: Archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relocate, "_same_volume", lambda _s, _t: False)

    def die(*_args, **_kwargs) -> None:
        raise SystemExit("power cut")

    monkeypatch.setattr(relocate, "_delete_sources", die)
    with pytest.raises(SystemExit):
        relocate.relocate_cohort(archive.db, archive.cohort.id, str(archive.new), True)
    monkeypatch.undo()
    assert archive.all_under(archive.new)
    assert any(p.is_file() for p in archive.old.rglob("*")), "originals still there"

    relocate.resume(archive.db)

    assert not archive.old.exists()
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
        db=archive.db, cohorts=archive.cohorts, sessions=archive.sessions, broadcast=broadcast
    )
    result = asyncio.run(service.rescan(archive.cohort.id))

    assert result["rehomed"] == 3  # the session, the recorded run, the recovered one
    assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}
    # The recovered run is the same row, not a second adoption of its file.
    assert [r[0] for r in archive.db.conn.execute("SELECT id FROM adopted_runs")] == [archive.adopted_id]
    assert archive.all_under(archive.new), archive.stored_paths()
    [run] = archive.sessions.runs_for_cohort(archive.cohort.id)
    assert run.stop_reason == "BF_END_SESSION received"


def test_a_record_whose_file_is_not_at_the_new_place_is_left_for_the_prune(
    archive: Archive,
) -> None:
    old_way(archive)
    lost = next((archive.new / "2O-Bdisc" / SESSION / "behavior.json").glob("*090001.json"))
    lost.unlink()
    (lost.parent.parent / "behavior.tsv" / f"{lost.stem}.tsv").unlink()

    assert relocate.rehome(archive.db, archive.cohort.id) == 2
    recorded = archive.db.conn.execute(
        "SELECT file_path FROM session_animal_runs WHERE id = 'run-1'"
    ).fetchone()[0]
    assert str(archive.old) in recorded


def test_rehome_leaves_a_healthy_cohort_alone(archive: Archive) -> None:
    before = archive.stored_paths()
    assert relocate.rehome(archive.db, archive.cohort.id) == 0
    assert archive.stored_paths() == before
