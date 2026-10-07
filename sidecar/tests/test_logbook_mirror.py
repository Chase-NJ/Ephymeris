"""The session folder's `notes.md` — `DATA.md#the-notesmd-mirror`.

Derived from the database, written atomically, never raised from, and
invisible to everything that reads the archive.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics import reader
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.logbook import mirror
from ephymeris_sidecar.logbook.models import SessionLog, SessionNote
from ephymeris_sidecar.logbook.service import LogbookService
from ephymeris_sidecar.sessions.models import GroupRun, Session
from tests.test_analytics_service import HIT_1, Rig

DAY = "2026-07-22"


def _session(sid: str, start: str, end: str) -> Session:
    return Session(
        id=sid,
        cohort_id="c",
        prefix_id="p",
        prefix_name="2O-Bdisc",
        session_number="12",
        date=DAY,
        started_at=start,
        status="completed",
        folder_path="/x",
        ended_at=end,
        group_runs=[GroupRun("g", 0, start, end)],
    )


def _note(nid: str, sid: str, at: str, **kw) -> SessionNote:
    return SessionNote(
        id=nid, session_id=sid, cohort_id="c", at=at, created_at=at,
        tag=kw.pop("tag", "observation"), body=kw.pop("body", "note"), **kw,
    )


def test_render_holds_the_whole_folder_in_time_order() -> None:
    morning = _session("s1", "2026-07-22T09:00:00+00:00", "2026-07-22T10:00:00+00:00")
    afternoon = _session("s2", "2026-07-22T13:00:00+00:00", "2026-07-22T14:00:00+00:00")
    text = mirror.render_markdown(
        cohort_name="Batch A",
        sessions=[afternoon, morning],
        logs=[SessionLog("s1", operator="CJ", summary="Fine.")],
        notes=[
            _note("n2", "s2", "2026-07-22T13:05:00+00:00", body="second", tag="hardware",
                  scope_kind="box", box_number=3, carry_forward=True),
            _note("n1", "s1", "2026-07-22T09:01:30+00:00", body="first", scope_kind="animal",
                  animal_id="a1"),
        ],
        changes=[
            {"animalId": "a1", "box": 1, "first": False, "task": "GRGL", "taskChange": None,
             "boxChange": None, "params": [{"key": "holdMs", "from": 200, "to": 300}],
             "paramsKnown": True},
        ],
        animal_names={"a1": "remy1"},
        now=datetime(2026, 7, 23, tzinfo=timezone.utc),
    )
    assert text.startswith("# 2O-Bdisc_12 · 2026-07-22")
    assert "Operator: CJ" in text
    assert "holdMs `200` → `300`" in text
    # The whole day: first start to last end.
    assert "| 5:00:00 |" in text
    first, second = text.index("first"), text.index("second")
    assert first < second
    assert "T+01:30" in text and "remy1" in text
    assert "T+05:00" in text and "Box 3" in text and "carry forward" in text


def test_write_is_atomic_skips_unchanged_and_leaves_no_part(tmp_path: Path) -> None:
    folder = tmp_path / "prefix" / "session"
    folder.parent.mkdir()
    assert mirror.write_mirror(folder, "hello\n") == folder / "notes.md"
    assert (folder / "notes.md").read_text(encoding="utf-8") == "hello\n"
    assert mirror.write_mirror(folder, "hello\n") is None  # unchanged: no rewrite, no backup
    assert not list(folder.glob("*.part"))


def test_a_missing_archive_is_never_recreated(tmp_path: Path) -> None:
    """A missing prefix folder means an unmounted drive, not a folder to make."""
    folder = tmp_path / "unmounted" / "prefix" / "session"
    assert mirror.write_mirror(folder, "x") is None
    assert not (tmp_path / "unmounted").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
def test_an_unwritable_folder_only_logs(tmp_path: Path, caplog) -> None:
    folder = tmp_path / "session"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        assert mirror.write_mirror(folder, "x") is None
    finally:
        folder.chmod(0o700)
    assert "database copy is intact" in caplog.text


def test_notes_md_is_invisible_to_the_archive_walk(tmp_path: Path) -> None:
    folder = tmp_path / "Batch A" / "P" / f"P_1_{DAY}"
    (folder / "behavior.json").mkdir(parents=True)
    (folder / "behavior.json" / "remy1.json").write_text("{}")
    (folder / "notes.md").write_text("# notes")
    cohort = tmp_path / "Batch A"
    found = [
        p.name
        for p in [*reader.walk_session_files(cohort), *reader.walk_orphaned_tsvs(cohort)]
    ]
    assert found == ["remy1.json"]


# --- through the service ------------------------------------------------------


@pytest.fixture
def rig(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    database.connect()
    r = Rig(database, tmp_path)
    r.write_sketch()
    try:
        yield r
    finally:
        database.close()


def _service(rig: Rig, queued: list) -> LogbookService:
    async def broadcast(message: dict) -> None:
        rig.events.append(message)

    return LogbookService(
        db=rig.db, cohorts=rig.cohorts, sessions=rig.sessions, profiles=rig.profiles,
        broadcast=broadcast, enqueue_backup=queued.append,
    )


async def test_a_note_writes_the_mirror_and_queues_it_for_backup(rig: Rig) -> None:
    queued: list = []
    logbook = _service(rig, queued)
    sid = rig.add_session("1", DAY)
    rig.add_run(sid, "a1", HIT_1 * 3)
    await logbook.add_note(sid, {"tag": "observation", "body": "Quiet session"})
    await logbook.drain()
    target = Path(rig.sessions.get_session(sid).folder_path) / "notes.md"
    assert "Quiet session" in target.read_text(encoding="utf-8")
    assert queued == [target]


async def test_an_unannotated_session_gets_no_file(rig: Rig) -> None:
    queued: list = []
    logbook = _service(rig, queued)
    sid = rig.add_session("1", DAY)
    rig.add_run(sid, "a1", HIT_1 * 3)
    await logbook.refresh(rig.cohort.id, [sid])
    await logbook.drain()
    assert not (Path(rig.sessions.get_session(sid).folder_path) / "notes.md").exists()
    assert queued == []


async def test_folder_mates_share_one_file(rig: Rig) -> None:
    logbook = _service(rig, [])
    first = rig.add_session("12", DAY)
    second = rig.add_session("12", DAY)
    rig.add_run(first, "a1", HIT_1 * 3)
    await logbook.add_note(first, {"tag": "observation", "body": "morning note"})
    await logbook.add_note(second, {"tag": "observation", "body": "afternoon note"})
    await logbook.drain()
    text = (Path(rig.sessions.get_session(first).folder_path) / "notes.md").read_text(
        encoding="utf-8"
    )
    assert "morning note" in text and "afternoon note" in text
