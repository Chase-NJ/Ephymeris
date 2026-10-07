"""The session log — `DATA.md#the-session-log`.

Pins the note lifecycle (add, edit, soft delete, carry-forward), the refusals,
the T+ offset's window (`DATA.md#the-session-clock`), and that every payload the
service emits matches the wire schema.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.logbook.models import (
    NoteInvalid,
    NoteNotFound,
    SessionLog,
    merge_logs,
    offset_ms,
)
from ephymeris_sidecar.logbook.service import LogbookService
from ephymeris_sidecar.protocol import validate, validate_command_result
from ephymeris_sidecar.sessions.models import GroupRun, Session
from tests.test_analytics_service import Rig

DAY = "2026-07-22"


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
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
def logbook(rig: Rig) -> LogbookService:
    async def broadcast(message: dict) -> None:
        rig.events.append(message)

    return LogbookService(
        db=rig.db,
        cohorts=rig.cohorts,
        sessions=rig.sessions,
        profiles=rig.profiles,
        broadcast=broadcast,
    )


def ran(rig: Rig, session_id: str, start: str, end: str | None) -> None:
    rig.sessions.set_group_runs(
        session_id, [GroupRun(group_id="g", order=0, started_at=start, ended_at=end)]
    )


# --- the session clock -------------------------------------------------------


def _session(**kw) -> Session:
    base = dict(
        id="s",
        cohort_id="c",
        prefix_id="p",
        prefix_name="P",
        session_number="1",
        date=DAY,
        started_at="2026-07-22T08:00:00+00:00",
        status="completed",
        folder_path="/x",
        ended_at="2026-07-22T11:00:00+00:00",
    )
    base.update(kw)
    return Session(**base)


def test_the_clock_starts_at_the_first_group_run_not_the_record() -> None:
    session = _session(
        group_runs=[
            GroupRun("b", 1, "2026-07-22T10:00:00+00:00", "2026-07-22T10:30:00+00:00"),
            GroupRun("a", 0, "2026-07-22T09:00:00+00:00", "2026-07-22T09:40:00+00:00"),
        ]
    )
    assert session.clock_started_at == "2026-07-22T09:00:00+00:00"
    # The last group's end, not when the operator finally closed the session.
    assert session.clock_ended_at == "2026-07-22T10:30:00+00:00"


def test_a_session_that_never_ran_uses_its_record_times() -> None:
    session = _session()
    assert session.clock_started_at == session.started_at
    assert session.clock_ended_at == session.ended_at


def test_an_open_session_has_no_clock_end() -> None:
    session = _session(
        status="running",
        group_runs=[GroupRun("a", 0, "2026-07-22T09:00:00+00:00", "2026-07-22T09:40:00+00:00")],
    )
    assert session.clock_ended_at is None


def test_the_offset_only_exists_inside_the_running_window() -> None:
    start, end = "2026-07-22T09:00:00+00:00", "2026-07-22T10:00:00+00:00"
    now = datetime(2026, 7, 23, tzinfo=timezone.utc)
    assert offset_ms("2026-07-22T09:12:34.500+00:00", start, end, now) == 754_500
    assert offset_ms("2026-07-22T08:59:59+00:00", start, end, now) is None
    assert offset_ms("2026-07-22T10:00:01+00:00", start, end, now) is None
    # Open: the window runs to now.
    assert offset_ms("2026-07-22T11:00:00+00:00", start, None, now) == 7_200_000
    assert offset_ms("not a time", start, end, now) is None


# --- notes -----------------------------------------------------------------


async def test_a_note_round_trips_and_matches_the_wire(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    ran(rig, sid, "2026-07-22T09:00:00+00:00", "2026-07-22T10:00:00+00:00")

    reply = await logbook.add_note(
        sid,
        {
            "tag": "hardware",
            "body": "Lick spout dripping",
            "scope": {"kind": "box", "box": 3},
            "carryForward": True,
            "at": "2026-07-22T09:20:00+00:00",
        },
    )
    assert validate_command_result("logbook.addNote", reply) == []
    note = reply["note"]
    assert note["offsetMs"] == 20 * 60 * 1000
    assert note["scope"] == {"kind": "box", "animalId": None, "box": 3}

    cohort = await logbook.cohort(rig.cohort.id)
    assert validate_command_result("logbook.cohort", cohort) == []
    assert [n["id"] for n in cohort["notes"]] == [note["id"]]
    assert rig.events[-1]["evt"] == "logbook.updated"
    assert rig.events[-1]["data"] == {"cohortId": rig.cohort.id, "sessionIds": [sid]}


async def test_an_edit_keeps_absent_fields_and_stamps_edited(
    rig: Rig, logbook: LogbookService
) -> None:
    sid = rig.add_session("1", DAY)
    note = (await logbook.add_note(sid, {"tag": "observation", "body": "calm"}))["note"]
    edited = (await logbook.edit_note(note["id"], {"body": "calm, groomed"}))["note"]
    assert edited["body"] == "calm, groomed"
    assert edited["tag"] == "observation"
    assert edited["editedAt"] is not None
    assert validate_command_result("logbook.editNote", {"note": edited}) == []


async def test_a_deleted_note_is_hidden_but_kept(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    note = (await logbook.add_note(sid, {"tag": "observation", "body": "x"}))["note"]
    await logbook.delete_note(note["id"])
    assert (await logbook.cohort(rig.cohort.id))["notes"] == []
    with pytest.raises(NoteNotFound):
        await logbook.edit_note(note["id"], {"body": "y"})
    # The row is still there, marked — a soft delete, never an erase.
    row = rig.db.conn.execute(
        "SELECT deleted_at FROM session_notes WHERE id = ?", (note["id"],)
    ).fetchone()
    assert row["deleted_at"] is not None


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"tag": "gossip", "body": "x"}, "Unknown tag"),
        ({"tag": "observation", "body": "   "}, "needs some text"),
        ({"tag": "observation", "body": "x", "scope": {"kind": "box", "box": 7}}, "1–6"),
        ({"tag": "observation", "body": "x", "scope": {"kind": "animal"}}, "needs an animal"),
        (
            {"tag": "observation", "body": "x", "scope": {"kind": "animal", "animalId": "zz"}},
            "isn't in this cohort",
        ),
    ],
)
async def test_refusals(rig: Rig, logbook: LogbookService, fields: dict, message: str) -> None:
    sid = rig.add_session("1", DAY)
    with pytest.raises(NoteInvalid, match=message):
        await logbook.add_note(sid, fields)


async def test_a_recovered_files_session_takes_no_notes(logbook: LogbookService) -> None:
    with pytest.raises(NoteInvalid, match="recovered"):
        await logbook.add_note("adopted:abc", {"tag": "observation", "body": "x"})


async def test_carry_forward_flags_open_and_resolve(rig: Rig, logbook: LogbookService) -> None:
    first = rig.add_session("1", DAY)
    second = rig.add_session("2", "2026-07-23")
    flag = (
        await logbook.add_note(
            first, {"tag": "hardware", "body": "Box 3 spout", "carryForward": True}
        )
    )["note"]
    await logbook.add_note(first, {"tag": "observation", "body": "not a flag"})

    open_now = await logbook.open_flags(rig.cohort.id)
    assert validate_command_result("logbook.openFlags", open_now) == []
    assert [n["id"] for n in open_now["notes"]] == [flag["id"]]

    resolved = (await logbook.resolve_flag(flag["id"], True, second))["note"]
    assert resolved["resolvedAt"] is not None
    assert resolved["resolvedInSessionId"] == second
    assert (await logbook.open_flags(rig.cohort.id))["notes"] == []

    reopened = (await logbook.resolve_flag(flag["id"], False, None))["note"]
    assert reopened["resolvedAt"] is None
    assert reopened["resolvedInSessionId"] is None


async def test_only_a_flag_can_be_resolved(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    note = (await logbook.add_note(sid, {"tag": "observation", "body": "x"}))["note"]
    with pytest.raises(NoteInvalid):
        await logbook.resolve_flag(note["id"], True, None)


async def test_session_fields_keep_what_is_not_sent(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    await logbook.set_session_log(sid, {"operator": "  CJ  "})
    reply = await logbook.set_session_log(sid, {"summary": "Good day."})
    assert validate_command_result("logbook.setSessionLog", reply) == []
    assert reply["log"]["operator"] == "CJ"
    assert reply["log"]["summary"] == "Good day."
    cleared = (await logbook.set_session_log(sid, {"operator": ""}))["log"]
    assert cleared["operator"] is None


async def test_annotated_means_a_live_note_or_a_filled_field(
    rig: Rig, logbook: LogbookService
) -> None:
    a, b, c = (rig.add_session(n, DAY) for n in ("1", "2", "3"))
    await logbook.add_note(a, {"tag": "observation", "body": "x"})
    gone = (await logbook.add_note(b, {"tag": "observation", "body": "x"}))["note"]
    await logbook.delete_note(gone["id"])
    await logbook.set_session_log(c, {"summary": "x"})
    assert logbook.repo.annotated_session_ids(rig.cohort.id) == {a, c}


async def test_deleting_the_cohort_takes_its_log(rig: Rig, logbook: LogbookService) -> None:
    sid = rig.add_session("1", DAY)
    await logbook.add_note(sid, {"tag": "observation", "body": "x"})
    await logbook.set_session_log(sid, {"operator": "CJ"})
    rig.cohorts.archive(rig.cohort.id)
    rig.cohorts.delete(rig.cohort.id)
    assert rig.db.conn.execute("SELECT COUNT(*) FROM session_notes").fetchone()[0] == 0
    assert rig.db.conn.execute("SELECT COUNT(*) FROM session_logs").fetchone()[0] == 0


def test_merged_logs_keep_everything_anyone_wrote() -> None:
    merged = merge_logs(
        "keep",
        [
            SessionLog("keep", operator=None, summary="Morning group fine."),
            SessionLog("b", operator="AB", summary="Afternoon: box 4 jammed."),
            SessionLog("c", operator="CD", summary=None),
        ],
    )
    assert merged is not None
    assert merged.session_id == "keep"
    assert merged.operator == "AB"
    assert merged.summary == "Morning group fine.\n\nAfternoon: box 4 jammed."
    assert merge_logs("keep", [SessionLog("b")]) is None


def test_the_session_list_item_carries_the_clock() -> None:
    item = _session().to_list_item(1)
    assert validate(("ref", "SessionListItem"), item) == []
    assert item["clockStartedAt"] == item["startedAt"]
