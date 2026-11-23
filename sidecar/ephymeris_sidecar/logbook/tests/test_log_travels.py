"""The log travels in the session folder — `DATA.md#the-log-file`,
`DECISIONS.md#0011-the-log-travels-in-the-session-folder`.

Two machines here are two databases with a cohort of the same name and the
same animals **under different ids**, each with its own data folder. A session
folder is carried from one to the other by copying it, as an operator would.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.logbook import logfile
from ephymeris_sidecar.logbook.service import LogbookService
from ephymeris_sidecar.protocol import validate_command_result
from ephymeris_sidecar.sessions.models import Round
from ephymeris_sidecar.analytics.tests.test_analytics_service import HIT_1, Rig

DAY = "2026-07-22"
START = "2026-07-22T09:00:00+00:00"
END = "2026-07-22T10:00:00+00:00"


class Machine:
    """One lab machine: its database, its copy of the cohort and its log."""

    def __init__(self, tmp_path: Path, name: str, animals: dict[str, str]) -> None:
        self.db = Database(tmp_path / name / "app" / "ephymeris.db")
        self.db.connect()
        self.rig = Rig(self.db, tmp_path / name)
        self.rig.write_sketch()
        self.rig.cohorts.update(
            self.rig.cohort.id,
            {"animals": [{"id": i, "name": n, "boxNumber": 1} for i, n in animals.items()]},
        )
        self.rig.cohort = self.rig.cohorts.get(self.rig.cohort.id)
        self.events = self.rig.events

        async def broadcast(message: dict) -> None:
            self.events.append(message)

        self.log = LogbookService(
            db=self.db, cohorts=self.rig.cohorts, sessions=self.rig.sessions,
            profiles=self.rig.profiles, archive=self.rig.archive, broadcast=broadcast,
        )

    @property
    def cohort_id(self) -> str:
        return self.rig.cohort.id

    def ran(self, number: str = "12", animal: str | None = None) -> str:
        """A finished session with one run file in its folder."""
        sid = self.rig.add_session(number, DAY)
        first = animal or self.rig.cohort.animals[0].id
        self.rig.add_run(sid, first, HIT_1 * 3)
        self.rig.sessions.set_rounds(sid, [Round(order=0, started_at=START, ended_at=END)])
        return sid

    def folder(self, sid: str) -> Path:
        return Path(self.rig.sessions.get_session(sid).folder_path)

    def wrote(self, sid: str) -> dict:
        """Write the folder's files now and return its log file."""
        self.log.write_mirror(sid)
        return json.loads((self.folder(sid) / "log.json").read_text(encoding="utf-8"))

    def carry(self, sid: str, to: "Machine") -> Path:
        """Copy the session's folder into the other machine's data folder."""
        source = self.folder(sid)
        target = to.rig.root / source.parent.name / source.name
        shutil.copytree(source, target, dirs_exist_ok=True)
        return target

    async def rescan(self) -> dict:
        result = await self.rig.archive.rescan(self.cohort_id)
        assert validate_command_result("analytics.rescan", result) == []
        return result

    async def notebook(self) -> dict:
        return await self.log.cohort(self.cohort_id)

    def close(self) -> None:
        self.db.close()


@pytest.fixture
def lab(tmp_path: Path):
    a = Machine(tmp_path, "rig-a", {"a1": "remy1", "a2": "remy2"})
    b = Machine(tmp_path, "rig-b", {"b1": "remy1", "b2": "remy2"})
    try:
        yield a, b
    finally:
        a.close()
        b.close()


async def _logged(machine: Machine) -> tuple[str, str]:
    """A session with everything a person writes: a note about an animal,
    who ran it, a summary and the day's weigh-in. (session id, note id)."""
    sid = machine.ran()
    first = machine.rig.cohort.animals[0].id
    reply = await machine.log.add_note(
        sid,
        {"tag": "animal-health", "body": "Porphyrin around the left eye.",
         "scope": {"kind": "animal", "animalId": first}, "carryForward": True},
    )
    await machine.log.set_session_log(sid, {"operator": "CJ", "summary": "Steady."})
    await machine.log.set_health(machine.cohort_id, first, DAY, 312.4, True)
    return sid, reply["note"]["id"]


# --- the file -------------------------------------------------------------------


async def test_a_session_folder_carries_its_log(lab) -> None:
    a, _ = lab
    sid, note_id = await _logged(a)
    document = a.wrote(sid)
    (session,) = document["sessions"]
    assert (session["id"], session["operator"], session["summary"]) == (sid, "CJ", "Steady.")
    assert session["notes"][0]["id"] == note_id
    assert session["notes"][0]["scope"]["animal"] == "remy1"
    assert document["weigh_ins"] == [
        {"animal": "remy1", "animal_id": "a1", "date": DAY, "weight_g": 312.4, "baseline": True,
         "recorded_at": document["weigh_ins"][0]["recorded_at"]}
    ]
    assert (a.folder(sid) / "notes.md").is_file()


async def test_a_session_nobody_wrote_in_still_carries_its_record(lab) -> None:
    a, _ = lab
    sid = a.ran()
    assert a.log.write_mirror(sid) is None  # no notes.md: nothing for a person to read
    document = json.loads((a.folder(sid) / "log.json").read_text(encoding="utf-8"))
    assert document["sessions"][0]["rounds"][0]["started_at"] == START
    assert document["sessions"][0]["notes"] == [] and document["weigh_ins"] == []


# --- onto another machine ---------------------------------------------------------


async def test_a_rescan_on_another_machine_brings_the_session_and_its_log(lab) -> None:
    a, b = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    folder = a.carry(sid, b)

    result = await b.rescan()
    assert result["adopted"] == 1
    assert result["logs"] == {
        "files": 1, "unreadable": 0, "sessions": 1, "notes": 1, "logs": 1, "weighIns": 1,
        "unknownAnimals": [],
    }

    # The session is a record here now, in this machine's folder, as it ran.
    session = b.rig.sessions.get_session(sid)
    assert (session.cohort_id, session.status) == (b.cohort_id, "completed")
    assert Path(session.folder_path) == folder
    assert (session.clock_started_at, session.clock_ended_at) == (START, END)
    assert session.recording is None

    # Its run, known here only from its file, is that session's: not a
    # recovered session of its own, so the day can be written in.
    view = b.rig.archive.view(b.cohort_id)
    assert [s.id for s in view.sessions] == [sid]
    assert {run.session_id for run in view.runs} == {sid}
    await b.log.add_note(sid, {"tag": "observation", "body": "Read on rig B."})

    notebook = await b.notebook()
    assert validate_command_result("logbook.cohort", notebook) == []
    carried = next(n for n in notebook["notes"] if n["id"] == note_id)
    # About the same animal, under this machine's own id for it.
    assert carried["scope"] == {"kind": "animal", "animalId": "b1", "box": None}
    assert (carried["body"], carried["carryForward"]) == ("Porphyrin around the left eye.", True)
    assert notebook["logs"][0]["operator"] == "CJ"
    (weigh_in,) = notebook["health"]
    assert (weigh_in["animalId"], weigh_in["weightG"], weigh_in["baseline"]) == ("b1", 312.4, True)


async def test_reading_the_same_folder_again_changes_nothing(lab) -> None:
    a, b = lab
    sid, _ = await _logged(a)
    a.wrote(sid)
    a.carry(sid, b)
    await b.rescan()
    before = await b.notebook()

    again = await b.rescan()
    assert again["logs"] == {
        "files": 1, "unreadable": 0, "sessions": 0, "notes": 0, "logs": 0, "weighIns": 0,
        "unknownAnimals": [],
    }
    assert await b.notebook() == before


async def test_an_open_session_arrives_closed(lab) -> None:
    """A session is open only on the machine running it. A copy taken mid-run
    must not hold this machine's rig."""
    a, b = lab
    sid = a.ran()
    a.rig.sessions.set_rounds(sid, [Round(order=0, started_at=START, ended_at=None)])
    a.rig.sessions.set_status(sid, "running")
    assert a.wrote(sid)["sessions"][0]["status"] == "running"
    a.carry(sid, b)

    await b.rescan()
    session = b.rig.sessions.get_session(sid)
    assert session.status == "completed"
    assert session.clock_ended_at is not None


async def test_a_session_this_machine_ran_keeps_its_own_record(lab) -> None:
    """Both machines have a record of the day: the folder's notes join this
    machine's record, and its record is not touched."""
    a, b = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    own = b.ran()
    mine = b.rig.sessions.get_session(own)
    a.carry(sid, b)

    result = await b.rescan()
    assert result["logs"]["sessions"] == 0 and result["logs"]["notes"] == 1
    assert [s.id for s in b.rig.sessions.list_sessions(b.cohort_id, include_aborted=True)] == [own]
    assert b.rig.sessions.get_session(own) == mine
    notebook = await b.notebook()
    assert [(n["id"], n["sessionId"]) for n in notebook["notes"]] == [(note_id, own)]


# --- which copy wins --------------------------------------------------------------


async def test_the_newer_edit_wins_whichever_way_the_folder_goes(lab) -> None:
    a, b = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    a.carry(sid, b)
    await b.rescan()

    # Edited on B after it arrived: A's older copy, read again, changes nothing.
    time.sleep(0.01)
    await b.log.edit_note(note_id, {"body": "Cleared by the afternoon."})
    again = b.log._intake.read_cohort(b.cohort_id, [b.folder(sid)])
    assert again.notes == 0

    # And B's folder, carried back, updates A.
    b.wrote(sid)
    b.carry(sid, a)
    back = await a.rescan()
    assert back["logs"]["notes"] == 1
    notebook = await a.notebook()
    assert notebook["notes"][0]["body"] == "Cleared by the afternoon."
    assert notebook["notes"][0]["scope"]["animalId"] == "a1"


async def test_a_deletion_travels_and_an_absence_does_not(lab) -> None:
    a, b = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    a.carry(sid, b)
    await b.rescan()
    kept = (await b.log.add_note(sid, {"tag": "observation", "body": "Only on B."}))["note"]["id"]

    # A deletes its note and removes the weigh-in, then its folder comes over
    # again. A's file has never heard of B's note: that is not a deletion.
    time.sleep(0.01)
    await a.log.delete_note(note_id)
    await a.log.set_health(a.cohort_id, "a1", DAY, None)
    document = a.wrote(sid)
    assert document["sessions"][0]["notes"] == [
        {"id": note_id, "deleted_at": document["sessions"][0]["notes"][0]["deleted_at"]}
    ]
    assert "weight_g" not in document["weigh_ins"][0]
    shutil.copyfile(a.folder(sid) / "log.json", b.folder(sid) / "log.json")

    result = await b.rescan()
    assert (result["logs"]["notes"], result["logs"]["weighIns"]) == (1, 1)
    notebook = await b.notebook()
    assert [n["id"] for n in notebook["notes"]] == [kept]
    assert notebook["health"] == []


async def test_a_removed_weigh_in_stays_removed_on_the_machine_that_removed_it(lab) -> None:
    """The folder's own file still lists it until the next write, and that
    write reads the file first."""
    a, _ = lab
    sid, _ = await _logged(a)
    a.wrote(sid)
    await a.log.set_health(a.cohort_id, "a1", DAY, None)
    await a.log.drain()
    assert (await a.notebook())["health"] == []
    assert "weight_g" not in a.wrote(sid)["weigh_ins"][0]
    # Weighed again, it is a new weigh-in, unmarked.
    await a.log.set_health(a.cohort_id, "a1", DAY, 310.0)
    (entry,) = (await a.notebook())["health"]
    assert (entry["weightG"], entry["baseline"]) == (310.0, False)


async def test_a_cleared_field_is_cleared_there_too(lab) -> None:
    a, b = lab
    sid, _ = await _logged(a)
    a.wrote(sid)
    a.carry(sid, b)
    await b.rescan()
    time.sleep(0.01)
    await a.log.set_session_log(sid, {"operator": "", "summary": ""})
    a.wrote(sid)
    shutil.copyfile(a.folder(sid) / "log.json", b.folder(sid) / "log.json")
    await b.rescan()
    assert (await b.notebook())["logs"][0]["operator"] is None


# --- animals the other machine does not have ---------------------------------------


async def test_a_note_about_an_animal_this_cohort_lacks_waits_for_it(lab, tmp_path: Path) -> None:
    a, _ = lab
    c = Machine(tmp_path, "rig-c", {"c2": "remy2"})
    try:
        sid, note_id = await _logged(a)  # about remy1, whom C does not have
        a.wrote(sid)
        a.carry(sid, c)

        result = await c.rescan()
        assert result["logs"]["unknownAnimals"] == ["remy1"]
        assert (result["logs"]["notes"], result["logs"]["weighIns"]) == (1, 0)
        notebook = await c.notebook()
        assert notebook["notes"][0]["scope"]["animalId"] == "a1"  # kept, under the id it came with
        assert notebook["health"] == []

        # The animal is added; the next read knows who the note is about.
        c.rig.cohorts.update(
            c.cohort_id,
            {"animals": [{"id": "c2", "name": "remy2", "boxNumber": 1},
                         {"id": "c1", "name": "Remy1", "boxNumber": 2}]},
        )
        result = await c.rescan()
        assert result["logs"]["unknownAnimals"] == []
        notebook = await c.notebook()
        assert notebook["notes"][0]["id"] == note_id
        assert notebook["notes"][0]["scope"]["animalId"] == "c1"
        assert notebook["health"][0]["animalId"] == "c1"
    finally:
        c.close()


# --- the file is read before it is written over ------------------------------------


async def test_a_folders_file_is_taken_in_before_it_is_rewritten(lab) -> None:
    """B has its own record of the day and a folder that came from A. Writing
    a note on B rewrites the file: A's note, never rescanned, must not be lost
    from it, or from B's log."""
    a, b = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    own = b.ran()
    a.carry(sid, b)

    mine = (await b.log.add_note(own, {"tag": "observation", "body": "Written on B."}))["note"]["id"]
    await b.log.drain()
    await b.log.drain()  # the read-in re-announces, and that mirror settles too

    notebook = await b.notebook()
    assert {n["id"] for n in notebook["notes"]} == {note_id, mine}
    on_disk = json.loads((b.folder(own) / "log.json").read_text(encoding="utf-8"))
    assert {n["id"] for s in on_disk["sessions"] for n in s["notes"]} == {note_id, mine}
    # But a mirror never records a session: only a rescan does.
    assert [s["id"] for s in on_disk["sessions"]] == [own]


async def test_a_newer_builds_file_is_neither_read_nor_written_over(lab) -> None:
    a, b = lab
    sid, _ = await _logged(a)
    document = a.wrote(sid)
    document["log_version"] = logfile.VERSION + 1
    document["something_new"] = True
    text = logfile.dumps(document)
    own = b.ran()
    (b.folder(own) / "log.json").write_text(text, encoding="utf-8")

    result = await b.rescan()
    assert (result["logs"]["files"], result["logs"]["unreadable"]) == (1, 1)
    await b.log.add_note(own, {"tag": "observation", "body": "Written on B."})
    await b.log.drain()
    assert (b.folder(own) / "log.json").read_text(encoding="utf-8") == text
    assert (b.folder(own) / "notes.md").is_file()  # the copy for a person is still kept


async def test_a_damaged_file_is_replaced_from_the_database(lab) -> None:
    a, _ = lab
    sid, note_id = await _logged(a)
    a.wrote(sid)
    (a.folder(sid) / "log.json").write_text('{"log_version": 1, "sessions": [', encoding="utf-8")
    assert (await a.rescan())["logs"]["unreadable"] == 1
    assert a.wrote(sid)["sessions"][0]["notes"][0]["id"] == note_id
