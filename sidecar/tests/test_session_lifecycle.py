"""The held session and its lifecycle — `sessions/lifecycle.py`,
`ARCHITECTURE.md#session-lifecycle`, `DATA.md#continuing-between-groups`,
`RECORDING.md#start-and-end`.

Drives `SessionLifecycle` through its interface over a real SQLite database,
with stand-ins for the runner, the recording and the utility baseline that
write to one ordered log, so the ordering rules are what the tests read.
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.intan.service import IntanNotReady
from ephymeris_sidecar.ports.manager import CarriedSketch, sketch_fingerprint
from ephymeris_sidecar.rig.definition import _ReadWriteLock
from ephymeris_sidecar.sessions.lifecycle import (
    BoxRefused,
    MappingEntry,
    SessionLifecycle,
    SessionRefused,
    SketchNotCarried,
)
from ephymeris_sidecar.sessions.models import GroupRun
from ephymeris_sidecar.sessions.repository import SessionRepository
from ephymeris_sidecar.sessions.runner import ActiveRun, BoxConfig

TODAY = date.today().isoformat()


class FakeRunner:
    """The runner's lifecycle-facing surface, with no ports behind it."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.group_id = ""
        self.session_id = ""
        self.configs: dict[int, BoxConfig] = {}
        self.running: set[int] = set()

    def configure(self, _folder, _label, group_id, box_configs, duration_s=None, *, session_id):  # noqa: ANN001
        self.group_id = group_id
        self.session_id = session_id
        self.configs = {c.box: c for c in box_configs}

    def configured_boxes(self) -> list[int]:
        return sorted(self.configs)

    def box_configs(self) -> list[BoxConfig]:
        return [self.configs[box] for box in sorted(self.configs)]

    def running_boxes(self) -> list[int]:
        return sorted(self.running)

    def start_box(self, box: int) -> None:
        if box not in self.configs:
            raise KeyError(box)
        self.log.append(f"start {box}")
        self.running.add(box)

    def stop_box(self, box: int) -> None:
        self.log.append(f"stop {box}")

    async def end_all(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        self.log.append("end boxes")
        self.running.clear()

    def clear(self) -> None:
        if self.running:
            raise RuntimeError("active runs")
        self.log.append("clear")
        self.group_id = ""
        self.session_id = ""
        self.configs = {}

    def snapshot(self) -> list[dict]:
        # The real SessionBox rows need a port behind them; the lifecycle
        # broadcast is validated against the schema, and an empty list passes.
        return []


class FakeIntan:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.configured = True
        self.is_recording = False
        self.force_stop = asyncio.Event()
        self.gate: asyncio.Event | None = None

    def configured_for(self, _session_id: str, _group_id: str) -> bool:
        return self.configured

    async def start_recording(self) -> None:
        self.log.append("rhx start")
        if self.gate is not None:
            await self.gate.wait()
        self.is_recording = True

    async def stop_recording(self) -> dict[str, Any]:
        self.log.append("rhx stop")
        self.is_recording = False
        return {"file": "run1.rhd"}

    def release(self) -> None:
        self.log.append("rhx release")

    def note_waiting(self, _boxes: list[int]) -> None:
        pass

    def box_ended(self, *_args) -> None:  # noqa: ANN002
        pass


class FakeUtility:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def hold(self) -> None:
        self.log.append("hold")

    def release(self) -> None:
        self.log.append("release")

    def ensure(self) -> None:
        self.log.append("ensure")

    async def publish(self) -> None:
        pass


class Rig:
    """One lifecycle and everything it was built from."""

    def __init__(self, db: Database, root: Path, *, intan: bool = False) -> None:
        self.log: list[str] = []
        self.events: list[dict] = []
        self.root = root
        self.sessions = SessionRepository(db)
        self.cohorts = CohortRepository(db)
        self.runner = FakeRunner(self.log)
        self.intan = FakeIntan(self.log) if intan else None
        self.utility = FakeUtility(self.log)
        #: What each box's board carries -- `PortManager.carried`'s record.
        self.carried: dict[int, CarriedSketch] = {}

        async def broadcast(message: dict) -> None:
            self.events.append(message)

        self.lifecycle = SessionLifecycle(
            sessions=self.sessions,
            cohorts=self.cohorts,
            runner=self.runner,
            intan=self.intan,
            utility=self.utility,
            profiles=None,
            logbook=None,
            rig_reading=_ReadWriteLock().reading,
            broadcast=broadcast,
            carried=self.carried.get,
        )
        self._cohorts = 0

    def session(self, day: str = TODAY, *, recording: bool = False):  # noqa: ANN201
        self._cohorts += 1
        name = f"C{self._cohorts}"
        cohort = self.cohorts.create(
            name,
            str(self.root / name),
            groups=[{"id": f"{name}-g", "name": "A", "order": 0}],
            animals=[
                {"id": f"{name}-1", "name": "remy1", "groupId": f"{name}-g", "boxNumber": 1},
                {"id": f"{name}-2", "name": "remy2", "groupId": f"{name}-g", "boxNumber": 2},
            ],
        )
        prefix = self.sessions.create_prefix(f"P{self._cohorts}")
        return self.sessions.create_session(
            cohort.id, prefix, "12", day, str(self.root / name / "s"), recording=recording
        )

    def sketch(self, name: str = "sketch") -> Path:
        folder = self.root / name
        if not folder.is_dir():
            folder.mkdir()
            (folder / f"{name}.ino").write_text(f"// {name}\n")
        return folder

    def mapping(self, session) -> list[MappingEntry]:  # noqa: ANN001
        cohort = self.cohorts.get(session.cohort_id)
        return [
            MappingEntry(box=a.box_number, animal_id=a.id, sketch_path=str(self.sketch()), config={})
            for a in cohort.animals
        ]

    def flash(self, box: int, folder: Path) -> None:
        """What a successful `PortManager.flash` records."""
        self.carried[box] = CarriedSketch(str(folder), sketch_fingerprint(str(folder)))

    async def confirm(self, session, group_id: str = "g-a", *, flash: bool = True) -> None:  # noqa: ANN001
        """Confirm, then flash every mapped box as the placement walk does."""
        entries = self.mapping(session)
        await self.lifecycle.confirm_mapping(session.id, group_id, entries)
        if flash:
            for entry in entries:
                self.flash(entry.box, Path(entry.sketch_path))

    async def run_group(self, session, group_id: str = "g-a") -> None:  # noqa: ANN001
        await self.confirm(session, group_id)
        await self.lifecycle.start_all(session.id)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def rig(db: Database, tmp_path: Path) -> Rig:
    return Rig(db, tmp_path)


@pytest.fixture
def recording_rig(db: Database, tmp_path: Path) -> Rig:
    return Rig(db, tmp_path, intan=True)


# --- confirm, hold, and the three questions ---------------------------------


async def test_confirming_a_mapping_holds_the_session_and_the_rig(rig) -> None:
    session = rig.session()
    assert not rig.lifecycle.in_use

    await rig.confirm(session)

    assert rig.lifecycle.held == session.id
    assert rig.lifecycle.in_use and not rig.lifecycle.writing
    assert rig.log == ["hold"]
    assert rig.runner.session_id == session.id
    assert rig.events[-1]["evt"] == "session.lifecycle"


async def test_status_reports_the_rig_only_for_the_session_holding_it(rig) -> None:
    held = rig.session()
    other = rig.session()
    await rig.confirm(held)
    rig.runner.snapshot = lambda: [{"box": 1}]

    assert (await rig.lifecycle.status(held.id))["boxes"] == [{"box": 1}]
    assert (await rig.lifecycle.status(held.id))["groupId"] == "g-a"
    # Another session's status must not carry the held one's animals and boxes.
    reply = await rig.lifecycle.status(other.id)
    assert reply["session"]["id"] == other.id
    assert (reply["groupId"], reply["boxes"]) == (None, [])


async def test_status_between_groups_reports_no_group(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    await rig.lifecycle.end_group(session.id)

    assert (await rig.lifecycle.status(session.id))["groupId"] is None


async def test_a_mapping_missing_its_animal_is_refused_and_holds_nothing(rig) -> None:
    session = rig.session()
    entry = MappingEntry(box=1, animal_id="nobody", sketch_path="/sk", config={})
    with pytest.raises(SessionRefused, match="missing"):
        await rig.lifecycle.confirm_mapping(session.id, "g-a", [entry])
    assert rig.lifecycle.held is None
    assert rig.log == []


async def test_the_questions_across_a_whole_session(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    assert (rig.lifecycle.held, rig.lifecycle.in_use, rig.lifecycle.writing) == (
        session.id, True, True,
    )
    await rig.lifecycle.end_group(session.id)
    # Between groups: still held, nothing writing.
    assert (rig.lifecycle.held, rig.lifecycle.in_use, rig.lifecycle.writing) == (
        session.id, True, False,
    )
    await rig.lifecycle.end(session.id)
    assert (rig.lifecycle.held, rig.lifecycle.in_use, rig.lifecycle.writing) == (
        None, False, False,
    )


async def test_starting_a_box_with_no_mapping_names_the_box(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    with pytest.raises(BoxRefused) as refused:
        await rig.lifecycle.start_box(5)
    assert refused.value.box == 5
    assert isinstance(refused.value.__cause__, KeyError)


# --- what the boards carry (ARCHITECTURE.md#what-a-board-carries) ------------


async def test_start_all_refuses_a_box_never_flashed_and_starts_nothing(rig) -> None:
    session = rig.session()
    await rig.confirm(session, flash=False)
    rig.flash(1, rig.sketch())

    with pytest.raises(SketchNotCarried) as refused:
        await rig.lifecycle.start_all(session.id)

    assert refused.value.boxes == [2]
    assert "box 2 has not been flashed" in str(refused.value)
    # Box 1 was fine, and still did not start: a half-started group is worse.
    assert rig.log == ["hold"]
    stored = rig.sessions.get_session(session.id)
    assert (stored.status, stored.group_runs) == ("configuring", [])


async def test_the_refusal_comes_before_the_recording_starts(recording_rig) -> None:
    session = recording_rig.session(recording=True)
    await recording_rig.confirm(session, flash=False)

    with pytest.raises(SketchNotCarried) as refused:
        await recording_rig.lifecycle.start_all(session.id)

    assert refused.value.boxes == [1, 2]
    assert "rhx start" not in recording_rig.log


async def test_a_box_carrying_another_sketch_is_refused_by_name(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    rig.flash(1, rig.sketch("BOX_Utility"))

    with pytest.raises(SketchNotCarried, match="box 1 carries BOX_Utility, not sketch"):
        await rig.lifecycle.start_box(1)
    assert "start 1" not in rig.log

    await rig.lifecycle.start_box(2)
    assert "start 2" in rig.log


async def test_a_folder_rebuilt_since_the_flash_is_refused_until_reflashed(rig) -> None:
    """A wiring save or a task save rewrites the folder in place: same path, and
    the board still runs the old pins."""
    session = rig.session()
    await rig.confirm(session)
    (rig.sketch() / "TaskPins.h").write_text("#define VALVE 7\n")

    with pytest.raises(SketchNotCarried, match="older build of sketch"):
        await rig.lifecycle.start_box(1)

    rig.flash(1, rig.sketch())
    await rig.lifecycle.start_box(1)
    assert rig.log[-1] == "start 1"


async def test_the_same_folder_spelled_differently_is_the_same_sketch(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    folder = rig.sketch()
    spelled = f"{folder.parent}/./{folder.name}/"
    rig.carried[1] = CarriedSketch(spelled, sketch_fingerprint(str(folder)))

    await rig.lifecycle.start_box(1)
    assert rig.log[-1] == "start 1"


async def test_a_running_box_is_not_checked_again(rig) -> None:
    """Start All after a per-box start must not refuse the box already running
    because its board has since been forgotten -- starting it is a no-op."""
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(1)
    rig.carried.pop(1)

    await rig.lifecycle.start_all(session.id)
    assert "start 2" in rig.log


# --- abandon ------------------------------------------------------------------


async def test_abandoning_drops_the_mapping_and_hands_the_rig_back(rig) -> None:
    session = rig.session()
    await rig.confirm(session)

    abandoned = await rig.lifecycle.abandon(session.id)

    assert abandoned.status == "aborted"
    assert rig.lifecycle.held is None
    assert rig.runner.configured_boxes() == []
    assert rig.log == ["hold", "clear", "release", "ensure"]


async def test_a_session_that_ran_cannot_be_abandoned(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    with pytest.raises(SessionRefused, match="only a configuring session"):
        await rig.lifecycle.abandon(session.id)


# --- recording order (RECORDING.md#start-and-end) -----------------------------


async def test_the_recording_starts_before_any_box(recording_rig) -> None:
    rig = recording_rig
    session = rig.session(recording=True)
    await rig.run_group(session)
    assert rig.log == ["hold", "rhx start", "start 1", "start 2"]


async def test_a_recording_not_set_up_refuses_before_any_box_starts(recording_rig) -> None:
    rig = recording_rig
    rig.intan.configured = False
    session = rig.session(recording=True)
    await rig.confirm(session)
    with pytest.raises(IntanNotReady):
        await rig.lifecycle.start_all(session.id)
    with pytest.raises(IntanNotReady):
        await rig.lifecycle.start_box(1)
    assert rig.runner.running_boxes() == []
    assert rig.sessions.get_session(session.id).group_runs == []


async def test_ending_stops_the_boxes_then_rhx_then_lets_go(recording_rig) -> None:
    rig = recording_rig
    session = rig.session(recording=True)
    await rig.run_group(session)
    rig.log.clear()

    ended = await rig.lifecycle.end(session.id)

    assert rig.log == ["end boxes", "rhx stop", "clear", "release", "ensure"]
    assert ended.status == "completed"
    assert ended.group_runs[0].ended_at is not None
    assert rig.sessions.get_session(session.id).recording["runs"] == [{"file": "run1.rhd"}]


async def test_a_second_transition_waits_for_a_recording_start(recording_rig) -> None:
    """Starting RHX can take seconds; an End pressed meanwhile must not run
    inside it and end boxes that haven't started."""
    rig = recording_rig
    rig.intan.gate = asyncio.Event()
    session = rig.session(recording=True)
    await rig.confirm(session)

    starting = asyncio.create_task(rig.lifecycle.start_all(session.id))
    await asyncio.sleep(0.01)
    ending = asyncio.create_task(rig.lifecycle.end(session.id))
    await asyncio.sleep(0.01)
    assert not ending.done()
    rig.intan.gate.set()
    await asyncio.gather(starting, ending)

    assert rig.log == [
        "hold", "rhx start", "start 1", "start 2",
        "end boxes", "rhx stop", "clear", "release", "ensure",
    ]


# --- a finishing run records against its own session ---------------------------


async def test_a_run_that_lands_after_the_session_let_go_is_still_recorded(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    await rig.lifecycle.end(session.id)
    assert rig.lifecycle.held is None

    config = BoxConfig(
        box=1,
        animal_id="C1-1",
        animal_name="remy1",
        sketch_path="/sk",
        sketch_name="sk",
        start_command="START",
        config_metadata={},
        profile=None,
    )
    late = ActiveRun(
        box=1,
        config=config,
        run_id="r-late",
        started_at="2026-10-10T10:00:00+00:00",
        address="/dev/fake1",
        session_id_label="P1_12",
        session_id=session.id,
    )
    await rig.lifecycle.animal_ended(late, "end")

    assert [r.id for r in rig.sessions.runs_for(session.id)] == ["r-late"]
    assert rig.events[-1]["evt"] == "session.animalEnded"


# --- groups on the fly (ARCHITECTURE.md#group-step) ----------------------------


async def test_end_group_leaves_the_session_running_between_groups(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    rig.log.clear()

    ended = await rig.lifecycle.end_group(session.id)

    assert ended.status == "running"
    assert ended.group_runs[0].ended_at is not None
    # Held, but the finished group's mapping is gone: a reload must not offer
    # Start All on animals already carried home.
    assert rig.lifecycle.held == session.id
    assert rig.runner.configured_boxes() == []
    assert rig.runner.group_id == ""
    # The operator walks the rig for the next group, which wants the lights.
    assert rig.log == ["end boxes", "clear", "release", "ensure"]


async def test_the_operator_may_run_groups_in_any_order_and_repeat_one(rig) -> None:
    session = rig.session()
    for group in ("g-b", "g-a", "g-b"):
        await rig.run_group(session, group)
        await rig.lifecycle.end_group(session.id)

    runs = rig.sessions.get_session(session.id).group_runs
    assert [r.group_id for r in runs] == ["g-b", "g-a", "g-b"]
    assert all(r.ended_at is not None for r in runs)


async def test_start_all_after_a_per_box_start_is_one_group_run(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(1)
    await rig.lifecycle.start_all(session.id)
    assert len(rig.sessions.get_session(session.id).group_runs) == 1


async def test_a_per_box_start_records_the_group_run(rig) -> None:
    """Boxes started one at a time used to leave no group run and the status at
    `configuring` — so the group step could not badge the group, and Back on the
    next mapping discarded a session with real data in it."""
    session = rig.session()
    await rig.confirm(session)

    await rig.lifecycle.start_box(1)

    stored = rig.sessions.get_session(session.id)
    assert stored.status == "running"
    assert [r.group_id for r in stored.group_runs] == ["g-a"]


# --- resume (DATA.md#continuing-between-groups) -------------------------------


async def test_a_session_ended_too_early_can_be_continued_today(rig) -> None:
    session = rig.session()
    await rig.run_group(session)
    await rig.lifecycle.end(session.id)
    assert rig.sessions.get_session(session.id).status == "completed"

    resumed = await rig.lifecycle.resume(session.id)

    assert resumed.status == "running"
    assert rig.lifecycle.held == session.id
    assert rig.runner.configured_boxes() == []


async def test_a_crash_orphan_is_continued_with_its_open_group_closed(rig) -> None:
    session = rig.session()
    rig.sessions.set_group_runs(
        session.id, [GroupRun(group_id="g-a", order=0, started_at="2026-09-25T10:00:00")]
    )
    rig.sessions.set_status(session.id, "running")
    # A relaunched sidecar holds nothing.
    assert rig.lifecycle.held is None

    await rig.lifecycle.resume(session.id)

    runs = rig.sessions.get_session(session.id).group_runs
    assert runs[0].ended_at is not None
    assert rig.lifecycle.held == session.id


async def test_resume_refuses_another_days_session(rig) -> None:
    session = rig.session(day="2020-01-01")
    rig.sessions.set_group_runs(
        session.id, [GroupRun(group_id="g-a", order=0, started_at="x", ended_at="y")]
    )
    rig.sessions.set_status(session.id, "completed")
    with pytest.raises(SessionRefused, match="today"):
        await rig.lifecycle.resume(session.id)


async def test_resume_refuses_a_session_that_never_ran_a_group(rig) -> None:
    session = rig.session()
    rig.sessions.set_status(session.id, "completed")
    with pytest.raises(SessionRefused, match="never ran a group"):
        await rig.lifecycle.resume(session.id)


async def test_resume_refuses_while_another_session_is_open(rig) -> None:
    first = rig.session()
    await rig.run_group(first)
    await rig.lifecycle.end(first.id)

    live = rig.session()
    await rig.run_group(live)

    with pytest.raises(SessionRefused, match="another session"):
        await rig.lifecycle.resume(first.id)


async def test_closing_out_an_orphan_leaves_the_live_session_alone(rig) -> None:
    orphan = rig.session()
    rig.sessions.set_status(orphan.id, "running")
    live = rig.session()
    await rig.run_group(live)
    rig.log.clear()

    await rig.lifecycle.end(orphan.id)

    assert rig.log == []
    assert rig.lifecycle.held == live.id
    assert rig.runner.configured_boxes() == [1, 2]


# --- the handlers' error mapping (app.py) ---------------------------------------


def _mapped(exc: BaseException):  # noqa: ANN202
    from ephymeris_sidecar.app import _lifecycle_errors

    with pytest.raises(Exception) as raised:
        with _lifecycle_errors():
            raise exc
    return raised.value


def _box_refused(box: int, cause: BaseException) -> BoxRefused:
    try:
        raise BoxRefused(box) from cause
    except BoxRefused as exc:
        return exc


def test_each_refusal_reaches_the_wire_with_its_code() -> None:
    from ephymeris_sidecar.server import CommandError
    from ephymeris_sidecar.sessions.lifecycle import MappingRefused

    cases = [
        (SessionRefused("no"), "SESSION_INVALID", None),
        (MappingRefused(3, "too long"), "TASK_PROFILE_INVALID", {"box": 3}),
        (IntanNotReady("set it up"), "INTAN_NOT_READY", None),
        (_box_refused(4, KeyError(4)), "SESSION_INVALID", {"box": 4}),
        (SketchNotCarried("flash them", [2, 5]), "SESSION_INVALID", {"boxes": [2, 5]}),
    ]
    for exc, code, data in cases:
        mapped = _mapped(exc)
        assert isinstance(mapped, CommandError), exc
        assert mapped.code == code
        if data is not None:
            assert mapped.detail == data


def test_a_box_failure_nobody_names_surfaces_as_itself() -> None:
    assert isinstance(_mapped(_box_refused(2, ValueError("odd"))), ValueError)
