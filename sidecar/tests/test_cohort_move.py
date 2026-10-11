"""Moving animals between cohorts — `DATA.md#moving-animals-between-cohorts`.

The case this exists for: a grad student split a twelve-animal cohort into ten
and two by deleting the two from the roster and adding same-named animals to a
new cohort. History stayed behind under dead ids, and the new cohort started
from nothing. A move takes the animals' files, records and notes to the
destination, so the history is the destination's and none of it the source's.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import AnalyticsService, CohortArchive
from ephymeris_sidecar.analytics.repository import AnalyticsRepository, CacheKey, CachedRun
from ephymeris_sidecar.cohorts import move_apply, relocate
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.move import MoveRequest
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.logbook.models import SessionNote
from ephymeris_sidecar.logbook.repository import LogbookRepository
from ephymeris_sidecar.sessions.models import GroupRun, SessionAnimalRun
from ephymeris_sidecar.sessions.repository import SessionRepository
from tests.conftest import fine_mtime
from tests.test_relocate import unreachable


class Lab:
    """Cohort A (remy1, remy2, slow1 in boxes 1-3) and cohort B, with real
    files on disk.

    Session 1 is everyone's; session 2 is slow1's alone.
    """

    def __init__(self, db: Database, root: Path, *, legacy: bool = False) -> None:
        self.db = db
        self.cohorts = CohortRepository(db)
        self.sessions = SessionRepository(db)
        self.legacy = legacy
        self.a_root = root / "data" / "A"
        self.b_root = root / "data" / "B"
        self.a_root.mkdir(parents=True)
        self.b_root.mkdir(parents=True)
        self.a = self.cohorts.create(
            "A",
            str(self.a_root),
            groups=[{"id": "ga", "name": "Morning", "order": 0}],
            animals=[
                {"id": "remy1", "name": "remy1", "groupId": "ga", "boxNumber": 1},
                {"id": "remy2", "name": "remy2", "groupId": "ga", "boxNumber": 2},
                {"id": "slow1", "name": "slow1", "groupId": "ga", "boxNumber": 3, "sex": "F"},
            ],
        )
        self.b = self.cohorts.create(
            "B", str(self.b_root), groups=[{"id": "gb", "name": "Slow", "order": 0}]
        )
        self.prefix = self.sessions.create_prefix("2O-Bdisc")
        self.s1 = self.add_session("1", "2026-07-22", ["remy1", "remy2", "slow1"])
        self.s2 = self.add_session("2", "2026-07-23", ["slow1"])

    def folder(self, number: str, date: str, root: Path | None = None) -> Path:
        return (root or self.a_root) / "2O-Bdisc" / f"2O-Bdisc_{number}_{date}"

    def add_session(self, number: str, date: str, animals: list[str]) -> str:
        folder = self.folder(number, date)
        session = self.sessions.create_session(self.a.id, self.prefix, number, date, str(folder))
        self.sessions.set_group_runs(
            session.id, [GroupRun("ga", 0, f"{date}T10:00:00+00:00", f"{date}T11:00:00+00:00")]
        )
        self.sessions.set_status(session.id, "completed")
        json_dir, tsv_dir = ("behavior_json", "recovery_tsv") if self.legacy else (
            "behavior.json",
            "behavior.tsv",
        )
        for box, name in enumerate(animals, start=1):
            stem = f"{name}_2O-Bdisc_{number}_{date}_10000{box}"
            (folder / json_dir).mkdir(parents=True, exist_ok=True)
            (folder / tsv_dir).mkdir(parents=True, exist_ok=True)
            path = folder / json_dir / f"{stem}.json"
            path.write_text(
                json.dumps({"rat": name, "sketch": "GRGL", "ts_data": [[101, 0], [249, 10]]}),
                encoding="utf-8",
            )
            (folder / tsv_dir / f"{stem}.tsv").write_text(f"# {name}\n101\t0\n", encoding="utf-8")
            self.sessions.record_animal_run(
                SessionAnimalRun(
                    id=f"run-{number}-{name}",
                    session_id=session.id,
                    animal_id=name,
                    box_number={"remy1": 1, "remy2": 2, "slow1": 3}[name],
                    sketch_path="GRGL",
                    file_path=str(path),
                    started_at=f"{date}T10:05:00+00:00",
                )
            )
        return session.id

    def note(self, session_id: str, body: str, *, animal: str | None = None, box: int | None = None) -> str:
        note_id = f"note-{body}"
        kind = "animal" if animal else "box" if box else "session"
        LogbookRepository(self.db).add(
            SessionNote(
                id=note_id, session_id=session_id, cohort_id=self.a.id,
                at="2026-07-22T10:30:00+00:00", created_at="now", tag="observation",
                body=body, scope_kind=kind, animal_id=animal, box_number=box,
            )
        )
        return note_id

    def request(self, *ids: str, dest_group: str | None = None) -> MoveRequest:
        return MoveRequest(self.a.id, list(ids), self.b.id, dest_group)

    def preview(self, *ids: str, busy: str | None = None):
        return move_apply.preview(self.db, self.request(*ids), busy=busy)

    def apply(self, *ids: str):
        return move_apply.apply(self.db, self.request(*ids))

    def runs(self, cohort_id: str) -> dict[str, tuple[str, str]]:
        return {
            r.id: (r.animal_id, r.file_path or "")
            for r in self.sessions.runs_for_cohort(cohort_id)
        }

    def notes(self) -> list[tuple[str, str, str]]:
        """(body, cohort, session) for every note in either cohort."""
        logbook = LogbookRepository(self.db)
        return [
            (n.body, n.cohort_id, n.session_id)
            for cohort in (self.a.id, self.b.id)
            for n in logbook.notes_for_cohort(cohort)
        ]

    def note_rows(self) -> dict[str, tuple[str, str]]:
        """body → (cohort, session) for every note."""
        return {body: (cohort, session) for body, cohort, session in self.notes()}

    def files(self, root: Path) -> set[str]:
        return {
            str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*") if p.is_file()
        }


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "app" / "ephymeris.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def lab(db: Database, tmp_path: Path) -> Lab:
    return Lab(db, tmp_path)


def give_b(lab: Lab, name: str, animal_id: str) -> None:
    """The split as it was done by hand: B got its own animal of that name."""
    lab.cohorts.update(lab.b.id, {"animals": [{"id": animal_id, "name": name, "groupId": "gb"}]})


# --- the preview ---------------------------------------------------------------


def test_a_preview_changes_nothing(lab: Lab) -> None:
    before_a, before_b = lab.files(lab.a_root), lab.files(lab.b_root)
    plan = lab.preview("slow1")

    assert plan.refused == []
    assert lab.files(lab.a_root) == before_a and lab.files(lab.b_root) == before_b
    assert {r: a for r, (a, _) in lab.runs(lab.a.id).items()}["run-2-slow1"] == "slow1"
    payload = plan.to_json(applied=False)
    assert payload["files"]["count"] == 4  # .json and .tsv, in two sessions
    assert {s["label"]: s["kind"] for s in payload["sessions"]} == {
        "2O-Bdisc_1": "split",
        "2O-Bdisc_2": "whole",
    }


def test_a_same_named_animal_in_the_destination_is_joined(lab: Lab) -> None:
    give_b(lab, "Slow1", "b-slow")
    [animal] = lab.preview("slow1").animals
    assert (animal.outcome, animal.dest_id) == ("joins", "b-slow")


def test_an_animal_the_destination_lacks_is_carried_with_its_id(lab: Lab) -> None:
    [animal] = lab.preview("slow1").animals
    assert (animal.outcome, animal.dest_id, animal.dest_group_id, animal.dest_box) == (
        "carried",
        "slow1",
        "gb",
        3,
    )


# --- the move ------------------------------------------------------------------


def test_the_files_records_and_notes_move(lab: Lab) -> None:
    give_b(lab, "slow1", "b-slow")
    shared = lab.note(lab.s1, "Fan was loud")
    lab.note(lab.s1, "slow1-hesitant", animal="slow1")
    lab.note(lab.s1, "remy1-fine", animal="remy1")
    lab.note(lab.s1, "box3-sticky", box=3)
    lab.note(lab.s1, "box1-clean", box=1)
    lab.note(lab.s2, "slow1-alone")

    plan = lab.apply("slow1")

    # Files: under B at the same place below the cohort folder, gone from A.
    moved = {
        "2O-Bdisc/2O-Bdisc_1_2026-07-22/behavior.json/slow1_2O-Bdisc_1_2026-07-22_100003.json",
        "2O-Bdisc/2O-Bdisc_1_2026-07-22/behavior.tsv/slow1_2O-Bdisc_1_2026-07-22_100003.tsv",
        "2O-Bdisc/2O-Bdisc_2_2026-07-23/behavior.json/slow1_2O-Bdisc_2_2026-07-23_100001.json",
        "2O-Bdisc/2O-Bdisc_2_2026-07-23/behavior.tsv/slow1_2O-Bdisc_2_2026-07-23_100001.tsv",
    }
    assert moved <= lab.files(lab.b_root)
    assert not moved & lab.files(lab.a_root)
    assert not lab.folder("2", "2026-07-23").exists(), "session 2 was slow1's alone"
    assert any("remy1" in f for f in lab.files(lab.a_root))

    # Records: every slow1 run is B's, under B's animal, pointing at B's files.
    a_runs, b_runs = lab.runs(lab.a.id), lab.runs(lab.b.id)
    assert {a for a, _ in a_runs.values()} == {"remy1", "remy2"}
    assert {a for a, _ in b_runs.values()} == {"b-slow"}
    assert all(Path(p).is_file() and str(lab.b_root) in p for _, p in b_runs.values())
    assert [a.name for a in lab.cohorts.get(lab.a.id).animals] == ["remy1", "remy2"]
    assert lab.cohorts.get(lab.a.id).former_animals == []

    # Notes: about slow1 or its box, moved; the session's own, copied; the
    # rest stay.
    notes = lab.note_rows()
    b_s1 = [s for s in lab.sessions.list_sessions(lab.b.id) if s.session_number == "1"][0]
    assert notes["slow1-hesitant"] == (lab.b.id, b_s1.id)
    assert notes["box3-sticky"] == (lab.b.id, b_s1.id)
    assert notes["remy1-fine"] == (lab.a.id, lab.s1)
    assert notes["box1-clean"] == (lab.a.id, lab.s1)
    assert notes["slow1-alone"][0] == lab.b.id
    copies = [cohort for body, cohort, _ in lab.notes() if body == "Fan was loud"]
    assert sorted(copies) == sorted([lab.a.id, lab.b.id])
    assert lab.note_rows()["Fan was loud"]  # the original is untouched
    assert shared  # (named for readability)

    # Sessions: the whole one moved as itself; the split one got a B record.
    assert lab.sessions.get_session(lab.s2).cohort_id == lab.b.id
    assert b_s1.folder_path == str(lab.folder("1", "2026-07-22", lab.b_root))
    assert [g.group_id for g in b_s1.group_runs] == ["gb"]
    assert plan.files and all(f.action == "present" for f in plan.files)


def test_a_carried_animal_lands_on_the_destination_roster(lab: Lab) -> None:
    lab.apply("slow1")
    [animal] = lab.cohorts.get(lab.b.id).animals
    assert (animal.id, animal.name, animal.group_id, animal.box_number, animal.sex) == (
        "slow1",
        "slow1",
        "gb",
        3,
        "F",
    )


def test_the_labs_split_is_repaired_from_its_files(lab: Lab) -> None:
    """slow1's row was deleted before former members existed; B has its own
    slow1. The dangling id is named from its files and joins B's animal."""
    # A state only an older app could leave, so it is written the way the
    # migration tests write old schemas: by hand.
    lab.db.conn.execute("DELETE FROM animals WHERE id = 'slow1'")
    lab.db.conn.commit()
    give_b(lab, "slow1", "b-slow")
    [former] = lab.cohorts.get(lab.a.id).former_animals
    assert (former.id, former.name, former.source) == ("slow1", "slow1", "files")

    lab.apply("slow1")

    assert lab.cohorts.get(lab.a.id).former_animals == []
    assert {a for a, _ in lab.runs(lab.b.id).values()} == {"b-slow"}


def test_a_former_member_moves_as_a_former_member(lab: Lab) -> None:
    roster = [a.to_json() for a in lab.cohorts.get(lab.a.id).animals if a.id != "slow1"]
    lab.cohorts.update(lab.a.id, {"animals": roster})

    lab.apply("slow1")

    b = lab.cohorts.get(lab.b.id)
    assert b.animals == []
    assert [(f.id, f.name, f.source) for f in b.former_animals] == [("slow1", "slow1", "removed")]


def test_notes_md_is_never_moved(lab: Lab) -> None:
    (lab.folder("1", "2026-07-22") / "notes.md").write_text("# log\n", encoding="utf-8")
    lab.apply("slow1")
    assert (lab.folder("1", "2026-07-22") / "notes.md").is_file()
    assert not (lab.folder("1", "2026-07-22", lab.b_root) / "notes.md").exists()


def test_a_moved_recording_follows_a_relocate_of_the_folder_it_stayed_in(
    lab: Lab, tmp_path: Path
) -> None:
    """The recording stays in A's folder, so the session now B's points there;
    relocating A moved the files and left B's record at the old place."""
    ephys = lab.folder("2", "2026-07-23") / "ephys" / "rec_260723_100000"
    ephys.mkdir(parents=True)
    (ephys / "info.rhd").write_bytes(b"rhd")
    lab.sessions.set_recording(lab.s2, {"runs": [{"groupId": "ga", "path": str(ephys)}]})
    lab.apply("slow1")  # session 2 is slow1's alone: it moves whole
    assert lab.sessions.get_session(lab.s2).recording["runs"][0]["path"] == str(ephys)

    new_a = tmp_path / "elsewhere" / "A"
    relocate.relocate_cohort(lab.db, lab.a.id, str(new_a), True)

    [run] = lab.sessions.get_session(lab.s2).recording["runs"]
    assert run["path"] == str(new_a / ephys.relative_to(lab.a_root))
    assert (Path(run["path"]) / "info.rhd").is_file()


def cache_row(lab: Lab, path: str, key: tuple[int, int]) -> None:
    AnalyticsRepository(lab.db).store([
        CachedRun(
            run_id="run-2-slow1", status="ok", detail=None, profile_hash=None,
            profile_source="snapshot", params_hash=None, config=None, summary={},
            key=CacheKey(file_path=path, mtime_ns=key[0], size=key[1], profile_hash=None, codec_version=1),
        )
    ])


def cached_key(lab: Lab) -> tuple[str, int, int]:
    key = AnalyticsRepository(lab.db).load_cached(["run-2-slow1"])["run-2-slow1"].key
    return key.file_path, key.mtime_ns, key.size


def test_the_cache_follows_the_run_and_stays_warm(lab: Lab, coarse_volume: None) -> None:
    """Even on a volume that rounds the copy's mtime: the content is the same."""
    old = Path(lab.runs(lab.a.id)["run-2-slow1"][1])
    fine_mtime(old)
    cache_row(lab, str(old), (old.stat().st_mtime_ns, old.stat().st_size))

    lab.apply("slow1")

    path, mtime, size = cached_key(lab)
    new = Path(path).stat()
    assert str(lab.b_root) in path
    assert (mtime, size) == (new.st_mtime_ns, new.st_size)
    assert mtime != 1_760_000_000_123_456_789, "the copy's mtime was rounded"


def test_a_stale_cache_row_stays_stale(lab: Lab) -> None:
    """Made fresh by the move, it would serve a summary of content the file no
    longer has."""
    old = lab.runs(lab.a.id)["run-2-slow1"][1]
    cache_row(lab, old, (1, 1))

    lab.apply("slow1")

    path, mtime, size = cached_key(lab)
    assert str(lab.b_root) in path
    assert (mtime, size) == (1, 1)


def test_a_legacy_layout_moves_in_its_own_spelling(db: Database, tmp_path: Path) -> None:
    lab = Lab(db, tmp_path, legacy=True)
    lab.apply("slow1")
    files = lab.files(lab.b_root)
    assert any("/behavior_json/slow1_" in f for f in files)
    assert any("/recovery_tsv/slow1_" in f for f in files)


def test_a_file_no_record_points_at_moves_too(lab: Lab) -> None:
    """A crash's lone .tsv is the animal's history as much as a record is."""
    stray = lab.folder("1", "2026-07-22") / "behavior.tsv" / "slow1_2O-Bdisc_1_2026-07-22_120000.tsv"
    stray.write_text("101\t0\n", encoding="utf-8")

    lab.apply("slow1")

    assert not stray.exists()
    assert (lab.folder("1", "2026-07-22", lab.b_root) / "behavior.tsv" / stray.name).is_file()


# --- the other machine ---------------------------------------------------------


def test_files_the_other_machine_already_moved_are_followed_not_copied(lab: Lab) -> None:
    """Machine 2 runs the same move after machine 1 moved the files. Its
    records still point at A; the files are already in B."""
    for src in list(lab.a_root.rglob("slow1_*")):
        dst = lab.b_root / src.relative_to(lab.a_root)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)

    plan = lab.apply("slow1")

    assert plan.refused == []
    assert {f.action for f in plan.files} == {"already"}
    assert all(Path(p).is_file() for _, p in lab.runs(lab.b.id).values())


def test_after_a_move_neither_rescan_prunes_or_adopts(lab: Lab) -> None:
    import asyncio

    async def broadcast(_message: dict) -> None:
        return None

    archive = CohortArchive(db=lab.db, cohorts=lab.cohorts, sessions=lab.sessions)
    service = AnalyticsService(
        db=lab.db, cohorts=lab.cohorts, sessions=lab.sessions, broadcast=broadcast, archive=archive
    )
    lab.apply("slow1")

    for cohort in (lab.a.id, lab.b.id):
        result = asyncio.run(service.rescan(cohort))
        assert result["adopted"] == 0, cohort
        assert result["pruned"] == {"runs": 0, "sessions": 0, "adopted": 0}, cohort


# --- refusals --------------------------------------------------------------------


def test_a_busy_rig_refuses(lab: Lab) -> None:
    plan = lab.preview("slow1", busy="A session is running.")
    assert [r["code"] for r in plan.refused] == ["busy"]
    with pytest.raises(move_apply.MoveRefused):
        move_apply.apply(lab.db, lab.request("slow1"), busy="A session is running.")


def test_a_differing_file_at_the_destination_refuses_and_moves_nothing(lab: Lab) -> None:
    clash = (
        lab.folder("2", "2026-07-23", lab.b_root)
        / "behavior.json"
        / "slow1_2O-Bdisc_2_2026-07-23_100001.json"
    )
    clash.parent.mkdir(parents=True)
    clash.write_text("{}", encoding="utf-8")
    before = lab.files(lab.a_root)

    with pytest.raises(move_apply.MoveRefused) as caught:
        lab.apply("slow1")

    assert [r["code"] for r in caught.value.plan.refused] == ["collision"]
    assert lab.files(lab.a_root) == before
    assert clash.read_text(encoding="utf-8") == "{}"


def test_an_identical_file_at_the_destination_is_not_a_collision(lab: Lab) -> None:
    src = lab.folder("2", "2026-07-23") / "behavior.json" / "slow1_2O-Bdisc_2_2026-07-23_100001.json"
    dst = lab.b_root / src.relative_to(lab.a_root)
    dst.parent.mkdir(parents=True)
    dst.write_bytes(src.read_bytes())

    plan = lab.preview("slow1")

    assert plan.refused == []
    assert plan.to_json(applied=False)["files"]["alreadyThere"] == 1


def test_an_open_session_refuses(lab: Lab) -> None:
    lab.sessions.set_status(lab.s1, "running")
    assert [r["code"] for r in lab.preview("slow1").refused] == ["unfinished-session"]


def test_moving_within_one_cohort_refuses(lab: Lab) -> None:
    plan = move_apply.preview(lab.db, MoveRequest(lab.a.id, ["slow1"], lab.a.id))
    assert [r["code"] for r in plan.refused] == ["same-cohort"]


def test_an_animal_the_source_never_had_refuses(lab: Lab) -> None:
    assert [r["code"] for r in lab.preview("nobody").refused] == ["unknown-animal"]


def test_nested_data_folders_refuse(lab: Lab) -> None:
    lab.cohorts.set_data_folder(lab.b.id, str(lab.a_root / "inner"))
    (lab.a_root / "inner").mkdir()
    assert [r["code"] for r in lab.preview("slow1").refused] == ["same-folder"]


# --- crashes -----------------------------------------------------------------------


def test_a_crash_while_copying_is_undone_at_the_next_start(lab: Lab, power_cut) -> None:
    before = lab.files(lab.a_root)
    power_cut("copy2", lab.b_root, nth=2)
    with pytest.raises(SystemExit):
        lab.apply("slow1")
    assert lab.files(lab.b_root), "the first file was copied before the cut"

    assert move_apply.resume(lab.db) == 1

    assert lab.files(lab.b_root) == set()
    assert lab.files(lab.a_root) == before
    assert {a for a, _ in lab.runs(lab.a.id).values()} == {"remy1", "remy2", "slow1"}
    [state] = lab.db.conn.execute("SELECT state FROM animal_moves").fetchone()
    assert state == "rolled-back"


def test_a_crash_after_the_commit_is_finished_at_the_next_start(lab: Lab, power_cut) -> None:
    power_cut("unlink", lab.a_root)  # the first original to go
    with pytest.raises(SystemExit):
        lab.apply("slow1")
    assert any("slow1" in f for f in lab.files(lab.a_root)), "originals still there"

    assert move_apply.resume(lab.db) == 1

    assert not any("slow1" in f for f in lab.files(lab.a_root))
    assert all(Path(p).is_file() for _, p in lab.runs(lab.b.id).values())


def test_a_resume_that_cannot_reach_the_originals_leaves_the_journal_to_retry(
    lab: Lab, power_cut, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B18: with the source's folder unreachable at start-up, the resume
    deleted nothing and still marked the move `done`, so the originals stayed
    behind with nothing left to finish them. It stays `committed` instead,
    and the next start with the folder back deletes them."""
    power_cut("unlink", lab.a_root)  # the first original to go
    with pytest.raises(SystemExit):
        lab.apply("slow1")

    with monkeypatch.context() as m:
        unreachable(m, lab.a_root)
        move_apply.resume(lab.db)
    [state] = lab.db.conn.execute("SELECT state FROM animal_moves").fetchone()
    assert state == "committed"
    assert any("slow1" in f for f in lab.files(lab.a_root)), "nothing was deleted"

    assert move_apply.resume(lab.db) == 1

    assert not any("slow1" in f for f in lab.files(lab.a_root))
    [state] = lab.db.conn.execute("SELECT state FROM animal_moves").fetchone()
    assert state == "done"


def test_records_changing_under_the_copy_abandon_the_move(lab: Lab) -> None:
    def record_once_copied(done: int, total: int) -> None:
        if done < total:
            return
        lab.sessions.record_animal_run(
            SessionAnimalRun(
                id="late", session_id=lab.s1, animal_id="slow1", box_number=3,
                sketch_path="GRGL", started_at="now",
            )
        )

    before = lab.files(lab.a_root)

    with pytest.raises(move_apply.MoveRefused):
        move_apply.apply(lab.db, lab.request("slow1"), on_copied=record_once_copied)

    assert lab.files(lab.b_root) == set()
    assert lab.files(lab.a_root) == before
    assert "slow1" in {a for a, _ in lab.runs(lab.a.id).values()}
