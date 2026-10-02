"""Tidying a cohort's session records — `DATA.md#tidy-records`.

A day that goes wrong leaves two shapes behind: the same session split across
two records that write into one folder, and records with nothing behind them.
These pin what the tidy does to each, and — the half that matters more — what
it refuses to touch: the held session, a set-up started today, an unreachable
folder, and any file at all.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ephymeris_sidecar.analytics.service import _adoption_owners
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.sessions import tidy
from ephymeris_sidecar.sessions.models import GroupRun
from tests.test_analytics_service import HIT_1, HIT_3, Rig

TODAY = date.today().isoformat()
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


def started(rig: Rig, session_id: str, at: str) -> str:
    """Pin a record's creation time — two made in one test share a second."""
    rig.db.conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?", (at, session_id))
    rig.db.conn.commit()
    return session_id


def group_run(group_id: str, at: str) -> GroupRun:
    return GroupRun(group_id=group_id, order=0, started_at=at, ended_at=at)


async def preview(rig: Rig, **kw) -> dict:
    return await rig.service.tidy(
        rig.cohort.id, apply=False, protect=kw.get("protect", set()), today=kw.get("today", TODAY)
    )


async def apply(rig: Rig, **kw) -> dict:
    return await rig.service.tidy(
        rig.cohort.id, apply=True, protect=kw.get("protect", set()), today=kw.get("today", TODAY)
    )


# --- merging a split day -----------------------------------------------------


async def test_two_records_of_one_session_merge_into_the_earliest(rig: Rig) -> None:
    first = started(rig, rig.add_session("12", DAY), "2026-07-22T08:55:00")
    second = started(rig, rig.add_session("12", DAY), "2026-07-22T12:55:00")
    rig.sessions.set_group_runs(first, [group_run("gA", "2026-07-22T09:00:00")])
    rig.sessions.set_group_runs(second, [group_run("gB", "2026-07-22T13:00:00")])
    rig.add_run(first, "a1", HIT_1 * 5)
    rig.add_run(second, "a2", HIT_3 * 5)

    plan = await preview(rig)
    assert [m["keep"]["sessionId"] for m in plan["merges"]] == [first]
    assert [s["sessionId"] for s in plan["merges"][0]["absorb"]] == [second]

    done = await apply(rig)
    assert done["applied"] is True
    assert done["merges"][0]["keep"]["runCount"] == 2

    kept = rig.sessions.get_session(first)
    assert [r.group_id for r in kept.group_runs] == ["gA", "gB"]
    assert [r.order for r in kept.group_runs] == [0, 1]
    assert {r.session_id for r in rig.sessions.runs_for_cohort(rig.cohort.id)} == {first}
    assert [s.id for s in rig.sessions.list_sessions(rig.cohort.id)] == [first]

    # One session on the day, with both animals' runs under it.
    summary = await rig.service.summary(rig.cohort.id)
    assert [s["id"] for s in summary["sessions"]] == [first]
    assert {r["sessionId"] for r in summary["runs"]} == {first}


async def test_a_preview_changes_nothing(rig: Rig) -> None:
    first = rig.add_session("12", DAY)
    second = rig.add_session("12", DAY)
    rig.add_run(first, "a1", HIT_1)
    rig.add_run(second, "a2", HIT_1)
    await preview(rig)
    assert len(rig.sessions.list_sessions(rig.cohort.id)) == 2


async def test_different_numbers_are_never_merged(rig: Rig) -> None:
    """Same-number only: a different number is a different folder, and a merge
    across folders would leave files belonging to a session they are not in."""
    first = rig.add_session("12", DAY)
    other = rig.add_session("13", DAY)
    rig.add_run(first, "a1", HIT_1)
    rig.add_run(other, "a2", HIT_1)
    assert (await preview(rig))["merges"] == []


async def test_the_earliest_record_WITH_DATA_is_kept(rig: Rig) -> None:
    """An empty set-up created first must not become the day's session."""
    empty = rig.add_session("12", DAY)
    real = rig.add_session("12", DAY)
    rig.add_run(real, "a1", HIT_1)
    plan = await preview(rig)
    assert plan["merges"][0]["keep"]["sessionId"] == real
    assert [s["sessionId"] for s in plan["merges"][0]["absorb"]] == [empty]


async def test_recording_runs_from_every_record_are_kept(rig: Rig) -> None:
    first = started(rig, rig.add_session("12", DAY), "2026-07-22T08:55:00")
    second = started(rig, rig.add_session("12", DAY), "2026-07-22T12:55:00")
    rig.add_run(first, "a1", HIT_1)
    rig.sessions.set_recording(second, {"runs": [{"groupId": "gB", "startedAt": "t2"}]})
    rig.sessions.set_recording(first, {"runs": [{"groupId": "gA", "startedAt": "t1"}]})
    await apply(rig)
    kept = rig.sessions.get_session(first)
    assert [r["groupId"] for r in kept.recording["runs"]] == ["gA", "gB"]


# --- empty records ---------------------------------------------------------


async def test_an_empty_record_is_deleted_with_its_empty_folder(rig: Rig) -> None:
    sid = rig.add_session("12", DAY)
    folder = Path(rig.sessions.get_session(sid).folder_path)
    (folder / "behavior.json").mkdir(parents=True)  # the skeleton, no files

    plan = await preview(rig)
    assert [e["session"]["sessionId"] for e in plan["empty"]] == [sid]
    assert plan["empty"][0]["removesFolder"] is True

    await apply(rig)
    assert rig.sessions.list_sessions(rig.cohort.id, include_aborted=True) == []
    assert not folder.exists()


async def test_a_folder_with_any_file_is_data_and_is_never_removed(rig: Rig) -> None:
    """A crash's .tsv with no run record yet is still data — it is what
    `sessions.recover` rebuilds from."""
    sid = rig.add_session("12", DAY)
    folder = Path(rig.sessions.get_session(sid).folder_path) / "behavior.tsv"
    folder.mkdir(parents=True)
    (folder / "remy1_2O-Bdisc_12_2026-07-22_101500.tsv").write_text("101\t0\n")

    assert (await preview(rig))["empty"] == []
    await apply(rig)
    assert rig.sessions.get_session(sid)
    assert folder.exists()


async def test_an_unreachable_folder_is_never_read_as_empty(rig: Rig, monkeypatch) -> None:
    """An unmounted drive says nothing about what the folder holds (`DATA.md#pruning`'s
    reachable-and-absent rule, the prune's own)."""
    from ephymeris_sidecar.analytics import service

    rig.add_session("12", DAY)
    monkeypatch.setattr(service, "_folder_state", lambda _path: None)
    assert (await preview(rig))["empty"] == []


async def test_an_aborted_or_old_set_up_record_is_cleared(rig: Rig) -> None:
    aborted = rig.add_session("12", DAY)
    rig.sessions.set_status(aborted, "aborted")
    old_setup = rig.add_session("13", DAY)
    rig.sessions.set_status(old_setup, "configuring")
    plan = await preview(rig)
    assert {e["session"]["sessionId"] for e in plan["empty"]} == {aborted, old_setup}


# --- what is never touched -------------------------------------------------


async def test_the_held_session_and_its_folder_mates_are_left_whole(rig: Rig) -> None:
    earlier = started(rig, rig.add_session("12", DAY), "2026-07-22T08:55:00")
    held = started(rig, rig.add_session("12", DAY), "2026-07-22T12:55:00")
    rig.add_run(earlier, "a1", HIT_1)
    plan = await preview(rig, protect={held})
    assert plan["merges"] == [] and plan["empty"] == []
    assert {s["session"]["sessionId"] for s in plan["skipped"]} == {held, earlier}


async def test_a_set_up_started_today_is_left_alone(rig: Rig) -> None:
    """Step 1 creates the record before the mapping holds the rig, so today's
    `configuring` row may be under an operator's hands right now."""
    sid = rig.add_session("12", TODAY)
    rig.sessions.set_status(sid, "configuring")
    assert (await preview(rig))["empty"] == []


# --- recovered files count under their session -----------------------------


def _orphan(rig: Rig, number: str, day: str, animal: str) -> Path:
    folder = rig.root / "2O-Bdisc" / f"2O-Bdisc_{number}_{day}" / "behavior.json"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{animal}_2O-Bdisc_{number}_{day}_101500.json"
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


async def test_a_recovered_file_counts_under_the_recorded_session(rig: Rig) -> None:
    """A crash leaves a file with no run record; recovery adopts it under a
    synthetic `adopted:` session. When this database recorded that session, the
    day used to appear twice in Analytics — it is one session."""
    sid = rig.add_session("12", DAY)
    rig.add_run(sid, "a1", HIT_1)
    _orphan(rig, "12", DAY, "remy2")
    await rig.service.rescan(rig.cohort.id)

    summary = await rig.service.summary(rig.cohort.id)
    assert [s["id"] for s in summary["sessions"]] == [sid]
    assert {r["sessionId"] for r in summary["runs"]} == {sid}
    assert len(summary["runs"]) == 2


async def test_a_recovered_file_makes_its_record_not_empty(rig: Rig) -> None:
    sid = rig.add_session("12", DAY)
    _orphan(rig, "12", DAY, "remy2")
    await rig.service.rescan(rig.cohort.id)
    assert (await preview(rig))["empty"] == []
    assert rig.sessions.get_session(sid)


def test_an_orphan_from_another_session_keeps_its_own_entry(rig: Rig) -> None:
    sid = rig.add_session("12", DAY)
    from ephymeris_sidecar.analytics.repository import AdoptedRun

    entry = AdoptedRun(
        id="x", cohort_id=rig.cohort.id, animal_id="a1", file_path="/f",
        prefix_name="2O-Bdisc", session_number="13", date=DAY,
        started_at="t", sketch_name=None, sketch_path=None,
    )
    assert _adoption_owners([entry], [rig.sessions.get_session(sid)]) == {}


# --- the planner alone -----------------------------------------------------


def test_the_session_key_is_the_folder_name() -> None:
    """Two spellings that make one folder are one session."""
    assert tidy.session_key("2O-Bdisc", " 12", DAY) == tidy.session_key("2o-bdisc", "12", DAY)
    assert tidy.session_key("2O-Bdisc", "12", DAY) != tidy.session_key("2O-Bdisc", "12", "2026-07-23")
