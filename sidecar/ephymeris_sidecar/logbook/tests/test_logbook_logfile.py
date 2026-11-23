"""The session folder's `log.json`, as a format — `DATA.md#the-log-file`.

What goes in, that it comes back out the same, and that nothing unreadable is
ever guessed at. `test_log_travels.py` covers what is done with it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ephymeris_sidecar.logbook import logfile
from ephymeris_sidecar.logbook.models import HealthEntry, SessionLog, SessionNote
from ephymeris_sidecar.sessions.models import Round, Session

DAY = "2026-07-22"
T0 = "2026-07-22T09:00:00.000+00:00"
T1 = "2026-07-22T09:30:00.000+00:00"
T2 = "2026-07-22T10:00:00.000+00:00"


def _session(sid: str = "s1") -> Session:
    return Session(
        id=sid, cohort_id="c", prefix_id="p", prefix_name="2O-Bdisc", session_number="12",
        date=DAY, started_at=T0, status="completed", folder_path="/x", ended_at=T2,
        rounds=[Round(0, T0, T2)],
    )


def _note(nid: str, **kw) -> SessionNote:
    return SessionNote(
        id=nid, session_id="s1", cohort_id="c", at=kw.pop("at", T1), created_at=kw.pop("created_at", T1),
        tag=kw.pop("tag", "observation"), body=kw.pop("body", "note"), **kw,
    )


def _document(**kw) -> dict:
    return logfile.build(
        cohort_name="Batch A",
        sessions=kw.get("sessions", [_session()]),
        logs=kw.get("logs", [SessionLog("s1", operator="CJ", summary="Fine.", updated_at=T2)]),
        notes=kw.get("notes", [_note("n1", scope_kind="animal", animal_id="a1", carry_forward=True)]),
        weights=kw.get("weights", [HealthEntry("a1", DAY, 312.4, True, T0)]),
        animal_names={"a1": "remy1"},
    )


def test_a_log_comes_back_as_it_was_written() -> None:
    read = logfile.parse(logfile.dumps(_document()))
    assert read is not None
    (session,) = read.sessions
    assert (session.id, session.prefix, session.number, session.date) == ("s1", "2O-Bdisc", "12", DAY)
    assert (session.operator, session.summary, session.log_updated_at) == ("CJ", "Fine.", T2)
    assert session.rounds == ({"order": 0, "started_at": T0, "ended_at": T2, "label": None},)
    (note,) = session.notes
    assert (note.id, note.body, note.scope_kind, note.carry_forward) == ("n1", "note", "animal", True)
    (weigh_in,) = read.weigh_ins
    assert (weigh_in.weight_g, weigh_in.baseline, weigh_in.recorded_at) == (312.4, True, T0)


def test_animals_are_named_since_an_id_is_one_machines_own() -> None:
    read = logfile.parse(logfile.dumps(_document()))
    assert read is not None
    assert (read.sessions[0].notes[0].animal, read.sessions[0].notes[0].animal_id) == ("remy1", "a1")
    assert (read.weigh_ins[0].animal, read.weigh_ins[0].animal_id) == ("remy1", "a1")


def test_what_was_deleted_leaves_a_marker_and_none_of_its_content() -> None:
    document = _document(
        notes=[_note("gone", body="a secret", deleted_at=T2)],
        weights=[HealthEntry("a1", DAY, 312.4, False, T0, removed_at=T2)],
    )
    text = logfile.dumps(document)
    assert "a secret" not in text and "312.4" not in text
    read = logfile.parse(text)
    assert read is not None
    assert read.sessions[0].notes == (logfile.FileNote(id="gone", deleted_at=T2),)
    assert read.weigh_ins[0].removed_at == T2


def test_an_unchanged_log_is_written_byte_for_byte_the_same(tmp_path: Path) -> None:
    """No "written at": an unchanged session costs no write and no backup copy."""
    text = logfile.dumps(_document())
    assert logfile.dumps(_document()) == text
    assert logfile.write(tmp_path, text) == tmp_path / "log.json"
    assert logfile.write(tmp_path, text) is None
    assert not (tmp_path / "log.json.part").exists()


def test_a_note_is_as_new_as_the_last_thing_that_happened_to_it() -> None:
    assert _stamp(created_at=T0) == T0
    assert _stamp(created_at=T0, edited_at=T1) == T1
    assert _stamp(created_at=T0, edited_at=T1, resolved_at=T2, carry_forward=True) == T2


def _stamp(**kw) -> str | None:
    read = logfile.parse(logfile.dumps(_document(notes=[_note("n", **kw)])))
    assert read is not None
    return read.sessions[0].notes[0].stamp


def test_newer_is_judged_as_instants_not_as_strings() -> None:
    # The same moment, spelled by two machines in two zones.
    utc, local = "2026-07-22T14:00:00.000+00:00", "2026-07-22T09:00:00.000-05:00"
    assert not logfile.newer(utc, local) and not logfile.newer(local, utc)
    assert logfile.newer("2026-07-22T09:00:01.000-05:00", utc)
    assert logfile.newer(utc, None) and not logfile.newer(None, utc)
    assert logfile.latest(None, "not a time") is None


def test_a_file_from_a_newer_build_is_not_read() -> None:
    document = _document()
    document["log_version"] = logfile.VERSION + 1
    text = logfile.dumps(document)
    assert logfile.parse(text) is None
    assert logfile.from_newer_build(text)
    assert not logfile.from_newer_build(logfile.dumps(_document()))
    assert not logfile.from_newer_build("{ not json")


def test_what_is_not_a_log_file_is_no_log_file(tmp_path: Path) -> None:
    for text in ("", "{ not json", "[]", "{}", json.dumps({"log_version": "1"})):
        assert logfile.parse(text) is None
    assert logfile.read(tmp_path) == (None, None)
    (tmp_path / "log.json").write_text("{ not json", encoding="utf-8")
    assert logfile.read(tmp_path) == (None, "{ not json")


def test_one_bad_entry_does_not_cost_the_rest() -> None:
    document = _document()
    document["sessions"][0]["notes"].append({"id": "half", "body": 7})
    document["sessions"].append({"id": "nameless"})
    document["weigh_ins"].append({"animal": "remy2", "date": DAY, "weight_g": "heavy"})
    read = logfile.parse(logfile.dumps(document))
    assert read is not None
    assert [s.id for s in read.sessions] == ["s1"]
    assert [n.id for n in read.sessions[0].notes] == ["n1"]
    assert len(read.weigh_ins) == 1
