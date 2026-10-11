"""The held session and its lifecycle — `sessions/lifecycle.py`,
`ARCHITECTURE.md#session-lifecycle`, `DATA.md#continuing-between-groups`,
`RECORDING.md#start-and-end`.

Drives `SessionLifecycle` through its interface over a real SQLite database,
with stand-ins for the runner, the recording and the utility baseline that
write to one ordered log, so the ordering rules are what the tests read.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ephymeris_sidecar.cohorts.db import Database
from ephymeris_sidecar.cohorts.repository import CohortRepository
from ephymeris_sidecar.intan.service import IntanNotReady
from ephymeris_sidecar.ports.manager import CarriedSketch, sketch_fingerprint
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
from tests.live_sidecar import LiveSidecar, Refused, create_cohort, hold_the_rig
from tests.scripted_board import until

TODAY = date.today().isoformat()


class FakeRunner:
    """The runner's lifecycle-facing surface, with no ports behind it."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.group_id = ""
        self.session_id = ""
        self.configs: dict[int, BoxConfig] = {}
        self.running: set[int] = set()
        #: Boxes whose port will not take `STOP` (left the session, write failed).
        self.stop_refused: set[int] = set()
        #: The keywords `end_all` was last called with.
        self.ended_with: dict[str, Any] = {}

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

    def stop_box(self, box: int) -> bool:
        self.log.append(f"stop {box}")
        return box in self.running and box not in self.stop_refused

    async def end_all(self, *_args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.log.append("end boxes")
        self.ended_with = kwargs
        self.running.clear()

    def clear(self) -> None:
        if self.running:
            raise RuntimeError("active runs")
        self.log.append("clear")
        self.group_id = ""
        self.session_id = ""
        self.configs = {}

    def snapshot(self) -> list[dict]:
        """The real runner's rows, from this fake's own mapping and runs."""
        return [
            {
                "box": box,
                "animalId": config.animal_id,
                "animalName": config.animal_name,
                "sketchName": config.sketch_name,
                "sketchPath": config.sketch_path,
                "running": box in self.running,
                "startedAt": "2026-07-22T10:00:00+00:00" if box in self.running else None,
                "ended": False,
            }
            for box, config in sorted(self.configs.items())
        ]


class FakeIntan:
    """`IntanService`'s lifecycle-facing surface, held to its contract below."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        #: The (session, group) the Record step set a recording up for.
        self.set_up_for: tuple[str, str] | None = None
        self.is_recording = False
        self.force_stop = asyncio.Event()
        self.gate: asyncio.Event | None = None

    def set_up(self, session_id: str, group_id: str) -> None:
        """What the Record step's `intan.configure` leaves behind."""
        self.set_up_for = (session_id, group_id)

    def refuse_unless_ready(self, session_id: str, group_id: str) -> None:
        if self.set_up_for != (session_id, group_id):
            raise IntanNotReady("Finish the Recording step first.")

    def run_open_for(self, session_id: str) -> bool:
        return self.is_recording and self.set_up_for is not None and self.set_up_for[0] == session_id

    def may_still_record_for(self, session_id: str) -> bool:
        return self.run_open_for(session_id)

    async def start_recording(self) -> None:
        self.log.append("rhx start")
        if self.gate is not None:
            await self.gate.wait()
        self.is_recording = True

    async def stop_recording(self) -> dict[str, Any] | None:
        if not self.is_recording:
            self.release()
            return None
        self.log.append("rhx stop")
        self.is_recording = False
        self.set_up_for = None
        return {"file": "run1.rhd"}

    def release(self) -> None:
        self.log.append("rhx release")
        if not self.is_recording:
            self.set_up_for = None

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


class FakeFlashes:
    """The flash queue's lifecycle-facing surface. Its calls go to their own
    list, not the ordering log: when a queue is cancelled is not an ordering
    rule. `run` plays each queued job's run-time sketch lookup, the way the
    queue would when the job's turn comes."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.jobs: list = []

    def submit(self, jobs) -> None:  # noqa: ANN001
        for job in jobs:
            self.calls.append(f"flash {job.box}")
            self.jobs.append(job)

    def cancel(self, origins=("session", "debug"), boxes=None, *, clear: bool = False) -> None:  # noqa: ANN001
        self.calls.append(f"cancel {','.join(origins)}")
        self.jobs = [j for j in self.jobs if j.origin not in origins]

    def run(self) -> list[str | None]:
        return [job.prepare() for job in self.jobs]


class Rig:
    """One lifecycle and everything it was built from."""

    def __init__(self, db: Database, root: Path, *, intan: Any = False, ports=None) -> None:  # noqa: ANN001
        """`ports` puts the real `SessionRunner` on those ports in place of
        `FakeRunner` (`tests/scripted_board.py`). `intan` is True for
        `FakeIntan`, or the recording service itself."""
        self.log: list[str] = []
        self.events: list[dict] = []
        self.root = root
        self.sessions = SessionRepository(db)
        self.cohorts = CohortRepository(db)
        if ports is None:
            self.runner = FakeRunner(self.log)
        else:
            from ephymeris_sidecar.sessions.runner import SessionRunner

            async def runner_broadcast(message: dict) -> None:
                self.events.append(message)

            self.runner = SessionRunner(
                loop=asyncio.get_running_loop(), ports=ports, broadcast=runner_broadcast,
                on_animal_ended=lambda run, reason: self.lifecycle.animal_ended(run, reason),
            )
        self.intan = FakeIntan(self.log) if intan is True else (intan or None)
        self.utility = FakeUtility(self.log)
        self.flashes = FakeFlashes()
        #: What each box's board carries -- `PortManager.carried`'s record.
        self.carried: dict[int, CarriedSketch] = {}

        async def broadcast(message: dict) -> None:
            self.events.append(message)

        #: Whether `confirm` also does the Record step for a recording session.
        self.record_step = True
        self.lifecycle = SessionLifecycle(
            sessions=self.sessions,
            cohorts=self.cohorts,
            runner=self.runner,
            intan=self.intan,
            utility=self.utility,
            profiles=None,
            logbook=None,
            rig_reading=nullcontext,  # no rig definition write in these tests
            broadcast=broadcast,
            carried=self.carried.get,
            flashes=self.flashes,
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
        if self.intan is not None and session.recording is not None and self.record_step:
            self.intan.set_up(session.id, group_id)
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


@pytest.fixture
async def bench():  # noqa: ANN201
    """Boxes 1 and 2 on a real `PortManager`, boards plugged in."""
    from tests.scripted_board import Bench

    made = await Bench(asyncio.get_running_loop(), (1, 2)).plug_in()
    yield made
    made.shutdown()


@pytest.fixture
async def bench_rig(db: Database, tmp_path: Path, bench) -> Rig:  # noqa: ANN001
    """The lifecycle over the real runner over the real ports."""
    return Rig(db, tmp_path, ports=bench.ports)


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


# --- the session's flashes (ARCHITECTURE.md#flash-sequence) -------------------


async def test_flashing_queues_the_mapped_boxes_in_the_order_asked(rig) -> None:
    session = rig.session()
    await rig.confirm(session, flash=False)

    await rig.lifecycle.flash(session.id, [2, 1])

    assert rig.flashes.calls == ["cancel session", "flash 2", "flash 1"]
    assert [job.origin for job in rig.flashes.jobs] == ["session", "session"]
    assert rig.flashes.run() == [str(rig.sketch()), str(rig.sketch())]


async def test_a_queued_flash_takes_the_mapping_current_when_it_runs(rig) -> None:
    """The defect the sidecar queue exists for: a flash queued under one
    mapping must not land the old sketch after the mapping changed."""
    session = rig.session()
    await rig.confirm(session, flash=False)
    await rig.lifecycle.flash(session.id, [1])
    queued = rig.flashes.jobs[0]

    other = rig.sketch("other")
    entries = [
        MappingEntry(box=e.box, animal_id=e.animal_id, sketch_path=str(other), config={})
        for e in rig.mapping(session)
    ]
    await rig.lifecycle.confirm_mapping(session.id, "g-a", entries)

    # The new confirm dropped it; had it already been under way, it would read
    # the new mapping when its turn came.
    assert rig.flashes.jobs == []
    assert queued.prepare() == str(other)


async def test_a_box_the_mapping_no_longer_holds_is_skipped(rig) -> None:
    session = rig.session()
    await rig.confirm(session, flash=False)
    await rig.lifecycle.flash(session.id, [1])
    queued = rig.flashes.jobs[0]

    await rig.lifecycle.abandon(session.id)

    assert queued.prepare() is None


async def test_a_running_box_is_not_reflashed(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(1)

    with pytest.raises(SessionRefused, match="box 1 is running"):
        await rig.lifecycle.flash(session.id, [1])
    assert rig.lifecycle.mapped_sketch(1) is None


async def test_flashing_needs_the_session_that_holds_the_rig(rig) -> None:
    session = rig.session()
    with pytest.raises(SessionRefused, match="doesn't hold the rig"):
        await rig.lifecycle.flash(session.id, [1])

    await rig.confirm(session, flash=False)
    with pytest.raises(SessionRefused, match="box 3 isn't in the confirmed mapping"):
        await rig.lifecycle.flash(session.id, [1, 3])
    # Refused whole: nothing queued for box 1 either.
    assert rig.flashes.jobs == []


async def test_every_way_out_drops_what_is_still_queued(rig) -> None:
    session = rig.session()
    await rig.confirm(session, flash=False)
    await rig.lifecycle.flash(session.id, [1, 2])
    await rig.lifecycle.end(session.id)
    assert rig.flashes.jobs == []

    second = rig.session()
    await rig.run_group(second)
    await rig.lifecycle.end_group(second.id)
    assert rig.flashes.calls[-1] == "cancel session"


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
    rig.record_step = False
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


# --- a start that fails part-way, on the real runner and ports ------------------


async def test_a_box_start_the_port_refuses_records_nothing_and_ends(bench_rig, bench) -> None:  # noqa: ANN001
    """B1: box 1's port is in ERROR from an earlier start whose board never
    reported READY. Its board still carries the sketch, so Start reaches the
    port, and the port refuses. Nothing is recorded, and End still ends."""
    rig = bench_rig
    session = rig.session()
    await rig.confirm(session)
    bench.ports.handler(1).force_error("board never reported READY")

    with pytest.raises(BoxRefused):
        await rig.lifecycle.start_box(1)

    stored = rig.sessions.get_session(session.id)
    assert (stored.status, stored.group_runs) == ("configuring", [])
    assert rig.runner.running_boxes() == []
    assert not rig.lifecycle.writing

    ended = await rig.lifecycle.end(session.id)
    assert ended.status == "completed" and rig.lifecycle.held is None


async def test_switch_group_after_a_refused_box_start(bench_rig, bench) -> None:  # noqa: ANN001
    """B1, with another box already running: Switch Group ends that one and
    the group, and the rig is free for the next."""
    rig = bench_rig
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(2)
    await bench.run_handshake(2)
    bench.ports.handler(1).force_error("board never reported READY")
    with pytest.raises(BoxRefused):
        await rig.lifecycle.start_box(1)

    await rig.lifecycle.end_group(session.id)

    stored = rig.sessions.get_session(session.id)
    assert [r.ended_at is not None for r in stored.group_runs] == [True]
    assert [r.box_number for r in rig.sessions.runs_for(session.id)] == [2]
    assert rig.runner.configured_boxes() == [] and rig.runner.running_boxes() == []


async def test_start_all_failing_part_way_records_the_boxes_it_started(bench_rig, bench) -> None:  # noqa: ANN001
    """B2: box 1 starts, box 2 is refused. Box 1 is a run, so the group has
    run: the group run and `running` are recorded before the refusal is
    raised, End ends box 1, and Abandon is refused by name rather than
    failing inside the runner."""
    rig = bench_rig
    session = rig.session()
    await rig.confirm(session)
    bench.ports.handler(2).force_error("board never reported READY")

    with pytest.raises(BoxRefused) as refused:
        await rig.lifecycle.start_all(session.id)
    assert refused.value.box == 2

    stored = rig.sessions.get_session(session.id)
    assert stored.status == "running"
    assert [(r.group_id, r.ended_at) for r in stored.group_runs] == [("g-a", None)]
    assert rig.runner.running_boxes() == [1]
    assert rig.events[-1]["evt"] == "session.lifecycle"

    with pytest.raises(SessionRefused, match="only a configuring session"):
        await rig.lifecycle.abandon(session.id)

    await bench.run_handshake(1)
    ended = await rig.lifecycle.end(session.id)
    assert ended.status == "completed"
    assert [r.box_number for r in rig.sessions.runs_for(session.id)] == [1]
    assert rig.runner.running_boxes() == []


async def test_start_all_refused_at_its_first_box_can_be_abandoned(bench_rig, bench) -> None:  # noqa: ANN001
    """B2 at k = 1: nothing started, so nothing ran, and the configuring
    session can still be abandoned."""
    rig = bench_rig
    session = rig.session()
    await rig.confirm(session)
    bench.ports.handler(1).force_error("board never reported READY")

    with pytest.raises(BoxRefused):
        await rig.lifecycle.start_all(session.id)

    assert rig.sessions.get_session(session.id).group_runs == []
    abandoned = await rig.lifecycle.abandon(session.id)
    assert abandoned.status == "aborted" and rig.lifecycle.held is None


# --- RHX unreachable while a group records (RECORDING.md#when-rhx-goes-away) ---


@pytest.fixture
async def rhx():  # noqa: ANN201
    """`(fake RHX, the real recording service on it)`, polling every 50 ms."""
    from ephymeris_sidecar.intan.service import IntanService
    from tests.fake_rhx import FakeRhx
    from tests.test_intan_service import settings_for

    fake = await FakeRhx().start()

    async def nothing(_message: dict) -> None:
        return None

    service = IntanService(
        loop=asyncio.get_running_loop(), broadcast=nothing,
        settings=settings_for(fake, {1: 2, 2: 5}), rig_has_sync=lambda: True,
        pre_roll_s=0.0, post_roll_s=0.0, poll_s=0.05,
    )
    service.start()
    try:
        yield fake, service
    finally:
        await service.stop()
        await fake.stop()


def _two_box_recording(tmp_path: Path) -> dict:
    from tests.test_intan_service import config

    return config(
        tmp_path,
        boxes=[
            {"box": 1, "port": "A", "firstChannel": 0, "lastChannel": 15},
            {"box": 2, "port": "A", "firstChannel": 16, "lastChannel": 31},
        ],
    )


async def _recording_rig(db: Database, tmp_path: Path, rhx, ports=None):  # noqa: ANN001, ANN202
    """A recording session confirmed and its Record step done, on the real
    recording service."""
    fake, service = rhx
    rig = Rig(db, tmp_path, intan=service, ports=ports)
    rig.record_step = False
    session = rig.session(recording=True)
    await rig.confirm(session)
    await service.configure(session.id, "g-a", _two_box_recording(tmp_path), "x")
    return rig, session


async def _lose_rhx(rhx) -> None:  # noqa: ANN001
    fake, service = rhx
    await fake.stop_listening()
    await until(lambda: service.status_json()["state"] == "error")


async def test_an_end_with_rhx_unreachable_still_waits_stops_and_records_the_run(
    db, tmp_path, rhx  # noqa: ANN001
) -> None:
    """B20: the link drops mid-recording and the operator ends the session.
    The boxes still get the recording's grace period, the stop is still
    attempted (and said to have failed), and the run is still the session's."""
    from ephymeris_sidecar.sessions.lifecycle import RECORDING_GRACE_S

    _fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_all(session.id)
    await _lose_rhx(rhx)

    ended = await asyncio.wait_for(rig.lifecycle.end(session.id), 10.0)

    assert ended.status == "completed"
    assert rig.runner.ended_with.get("graceful_timeout_s") == RECORDING_GRACE_S
    runs = rig.sessions.get_session(session.id).recording["runs"]
    assert [(r["groupId"], bool(r["startedAt"]), bool(r["endedAt"])) for r in runs] == [
        ("g-a", True, True)
    ]
    assert "Stop it from RHX" in service.status_json()["message"]


async def test_a_reconnect_stops_the_recording_an_unreachable_end_left_running(
    db, tmp_path, rhx  # noqa: ANN001
) -> None:
    """B20: RHX went on recording after the End that could not reach it. Once
    it is reachable again the stop owed is sent, and the next group's
    Record step is not refused with "RHX is already recording"."""
    fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_all(session.id)
    await _lose_rhx(rhx)
    await rig.lifecycle.end_group(session.id)
    assert fake.params["runmode"] == "Record"

    await fake.listen_again()
    await until(lambda: fake.params["runmode"] == "Stop")
    await until(lambda: service.status_json()["state"] == "idle")

    await service.configure(session.id, "g-b", _two_box_recording(tmp_path), "y")
    assert service.status_json()["state"] == "configured"


async def test_an_end_after_rhx_was_stopped_from_rhx_still_records_the_run(
    db, tmp_path, rhx  # noqa: ANN001
) -> None:
    """B20's sibling: Stop pressed in RHX mid-recording. The run happened, and
    the session says so. RHX is known to be in Stop, so the grace period would
    keep nothing inside the recording: the boxes end as behavior-only ones do."""
    fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_all(session.id)
    fake.params["runmode"] = "Stop"
    await until(lambda: service.status_json()["state"] == "error")

    await rig.lifecycle.end(session.id)

    assert "graceful_timeout_s" not in rig.runner.ended_with
    runs = rig.sessions.get_session(session.id).recording["runs"]
    assert [r["groupId"] for r in runs] == ["g-a"]


async def test_a_box_start_after_rhx_drops_names_the_lost_link(db, tmp_path, rhx) -> None:  # noqa: ANN001
    """B16: one box of a recording group is running and RHX's link drops.
    Starting another box is refused, but for the reason it is: the link, not a
    Recording step the operator already finished."""
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_box(1)
    await _lose_rhx(rhx)

    with pytest.raises(Exception) as refused:
        await rig.lifecycle.start_box(2)

    mapped = _mapped(refused.value)
    assert mapped.code == "INTAN_UNAVAILABLE"
    assert "Lost contact with RHX" in str(mapped)
    assert "Recording step" not in str(mapped)
    assert rig.runner.running_boxes() == [1]


async def test_abandoning_after_start_all_refused_at_box_1_stops_the_recording(
    db, tmp_path, rhx, bench  # noqa: ANN001
) -> None:
    """P1's B2 at k = 1, on a recording session: RHX started recording before
    box 1 was refused. Nothing ran, so the session may be abandoned, and
    abandoning it stops the recording rather than leaving RHX in Record."""
    fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx, ports=bench.ports)
    bench.ports.handler(1).force_error("board never reported READY")
    with pytest.raises(BoxRefused):
        await rig.lifecycle.start_all(session.id)
    assert fake.params["runmode"] == "Record"

    abandoned = await rig.lifecycle.abandon(session.id)

    assert abandoned.status == "aborted"
    await until(lambda: fake.params["runmode"] == "Stop")
    assert service.recording is None
    runs = rig.sessions.get_session(session.id).recording["runs"]
    assert [r["groupId"] for r in runs] == ["g-a"]


# --- a per-box stop (port.stopSession) ---------------------------------------


async def test_a_stop_the_port_could_not_take_is_refused_by_box(rig) -> None:
    """The STOP did not go out (the port left the session, or the write
    failed): the operator is told, not answered as if the box were stopping."""
    session = rig.session()
    await rig.run_group(session)
    rig.runner.stop_refused.add(1)

    with pytest.raises(BoxRefused) as refused:
        rig.lifecycle.stop_box(1)

    mapped = _mapped(refused.value)
    assert (mapped.code, mapped.detail) == ("ILLEGAL_TRANSITION", {"box": 1})


async def test_stopping_a_box_that_is_not_running_is_a_no_op(rig) -> None:
    """A box that already ended -- the board's end strobe raced the click."""
    session = rig.session()
    await rig.confirm(session)
    rig.lifecycle.stop_box(1)


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


# --- refusals over the wire -----------------------------------------------------


async def test_starting_boxes_that_carry_no_sketch_is_refused_by_name(
    sidecar: LiveSidecar, tmp_path: Path
) -> None:
    """Through the real handler: a refusal the handler forgot to map would reach
    the operator as INTERNAL, with no box to go and flash."""
    session = await hold_the_rig(sidecar, await create_cohort(sidecar, tmp_path / "Batch A"))
    with pytest.raises(Refused) as refused:
        await sidecar.call("sessions.startAll", sessionId=session)
    assert refused.value.code == "SESSION_INVALID"
    assert refused.value.detail == {"boxes": [1]}


async def test_flashing_for_a_session_that_does_not_hold_the_rig_is_refused(
    sidecar: LiveSidecar, tmp_path: Path
) -> None:
    cohort = await create_cohort(sidecar, tmp_path / "Batch A")
    prefix = (await sidecar.call("prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
    session = (await sidecar.call(
        "sessions.create", cohortId=cohort["id"], prefixId=prefix, sessionNumber="1"
    ))["session"]["id"]
    with pytest.raises(Refused) as refused:
        await sidecar.call("sessions.flash", sessionId=session, boxes=[1])
    assert refused.value.code == "SESSION_INVALID"


# --- FakeRunner keeps the real runner's contract -------------------------------
#
# The lifecycle tests above run on FakeRunner, so they prove something about the
# lifecycle only while it answers as SessionRunner does. These rules are the
# members the lifecycle calls, run against both.


def _real_runner(ports):  # noqa: ANN001, ANN202
    from ephymeris_sidecar.sessions.runner import SessionRunner

    async def nothing(*_args) -> None:  # noqa: ANN002
        return None

    return SessionRunner(
        loop=asyncio.get_running_loop(), ports=ports, broadcast=nothing, on_animal_ended=nothing,
    )


def _box(box: int) -> BoxConfig:
    return BoxConfig(
        box=box, animal_id=f"a{box}", animal_name=f"remy{box}", sketch_path="/sk/GRGL",
        sketch_name="GRGL", start_command="START", config_metadata={}, profile=None,
    )


@pytest.fixture(params=["FakeRunner", "SessionRunner"])
async def runner(request: pytest.FixtureRequest, tmp_path: Path, bench):  # noqa: ANN001, ANN201
    # Built inside the test's loop: the real runner binds to it, on real ports.
    made = FakeRunner([]) if request.param == "FakeRunner" else _real_runner(bench.ports)
    made.configure(tmp_path, "2O-Bdisc_12", "g-a", [_box(2), _box(1)], session_id="s1")
    return made


async def test_a_runner_holds_the_mapping_it_was_given(runner) -> None:  # noqa: ANN001
    assert runner.group_id == "g-a"
    assert runner.configured_boxes() == [1, 2]
    assert [c.box for c in runner.box_configs()] == [1, 2]
    assert runner.running_boxes() == []


async def test_a_runner_refuses_a_box_it_has_no_mapping_for(runner) -> None:  # noqa: ANN001
    with pytest.raises(KeyError):
        runner.start_box(5)
    assert runner.running_boxes() == []


async def test_a_runner_starts_a_box_once(runner) -> None:  # noqa: ANN001
    runner.start_box(1)
    runner.start_box(1)
    assert runner.running_boxes() == [1]


async def test_a_runner_will_not_forget_a_mapping_while_a_box_runs(runner) -> None:  # noqa: ANN001
    runner.start_box(1)
    with pytest.raises(RuntimeError):
        runner.clear()
    assert runner.configured_boxes() == [1, 2]


async def test_a_runner_ends_every_box_then_forgets_on_clear(runner) -> None:  # noqa: ANN001
    runner.start_box(1)
    runner.start_box(2)
    await runner.end_all("operator stop")
    assert runner.running_boxes() == []

    runner.clear()
    assert (runner.group_id, runner.configured_boxes()) == ("", [])


async def test_a_runner_says_whether_a_stop_went_out(runner, bench) -> None:  # noqa: ANN001
    assert runner.stop_box(1) is False  # not running
    runner.start_box(1)
    if not isinstance(runner, FakeRunner):
        await bench.run_handshake(1)
    assert runner.stop_box(1) is True


async def test_a_runner_reports_a_row_per_mapped_box(runner) -> None:  # noqa: ANN001
    """What the lifecycle broadcasts as the running session's boxes."""
    runner.start_box(2)
    rows = runner.snapshot()
    assert [(r["box"], r["animalId"], r["running"]) for r in rows] == [
        (1, "a1", False), (2, "a2", True),
    ]


# --- FakeIntan keeps the real service's contract -------------------------------


@pytest.fixture(params=["FakeIntan", "IntanService"])
async def intan(request: pytest.FixtureRequest, tmp_path: Path):  # noqa: ANN201
    """`(service, set_up)`: `set_up(session, group)` does what the Record step's
    `intan.configure` does, for the fake or against a fake RHX."""
    if request.param == "FakeIntan":
        fake = FakeIntan([])

        async def set_up(session_id: str, group_id: str) -> None:
            fake.set_up(session_id, group_id)

        yield fake, set_up
        return

    from ephymeris_sidecar.intan.service import IntanService
    from tests.fake_rhx import FakeRhx
    from tests.test_intan_service import config, settings_for

    rhx = await FakeRhx().start()

    async def nothing(_message: dict) -> None:
        return None

    service = IntanService(
        loop=asyncio.get_running_loop(), broadcast=nothing,
        settings=settings_for(rhx, {1: 2, 3: 5}), rig_has_sync=lambda: True,
        pre_roll_s=0.0, post_roll_s=0.0, poll_s=0.05,
    )
    service.start()

    async def set_up(session_id: str, group_id: str) -> None:
        await service.configure(session_id, group_id, config(tmp_path), "x")

    try:
        yield service, set_up
    finally:
        await service.stop()
        await rhx.stop()


def _ready(service, session_id: str, group_id: str) -> bool:  # noqa: ANN001
    from ephymeris_sidecar.intan.client import RhxUnavailable

    try:
        service.refuse_unless_ready(session_id, group_id)
    except (IntanNotReady, RhxUnavailable):
        return False
    return True


async def test_a_recording_is_set_up_for_one_session_and_group(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    assert not _ready(service, "s1", "g1")
    await set_up("s1", "g1")
    assert _ready(service, "s1", "g1")
    assert not _ready(service, "s1", "g2")
    assert not _ready(service, "s2", "g1")


async def test_a_recording_runs_from_start_to_stop(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1", "g1")
    assert not service.is_recording and not service.run_open_for("s1")
    await service.start_recording()
    assert service.is_recording
    assert service.run_open_for("s1") and not service.run_open_for("s2")
    assert service.may_still_record_for("s1") and not service.may_still_record_for("s2")
    assert await service.stop_recording() is not None
    assert not service.is_recording and not service.run_open_for("s1")
    assert not service.may_still_record_for("s1")


async def test_stopping_a_recording_that_never_started_lets_go(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1", "g1")
    assert await service.stop_recording() is None
    assert not _ready(service, "s1", "g1")


async def test_letting_go_forgets_a_set_up_that_never_recorded(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1", "g1")
    service.release()
    assert not _ready(service, "s1", "g1")


async def test_letting_go_leaves_a_running_recording_alone(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1", "g1")
    await service.start_recording()
    service.release()
    assert service.is_recording and service.run_open_for("s1")
    await service.stop_recording()
