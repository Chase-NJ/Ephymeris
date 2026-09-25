"""Choosing groups on the fly, and continuing between groups — `dashboard.md` §5.2.

Drives the real `Application` handlers over a real `SessionRepository`, on a
stand-in for the rest of the app (the `test_debug_flash.py` pattern):
constructing `Application` spawns a board tool, and the handlers under test
read only the session repository, the runner and a broadcast.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.server import CommandError
from ephymeris_sidecar.sessions.models import GroupRun
from ephymeris_sidecar.sessions.repository import SessionRepository

TODAY = date.today().isoformat()


class FakeRunner:
    """The runner's session-facing surface, with no ports behind it."""

    def __init__(self) -> None:
        self.group_id = ""
        self.boxes: list[int] = []
        self.started: list[int] = []
        self.ended = 0

    def configure(self, group_id: str, boxes: list[int]) -> None:
        self.group_id = group_id
        self.boxes = list(boxes)

    def configured_boxes(self) -> list[int]:
        return list(self.boxes)

    def start_box(self, box: int) -> None:
        self.started.append(box)

    async def end_all(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        self.ended += 1

    def clear(self) -> None:
        self.group_id = ""
        self.boxes = []

    def snapshot(self) -> list[dict]:
        # The real SessionBox rows need a port behind them; the lifecycle
        # broadcast is validated against the schema, and an empty list passes.
        return []


class FakePorts:
    def handler(self, _box: int) -> SimpleNamespace:
        return SimpleNamespace(state=SimpleNamespace(value="IN_SESSION"))


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def app(db: Database) -> SimpleNamespace:
    events: list[dict] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    stub = SimpleNamespace(
        sessions=SessionRepository(db),
        cohorts=CohortRepository(db),
        runner=FakeRunner(),
        ports=FakePorts(),
        intan=None,
        utility=None,
        server=SimpleNamespace(broadcast=broadcast),
        events=events,
        _running_session_id=None,
    )
    # The handlers call these as methods; bind the real ones to the stand-in.
    for name in (
        "_require_runner",
        "_require_ports",
        "_end_all_boxes",
        "_close_group_run",
        "_open_group_run",
        "_clear_runner",
        "_release_baseline",
        "_broadcast_lifecycle",
        "_begin_recording_if_any",
        "_is_recording_session",
    ):
        setattr(stub, name, getattr(Application, name).__get__(stub))
    return stub


def make_session(app, day: str = TODAY):  # noqa: ANN001, ANN201
    cohort = app.cohorts.create("C", "/tmp/c")
    prefix = app.sessions.create_prefix("2O-Bdisc")
    return app.sessions.create_session(cohort.id, prefix, "12", day, "/tmp/f")


async def call(app, handler: str, **args):  # noqa: ANN001, ANN003, ANN201
    return await getattr(Application, handler)(app, None, None, args, None)


async def run_group(app, session_id: str, group_id: str) -> None:  # noqa: ANN001
    app.runner.configure(group_id, [1, 2])
    app._running_session_id = session_id
    await call(app, "_sessions_start_all", sessionId=session_id)


# --- sessions.endGroup ------------------------------------------------------


async def test_end_group_leaves_the_session_running_between_groups(app) -> None:
    session = make_session(app)
    await run_group(app, session.id, "g-a")

    reply = await call(app, "_sessions_end_group", sessionId=session.id)

    assert reply["session"]["status"] == "running"
    assert reply["session"]["groupRuns"][0]["endedAt"] is not None
    # Held, but the finished group's mapping is gone: a reload must not offer
    # Start All on animals already carried home.
    assert app._running_session_id == session.id
    assert app.runner.configured_boxes() == []
    assert app.runner.group_id == ""


async def test_the_operator_may_run_groups_in_any_order_and_repeat_one(app) -> None:
    session = make_session(app)
    for group in ("g-b", "g-a", "g-b"):
        await run_group(app, session.id, group)
        await call(app, "_sessions_end_group", sessionId=session.id)

    runs = app.sessions.get_session(session.id).group_runs
    assert [r.group_id for r in runs] == ["g-b", "g-a", "g-b"]
    assert all(r.ended_at is not None for r in runs)


async def test_start_all_after_a_per_box_start_is_one_group_run(app) -> None:
    session = make_session(app)
    app.runner.configure("g-a", [1, 2])
    app._running_session_id = session.id
    await call(app, "_port_start_session", box=1)
    await call(app, "_sessions_start_all", sessionId=session.id)
    assert len(app.sessions.get_session(session.id).group_runs) == 1


async def test_a_per_box_start_records_the_group_run(app) -> None:
    """Boxes started one at a time used to leave no group run and the status at
    `configuring` — so the group step could not badge the group, and Back on the
    next mapping discarded a session with real data in it."""
    session = make_session(app)
    app.runner.configure("g-a", [1, 2])
    app._running_session_id = session.id

    await call(app, "_port_start_session", box=1)

    stored = app.sessions.get_session(session.id)
    assert stored.status == "running"
    assert [r.group_id for r in stored.group_runs] == ["g-a"]


# --- sessions.resume --------------------------------------------------------


async def test_a_session_ended_too_early_can_be_continued_today(app) -> None:
    session = make_session(app)
    await run_group(app, session.id, "g-a")
    await call(app, "_sessions_end", sessionId=session.id)
    assert app.sessions.get_session(session.id).status == "completed"

    reply = await call(app, "_sessions_resume", sessionId=session.id)

    assert reply["session"]["status"] == "running"
    assert app._running_session_id == session.id
    assert app.runner.configured_boxes() == []


async def test_a_crash_orphan_is_continued_with_its_open_group_closed(app) -> None:
    session = make_session(app)
    app.sessions.set_group_runs(
        session.id, [GroupRun(group_id="g-a", order=0, started_at="2026-09-25T10:00:00")]
    )
    app.sessions.set_status(session.id, "running")
    # A relaunched sidecar holds nothing.
    assert app._running_session_id is None

    await call(app, "_sessions_resume", sessionId=session.id)

    runs = app.sessions.get_session(session.id).group_runs
    assert runs[0].ended_at is not None
    assert app._running_session_id == session.id


async def test_resume_refuses_another_days_session(app) -> None:
    session = make_session(app, day="2020-01-01")
    app.sessions.set_group_runs(
        session.id, [GroupRun(group_id="g-a", order=0, started_at="x", ended_at="y")]
    )
    app.sessions.set_status(session.id, "completed")
    with pytest.raises(CommandError, match="today"):
        await call(app, "_sessions_resume", sessionId=session.id)


async def test_resume_refuses_a_session_that_never_ran_a_group(app) -> None:
    session = make_session(app)
    app.sessions.set_status(session.id, "completed")
    with pytest.raises(CommandError, match="never ran a group"):
        await call(app, "_sessions_resume", sessionId=session.id)


async def test_resume_refuses_while_another_session_is_open(app) -> None:
    first = make_session(app)
    await run_group(app, first.id, "g-a")
    await call(app, "_sessions_end", sessionId=first.id)

    cohort = app.cohorts.create("D", "/tmp/d")
    prefix = app.sessions.create_prefix("Shaping")
    live = app.sessions.create_session(cohort.id, prefix, "3", TODAY, "/tmp/g")
    await run_group(app, live.id, "g-x")

    with pytest.raises(CommandError, match="another session"):
        await call(app, "_sessions_resume", sessionId=first.id)


async def test_closing_out_an_orphan_leaves_the_live_session_alone(app) -> None:
    orphan = make_session(app)
    app.sessions.set_status(orphan.id, "running")
    cohort = app.cohorts.create("D", "/tmp/d")
    prefix = app.sessions.create_prefix("Shaping")
    live = app.sessions.create_session(cohort.id, prefix, "3", TODAY, "/tmp/g")
    await run_group(app, live.id, "g-x")

    await call(app, "_sessions_end", sessionId=orphan.id)

    assert app.runner.ended == 0
    assert app._running_session_id == live.id
    assert app.runner.configured_boxes() == [1, 2]
