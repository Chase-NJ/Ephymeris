"""The held session and its lifecycle — `sessions/lifecycle.py`,
`ARCHITECTURE.md#session-lifecycle`, `DATA.md#continuing-between-rounds`,
`RECORDING.md#start-and-end`.

Drives `SessionLifecycle` through its interface over a real SQLite database,
with stand-ins for the runner, the recording and the utility baseline that
write to one ordered log, so the ordering rules are what the tests read.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ephymeris_sidecar.tasks.start_command import build_start_command
from ephymeris_sidecar.analytics.repository import AnalyticsRepository
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
    StopRefused,
    WiringNotLoaded,
)
from ephymeris_sidecar.sessions.models import Round, PrefixNameTaken, SessionAnimalRun
from ephymeris_sidecar.sessions.repository import SessionRepository
from ephymeris_sidecar.sessions.runner import ActiveRun, BoxConfig
from ephymeris_sidecar.tasks.profile import parse_profile, profile_hash
from tests.live_sidecar import LiveSidecar, Refused, create_cohort, hold_the_rig
from tests.scripted_board import until

TODAY = date.today().isoformat()


class FakeRunner:
    """The runner's lifecycle-facing surface, with no ports behind it."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.session_id = ""
        self.configs: dict[int, BoxConfig] = {}
        self.running: set[int] = set()
        #: Boxes whose port will not take `STOP` (left the session, write failed).
        self.stop_refused: set[int] = set()
        #: The keywords `end_all` was last called with.
        self.ended_with: dict[str, Any] = {}

    def configure(self, _folder, _label, box_configs, duration_s=None, *, session_id, **facts):  # noqa: ANN001, ANN003
        #: What the lifecycle said of the run's cohort, date and earlier runs.
        self.facts = facts
        self.session_id = session_id
        self.configs = {c.box: c for c in box_configs}

    def configured_boxes(self) -> list[int]:
        return sorted(self.configs)

    def box_configs(self) -> list[BoxConfig]:
        return [self.configs[box] for box in sorted(self.configs)]

    def running_boxes(self) -> list[int]:
        return sorted(self.running)

    def writing_boxes(self) -> list[int]:
        """The fake's runs finish the moment they end, so writing is running."""
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
        #: The (session, mapping confirmation) the Record step set a
        #: recording up for.
        self.set_up_for: tuple[str, int] | None = None
        self.is_recording = False
        self.force_stop = asyncio.Event()
        self.gate: asyncio.Event | None = None
        #: RHX has not confirmed the last stop (`IntanService.stop_owed`).
        self.stop_owed = False
        #: What `stop_recording` hands back as the run's record.
        self.run_record: dict[str, Any] = {"file": "run1.rhd"}

    def set_up(self, session_id: str, confirmation: int) -> None:
        """What the Record step's `intan.configure` leaves behind."""
        self.set_up_for = (session_id, confirmation)

    def refuse_unless_ready(self, session_id: str, confirmation: int) -> None:
        ours = self.set_up_for is not None and self.set_up_for[0] == session_id
        if ours and self.is_recording:
            return
        if self.set_up_for != (session_id, confirmation):
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
        return dict(self.run_record)

    def release(self) -> None:
        self.log.append("rhx release")
        if not self.is_recording:
            self.set_up_for = None

    def note_waiting(self, _boxes: list[int]) -> None:
        pass

    #: What `box_ended` hands back: a recorded box's spike counts, or None.
    spikes: Any = None

    def box_ended(self, *_args) -> Any:  # noqa: ANN002
        return self.spikes


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

    def __init__(
        self, db: Database, root: Path, *, intan: Any = False, ports=None, profiles=None  # noqa: ANN001
    ) -> None:
        """`ports` puts the real `SessionRunner` on those ports in place of
        `FakeRunner` (`tests/scripted_board.py`). `intan` is True for
        `FakeIntan`, or the recording service itself. `profiles` is where a
        finishing run's task profile is snapshotted."""
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

        #: What `RigDefinition.wiring_problem` answers: None while the stored
        #: wiring is in force.
        self.wiring_problem: str | None = None
        #: Whether `confirm` also does the Record step for a recording session.
        self.record_step = True
        self.lifecycle = SessionLifecycle(
            db=db,
            sessions=self.sessions,
            cohorts=self.cohorts,
            runner=self.runner,
            intan=self.intan,
            utility=self.utility,
            profiles=profiles,
            logbook=None,
            rig_reading=nullcontext,  # no rig definition write in these tests
            broadcast=broadcast,
            carried=self.carried.get,
            flashes=self.flashes,
            wiring_problem=lambda: self.wiring_problem,
        )
        self._cohorts = 0

    def session(self, day: str = TODAY, *, recording: bool = False):  # noqa: ANN201
        self._cohorts += 1
        name = f"C{self._cohorts}"
        cohort = self.cohorts.create(
            name,
            str(self.root / name),
            animals=[
                {"id": f"{name}-1", "name": "remy1", "boxNumber": 1},
                {"id": f"{name}-2", "name": "remy2", "boxNumber": 2},
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

    async def confirm(self, session, *, flash: bool = True) -> None:  # noqa: ANN001
        """Confirm, then flash every mapped box as the placement walk does."""
        entries = self.mapping(session)
        await self.lifecycle.confirm_mapping(session.id, entries)
        if self.intan is not None and session.recording is not None and self.record_step:
            self.intan.set_up(session.id, self.lifecycle.confirmations)
        if flash:
            for entry in entries:
                self.flash(entry.box, Path(entry.sketch_path))

    async def run_round(self, session) -> None:  # noqa: ANN001
        await self.confirm(session)
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


async def test_the_runner_is_told_the_cohort_the_date_and_how_to_count_earlier_runs(rig) -> None:
    """What a run's document says of itself beyond its box (`DATA.md#the-json-document`)."""
    session = rig.session()
    await rig.confirm(session)

    facts = rig.runner.facts
    assert (facts["cohort_name"], facts["session_date"]) == ("C1", session.date)
    assert facts["earlier_runs"]("C1-1") == 0, "no run yet today: the next is run 1"
    rig.sessions.record_animal_run(SessionAnimalRun(
        id="r1", session_id=session.id, animal_id="C1-1", box_number=1, sketch_path="/sk",
        started_at=f"{session.date}T10:00:00+00:00"))
    assert facts["earlier_runs"]("C1-1") == 1 and facts["earlier_runs"]("C1-2") == 0


async def test_each_box_records_the_channel_set_its_sketch_was_generated_against(
    rig, monkeypatch
) -> None:
    """Read inside the hold on the rig definition: no write lands between it
    and the end of the session, so it is the channel set the folders were
    generated from (`DATA.md#the-tsv-log`)."""
    from ephymeris_sidecar.rig import registry

    monkeypatch.setattr(
        registry.ChannelSet, "content_hash", lambda self, version=2: "c0ffee0123456789"
    )
    await rig.confirm(rig.session())
    assert {c.channel_set_hash for c in rig.runner.box_configs()} == {"c0ffee0123456789"}
    assert {c.channel_set_hash_version for c in rig.runner.box_configs()} == {2}


async def test_confirming_the_same_mapping_again_is_a_new_confirmation_on_the_wire(rig) -> None:
    """Two identical re-confirms are told apart by the payload itself.

    Everything else in it can repeat byte for byte: the runner's snapshot of
    a just-confirmed mapping is the same each time, and a per-box start of a
    later round announces nothing. A client clears its live run on a
    confirmation it has not seen, so the payload must say there was one.
    """
    session = rig.session()
    await rig.confirm(session)
    first = rig.events[-1]["data"]
    await rig.confirm(session)
    second = rig.events[-1]["data"]

    assert first != second
    assert second["confirmations"] == first["confirmations"] + 1
    # The answer a reconnecting or reloaded client asks for carries it too.
    assert (await rig.lifecycle.active())["confirmations"] == second["confirmations"]


async def test_a_refused_mapping_is_not_a_confirmation(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    before = (await rig.lifecycle.active())["confirmations"]
    entry = MappingEntry(box=1, animal_id="nobody", sketch_path="/sk", config={})
    with pytest.raises(SessionRefused):
        await rig.lifecycle.confirm_mapping(session.id, [entry])
    assert (await rig.lifecycle.active())["confirmations"] == before


async def test_status_reports_the_rig_only_for_the_session_holding_it(rig) -> None:
    held = rig.session()
    other = rig.session()
    await rig.confirm(held)
    rig.runner.snapshot = lambda: [{"box": 1}]

    assert (await rig.lifecycle.status(held.id))["boxes"] == [{"box": 1}]
    # Another session's status must not carry the held one's animals and boxes.
    reply = await rig.lifecycle.status(other.id)
    assert reply["session"]["id"] == other.id
    assert reply["boxes"] == []


async def test_status_between_rounds_reports_no_boxes(rig) -> None:
    session = rig.session()
    await rig.run_round(session)
    await rig.lifecycle.end_round(session.id)

    assert (await rig.lifecycle.status(session.id))["boxes"] == []


async def test_a_mapping_missing_its_animal_is_refused_and_holds_nothing(rig) -> None:
    session = rig.session()
    entry = MappingEntry(box=1, animal_id="nobody", sketch_path="/sk", config={})
    with pytest.raises(SessionRefused, match="missing"):
        await rig.lifecycle.confirm_mapping(session.id, [entry])
    assert rig.lifecycle.held is None
    assert rig.log == []


async def test_the_questions_across_a_whole_session(rig) -> None:
    session = rig.session()
    await rig.run_round(session)
    assert (rig.lifecycle.held, rig.lifecycle.in_use, rig.lifecycle.writing) == (
        session.id, True, True,
    )
    await rig.lifecycle.end_round(session.id)
    # Between rounds: still held, nothing writing.
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
    # Box 1 was fine, and still did not start: a half-started round is worse.
    assert rig.log == ["hold"]
    stored = rig.sessions.get_session(session.id)
    assert (stored.status, stored.rounds) == ("configuring", [])


async def test_no_box_starts_or_flashes_while_the_stored_wiring_did_not_load(rig) -> None:
    """The registry runs the shipped pins meanwhile, so a box started now would
    drive and record against wiring the operator never declared
    (`TASKS.md#the-channel-set-and-the-pin-map`)."""
    session = rig.session()
    await rig.confirm(session)
    rig.wiring_problem = "wiring.json did not load: it will not parse."

    for start in (lambda: rig.lifecycle.start_all(session.id), lambda: rig.lifecycle.start_box(1)):
        with pytest.raises(WiringNotLoaded, match="did not load"):
            await start()
    with pytest.raises(WiringNotLoaded):
        await rig.lifecycle.flash(session.id, [1])
    assert rig.log == ["hold"]

    rig.wiring_problem = None
    await rig.lifecycle.start_box(1)
    assert "start 1" in rig.log


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
    await rig.lifecycle.confirm_mapping(session.id, entries)

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
    await rig.run_round(second)
    await rig.lifecycle.end_round(second.id)
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
    await rig.run_round(session)
    with pytest.raises(SessionRefused, match="only a configuring session"):
        await rig.lifecycle.abandon(session.id)


# --- recording order (RECORDING.md#start-and-end) -----------------------------


async def test_the_recording_starts_before_any_box(recording_rig) -> None:
    rig = recording_rig
    session = rig.session(recording=True)
    await rig.run_round(session)
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
    assert rig.sessions.get_session(session.id).rounds == []


async def test_ending_stops_the_boxes_then_rhx_then_lets_go(recording_rig) -> None:
    rig = recording_rig
    session = rig.session(recording=True)
    await rig.run_round(session)
    rig.log.clear()

    ended = await rig.lifecycle.end(session.id)

    assert rig.log == ["end boxes", "rhx stop", "clear", "release", "ensure"]
    assert ended.status == "completed"
    assert ended.rounds[0].ended_at is not None
    assert rig.sessions.get_session(session.id).recording["runs"] == [{"file": "run1.rhd"}]


async def test_a_stopped_recording_starts_its_spike_export_off_the_sessions_path(recording_rig) -> None:
    """`RECORDING.md#the-sort-export`: the recording's runs, by its folder's
    name, once RHX has stopped; the end does not wait for it."""
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    asked: list[tuple[list[str], str]] = []
    gate = threading.Event()

    def slow_export(files: list[str], recording: str) -> None:
        gate.wait(5)
        asked.append((files, recording))

    rig.lifecycle.export_spikes = slow_export
    session = rig.session(recording=True)
    await rig.run_round(session)

    ended = await rig.lifecycle.end(session.id)
    assert ended.status == "completed" and asked == [], "the session ended while the export still ran"
    gate.set()
    await rig.lifecycle.exports_settled()
    [(files, recording)] = asked
    assert recording == "rec_260417_095743"
    assert files == [r.file_path for r in rig.sessions.runs_for(session.id) if r.file_path]


async def test_an_export_that_fails_costs_the_session_nothing(recording_rig) -> None:
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}

    def broken(_files: list[str], _recording: str) -> None:
        raise RuntimeError("disk on fire")

    rig.lifecycle.export_spikes = broken
    session = rig.session(recording=True)
    await rig.run_round(session)
    ended = await rig.lifecycle.end(session.id)
    await rig.lifecycle.exports_settled()
    assert ended.status == "completed"
    assert rig.sessions.get_session(session.id).recording["runs"] == [rig.intan.run_record]


async def test_a_stopped_recording_is_aligned_then_exported_in_that_order(recording_rig) -> None:
    """`RECORDING.md#alignment-at-session-end`: one pass, two steps, never at
    once: alignment rewrites each run's files, then the export reads them."""
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    steps: list[tuple[str, str]] = []

    looked = asyncio.Event()

    async def align(files: list[str], recording: str) -> None:
        await looked.wait()   # held open, so the export must still wait for it
        steps.append(("align", recording))

    rig.lifecycle.align_runs = align
    rig.lifecycle.export_spikes = lambda _files, recording: steps.append(("export", recording))
    session = rig.session(recording=True)
    await rig.run_round(session)
    # An end that waited for the alignment would never return: it is held open.
    ended = await asyncio.wait_for(rig.lifecycle.end(session.id), timeout=30)
    assert ended.status == "completed" and steps == [], "the end waited for neither"
    looked.set()
    await rig.lifecycle.exports_settled()
    assert steps == [("align", "rec_260417_095743"), ("export", "rec_260417_095743")]


async def test_an_alignment_that_cannot_run_costs_the_session_and_the_export_nothing(recording_rig) -> None:
    """A busy archive, a box already running again, RHX's files unreadable:
    the run's files stay as finalization wrote them and the export still runs."""
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    exported: list[str] = []

    async def refused(_files: list[str], _recording: str) -> None:
        raise RuntimeError("a box is running")

    rig.lifecycle.align_runs = refused
    rig.lifecycle.export_spikes = lambda _files, recording: exported.append(recording)
    session = rig.session(recording=True)
    await rig.run_round(session)
    ended = await rig.lifecycle.end(session.id)
    await rig.lifecycle.exports_settled()
    assert ended.status == "completed" and exported == ["rec_260417_095743"]


async def test_no_export_starts_while_rhx_has_not_confirmed_its_stop(recording_rig) -> None:
    """Its files may still be growing: an export now could be cut short and look whole."""
    rig = recording_rig
    rig.intan.run_record = {"baseFilename": "rec", "fileTimestamp": "260417_095743"}
    rig.intan.stop_owed = True
    asked: list[str] = []
    rig.lifecycle.export_spikes = lambda _files, recording: asked.append(recording)

    async def align(_files: list[str], recording: str) -> None:
        asked.append(recording)

    rig.lifecycle.align_runs = align
    session = rig.session(recording=True)
    await rig.run_round(session)
    await rig.lifecycle.end(session.id)
    await rig.lifecycle.exports_settled()
    assert asked == []


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
    await rig.run_round(session)
    await rig.lifecycle.end(session.id)
    assert rig.lifecycle.held is None

    config = BoxConfig(
        box=1,
        animal_id="C1-1",
        animal_name="remy1",
        sketch_path="/sk",
        sketch_name="sk",
        start_command=build_start_command(None, {}),
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


async def test_a_run_record_keeps_the_interpreter_and_channel_set_it_ran_on(rig) -> None:
    """`DATA.md#run-records`: what the board announced (`INTERP=<n>`) and the
    channel set its sketch was generated against go on the record at
    finalization."""
    session = rig.session()
    config = BoxConfig(
        box=1, animal_id="C1-1", animal_name="remy1", sketch_path="/sk", sketch_name="sk",
        start_command=build_start_command(None, {}), config_metadata={}, profile=None,
        channel_set_hash="3f0c9a17b2d4e588", channel_set_hash_version=2,
    )
    run = ActiveRun(box=1, config=config, run_id="r-1", started_at="2026-10-10T10:00:00+00:00",
                    address="/dev/fake1", session_id_label="P1_12", session_id=session.id, interp=2)
    await rig.lifecycle.animal_ended(run, "end")

    [recorded] = rig.sessions.runs_for(session.id)
    assert (recorded.interp, recorded.channel_set_hash) == (2, "3f0c9a17b2d4e588")


async def test_a_run_never_names_a_profile_another_writers_rollback_threw_away(
    db: Database, tmp_path: Path
) -> None:
    """B14: a finishing run's profile snapshot and its run record land
    together, whatever another writer does meanwhile
    (`ANALYTICS.md#which-profile-decodes-a-run`).

    The other writer here is the operator adding a prefix whose name is
    taken, which rolls back. It runs at the moment the profile is being
    snapshotted: the sqlite trace hook sees the `task_profiles` insert and
    queues the rival on the loop, ahead of the finalization's next step. On
    one shared connection, a rollback that lands between the snapshot and the
    run record throws the snapshot away, and the run is recorded naming a
    profile hash with no row -- decoded years later by whatever `task.json`
    is current, which is what the snapshot exists to prevent.
    """
    profiles = AnalyticsRepository(db)
    rig = Rig(db, tmp_path, profiles=profiles)
    session = rig.session()
    rig.sessions.create_prefix("Taken")
    profile = parse_profile({"taskName": "Snapshot me"})
    loop = asyncio.get_running_loop()
    refused: list[str] = []

    def rival() -> None:
        try:
            rig.sessions.create_prefix("Taken")
        except PrefixNameTaken:
            refused.append("Taken")

    fired = False

    def on_statement(sql: str) -> None:
        nonlocal fired
        if not fired and "INSERT" in sql.upper() and "task_profiles" in sql:
            fired = True
            loop.call_soon_threadsafe(rival)

    config = BoxConfig(
        box=1,
        animal_id="C1-1",
        animal_name="remy1",
        sketch_path="/sk",
        sketch_name="sk",
        start_command=build_start_command(None, {}),
        config_metadata={},
        profile=profile,
    )
    run = ActiveRun(
        box=1,
        config=config,
        run_id="r-1",
        started_at="2026-10-10T10:00:00+00:00",
        address="/dev/fake1",
        session_id_label="P1_12",
        session_id=session.id,
    )
    db._conn.set_trace_callback(on_statement)
    try:
        await rig.lifecycle.animal_ended(run, "end")
    finally:
        db._conn.set_trace_callback(None)

    assert refused == ["Taken"], "the rival write ran, and was refused"
    [recorded] = rig.sessions.runs_for(session.id)
    assert recorded.profile_hash == profile_hash(profile)
    assert profiles.load_profile(recorded.profile_hash) is not None, (
        "the run names a profile snapshot that another writer's rollback discarded"
    )


async def test_a_run_whose_profile_snapshot_aborts_the_unit_is_still_recorded_and_announced(
    db: Database, tmp_path: Path
) -> None:
    """A profile snapshot SQLite answers by rolling the whole unit back (a
    full disk, an I/O error) must not cost the run: it is recorded without a
    snapshot, as any snapshot failure is, and the finalization goes on to
    announce it (`DATA.md#transactions`). A TEMP trigger stands in for the
    full disk."""
    rig = Rig(db, tmp_path, profiles=AnalyticsRepository(db))
    session = rig.session()
    with db.write() as tx:
        tx.execute(
            "CREATE TEMP TRIGGER disk_full BEFORE INSERT ON task_profiles"
            " BEGIN SELECT RAISE(ROLLBACK, 'disk full'); END"
        )
    commits: list[int] = []
    db.on_commit(lambda: commits.append(1))
    config = BoxConfig(
        box=1, animal_id="C1-1", animal_name="remy1", sketch_path="/sk", sketch_name="sk",
        start_command=build_start_command(None, {}), config_metadata={},
        profile=parse_profile({"taskName": "Snapshot me"}),
    )
    run = ActiveRun(
        box=1, config=config, run_id="r-1", started_at="2026-10-10T10:00:00+00:00",
        address="/dev/fake1", session_id_label="P1_12", session_id=session.id,
    )

    await rig.lifecycle.animal_ended(run, "end")

    [recorded] = rig.sessions.runs_for(session.id)
    assert recorded.profile_hash is None
    assert rig.events[-1]["evt"] == "session.animalEnded"
    assert commits == [1], "the record was announced to the backup"


# --- rounds (ARCHITECTURE.md#between-rounds) ------------------------------------


async def test_end_round_leaves_the_session_running_between_rounds(rig) -> None:
    session = rig.session()
    await rig.run_round(session)
    rig.log.clear()

    ended = await rig.lifecycle.end_round(session.id)

    assert ended.status == "running"
    assert ended.rounds[0].ended_at is not None
    # Held, but the finished round's mapping is gone: a reload must not offer
    # Start All on animals already carried home.
    assert rig.lifecycle.held == session.id
    assert rig.runner.configured_boxes() == []
    # The operator walks the rig for the next round, which wants the lights.
    assert rig.log == ["end boxes", "clear", "release", "ensure"]


async def test_each_round_is_recorded_in_the_order_it_ran(rig) -> None:
    session = rig.session()
    for _ in range(3):
        await rig.run_round(session)
        await rig.lifecycle.end_round(session.id)

    rounds = rig.sessions.get_session(session.id).rounds
    assert [r.order for r in rounds] == [0, 1, 2]
    assert all(r.ended_at is not None and r.label is None for r in rounds)


async def test_any_animal_may_take_any_box(rig) -> None:
    """Free assignment: the usual box is where set-up starts, not a rule."""
    session = rig.session()
    first, second = rig.mapping(session)
    swapped = [replace(first, box=5), replace(second, box=1)]

    await rig.lifecycle.confirm_mapping(session.id, swapped)

    assert sorted(rig.runner.configs) == [1, 5]
    assert rig.runner.configs[1].animal_id == second.animal_id


@pytest.mark.parametrize("clash", ["box", "animal"])
async def test_a_mapping_naming_a_box_or_an_animal_twice_is_refused(rig, clash: str) -> None:
    session = rig.session()
    first, second = rig.mapping(session)
    doubled = replace(second, box=first.box) if clash == "box" else replace(second, animal_id=first.animal_id)

    with pytest.raises(SessionRefused, match="twice"):
        await rig.lifecycle.confirm_mapping(session.id, [first, doubled])
    assert rig.lifecycle.held is None


async def test_start_all_after_a_per_box_start_is_one_round(rig) -> None:
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(1)
    await rig.lifecycle.start_all(session.id)
    assert len(rig.sessions.get_session(session.id).rounds) == 1


async def test_a_per_box_start_records_the_round(rig) -> None:
    """Boxes started one at a time used to leave no round and the status at
    `configuring` — so the session could not be continued, and Back on the
    next mapping discarded a session with real data in it."""
    session = rig.session()
    await rig.confirm(session)

    await rig.lifecycle.start_box(1)

    stored = rig.sessions.get_session(session.id)
    assert stored.status == "running"
    assert [r.order for r in stored.rounds] == [0]


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
    assert (stored.status, stored.rounds) == ("configuring", [])
    assert rig.runner.running_boxes() == []
    assert not rig.lifecycle.writing

    ended = await rig.lifecycle.end(session.id)
    assert ended.status == "completed" and rig.lifecycle.held is None


async def test_ending_the_round_after_a_refused_box_start(bench_rig, bench) -> None:  # noqa: ANN001
    """B1, with another box already running: ending the round ends that one, and the rig is free for the next."""
    rig = bench_rig
    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(2)
    await bench.run_handshake(2)
    bench.ports.handler(1).force_error("board never reported READY")
    with pytest.raises(BoxRefused):
        await rig.lifecycle.start_box(1)

    await rig.lifecycle.end_round(session.id)

    stored = rig.sessions.get_session(session.id)
    assert [r.ended_at is not None for r in stored.rounds] == [True]
    assert [r.box_number for r in rig.sessions.runs_for(session.id)] == [2]
    assert rig.runner.configured_boxes() == [] and rig.runner.running_boxes() == []


async def test_start_all_failing_part_way_records_the_boxes_it_started(bench_rig, bench) -> None:  # noqa: ANN001
    """B2: box 1 starts, box 2 is refused. Box 1 is a run, so the round has
    run: the round and `running` are recorded before the refusal is
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
    assert [(r.order, r.ended_at) for r in stored.rounds] == [(0, None)]
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

    assert rig.sessions.get_session(session.id).rounds == []
    abandoned = await rig.lifecycle.abandon(session.id)
    assert abandoned.status == "aborted" and rig.lifecycle.held is None


async def test_a_box_writes_until_its_run_is_recorded(  # noqa: ANN001
    bench_rig, bench, db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A box ending has left the running boxes while its `.json` lands and
    its record commits. A rescan then would adopt the file its record is
    about to claim, and a recover would write that same `.json` beside the
    finalization: both are refused until the run is recorded."""
    import threading

    from ephymeris_sidecar.analytics import CohortArchive
    from ephymeris_sidecar.analytics.archive import RigInUse
    from ephymeris_sidecar.sessions import writer as writer_module
    from ephymeris_sidecar.analytics.tests.test_analytics_service import Changes

    rig = bench_rig
    finalizing, may_finalize = threading.Event(), threading.Event()
    recording, may_record = threading.Event(), threading.Event()
    real_finalize = writer_module.AnimalWriter.finalize
    real_record = rig.sessions.record_animal_run

    def slow_finalize(self, reason):  # noqa: ANN001, ANN202
        finalizing.set()
        may_finalize.wait(timeout=5)
        return real_finalize(self, reason)

    def slow_record(run, **unit):  # noqa: ANN001, ANN003, ANN202
        recording.set()
        may_record.wait(timeout=5)
        return real_record(run, **unit)

    monkeypatch.setattr(writer_module.AnimalWriter, "finalize", slow_finalize)
    monkeypatch.setattr(rig.sessions, "record_animal_run", slow_record)

    archive = CohortArchive(
        db=db, cohorts=rig.cohorts, sessions=rig.sessions, rig=rig.lifecycle, on_changed=Changes()
    )

    async def both_refused(cohort_id: str) -> None:
        with pytest.raises(RigInUse):
            await archive.rescan(cohort_id)
        with pytest.raises(RigInUse):
            await archive.recover(cohort_id)

    session = rig.session()
    await rig.confirm(session)
    await rig.lifecycle.start_box(1)
    await bench.run_handshake(1, seed=7)
    ending = asyncio.create_task(rig.lifecycle.end(session.id))

    await until(finalizing.is_set)
    assert rig.runner.running_boxes() == []
    await both_refused(session.cohort_id)

    may_finalize.set()
    await until(recording.is_set)
    await both_refused(session.cohort_id)

    may_record.set()
    await ending
    await until(lambda: not rig.lifecycle.writing)
    assert [r.box_number for r in rig.sessions.runs_for(session.id)] == [1]
    assert (await archive.recover(session.cohort_id))["scanned"] == 0


# --- RHX unreachable while a round records (RECORDING.md#when-rhx-goes-away) ---


@pytest.fixture
async def rhx():  # noqa: ANN201
    """`(fake RHX, the real recording service on it)`, polling every 50 ms."""
    from ephymeris_sidecar.intan.service import IntanService
    from tests.fake_rhx import FakeRhx
    from ephymeris_sidecar.intan.tests.test_intan_service import settings_for

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
    from ephymeris_sidecar.intan.tests.test_intan_service import config

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
    await service.configure(
        session.id, _two_box_recording(tmp_path), "x",
        confirmation=rig.lifecycle.confirmations,
    )
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
    assert [(bool(r["startedAt"]), bool(r["endedAt"])) for r in runs] == [(True, True)]
    assert "Stop it from RHX" in service.status_json()["message"]


async def test_a_reconnect_stops_the_recording_an_unreachable_end_left_running(
    db, tmp_path, rhx  # noqa: ANN001
) -> None:
    """B20: RHX went on recording after the End that could not reach it. Once
    it is reachable again the stop owed is sent, and the next round's
    Record step is not refused with "RHX is already recording"."""
    fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_all(session.id)
    await _lose_rhx(rhx)
    await rig.lifecycle.end_round(session.id)
    assert fake.params["runmode"] == "Record"

    await fake.listen_again()
    await until(lambda: fake.params["runmode"] == "Stop")
    await until(lambda: service.status_json()["state"] == "idle")

    await service.configure(session.id, _two_box_recording(tmp_path), "y")
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
    assert len(runs) == 1


async def test_an_end_waits_while_rhx_may_still_be_writing_the_run(
    db, tmp_path, rhx  # noqa: ANN001
) -> None:
    """The link comes back but RHX's file stamp can't be read, so the run is
    not confirmed. RHX is in Record, maybe on this run: unsure keeps the grace
    period (End now is the escape). Only RHX seen out of Record skips it."""
    from ephymeris_sidecar.sessions.lifecycle import RECORDING_GRACE_S

    fake, service = rhx
    rig, session = await _recording_rig(db, tmp_path, rhx)
    await rig.lifecycle.start_all(session.id)
    await _lose_rhx(rhx)
    del fake.params["filename.activefiletimestamp"]
    await fake.listen_again()
    await until(lambda: "Lost contact" not in (service.status_json()["message"] or ""))

    await rig.lifecycle.end(session.id)

    assert rig.runner.ended_with.get("graceful_timeout_s") == RECORDING_GRACE_S
    assert len(rig.sessions.get_session(session.id).recording["runs"]) == 1


async def test_a_box_start_after_rhx_drops_names_the_lost_link(db, tmp_path, rhx) -> None:  # noqa: ANN001
    """B16: one box of a recording round is running and RHX's link drops.
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
    assert len(runs) == 1


# --- a per-box stop (port.stopSession) ---------------------------------------


async def test_a_stop_the_port_could_not_take_is_refused_by_box(rig) -> None:
    """The STOP did not go out (the port left the session, or the write
    failed): the operator is told, not answered as if the box were stopping."""
    session = rig.session()
    await rig.run_round(session)
    rig.runner.stop_refused.add(1)

    with pytest.raises(StopRefused) as refused:
        rig.lifecycle.stop_box(1)

    mapped = _mapped(refused.value)
    assert (mapped.code, mapped.detail) == ("ILLEGAL_TRANSITION", {"box": 1})


async def test_stopping_a_box_that_is_not_running_is_a_no_op(rig) -> None:
    """A box that already ended -- the board's end strobe raced the click."""
    session = rig.session()
    await rig.confirm(session)
    rig.lifecycle.stop_box(1)


# --- resume (DATA.md#continuing-between-rounds) -------------------------------


async def test_a_session_ended_too_early_can_be_continued_today(rig) -> None:
    session = rig.session()
    await rig.run_round(session)
    await rig.lifecycle.end(session.id)
    assert rig.sessions.get_session(session.id).status == "completed"

    resumed = await rig.lifecycle.resume(session.id)

    assert resumed.status == "running"
    assert rig.lifecycle.held == session.id
    assert rig.runner.configured_boxes() == []


async def test_a_crash_orphan_is_continued_with_its_open_round_closed(rig) -> None:
    session = rig.session()
    rig.sessions.set_rounds(
        session.id, [Round(order=0, started_at="2026-09-25T10:00:00")]
    )
    rig.sessions.set_status(session.id, "running")
    # A relaunched sidecar holds nothing.
    assert rig.lifecycle.held is None

    await rig.lifecycle.resume(session.id)

    runs = rig.sessions.get_session(session.id).rounds
    assert runs[0].ended_at is not None
    assert rig.lifecycle.held == session.id


async def test_resume_refuses_another_days_session(rig) -> None:
    session = rig.session(day="2020-01-01")
    rig.sessions.set_rounds(
        session.id, [Round(order=0, started_at="x", ended_at="y")]
    )
    rig.sessions.set_status(session.id, "completed")
    with pytest.raises(SessionRefused, match="today"):
        await rig.lifecycle.resume(session.id)


async def test_resume_refuses_a_session_that_never_ran_an_animal(rig) -> None:
    session = rig.session()
    rig.sessions.set_status(session.id, "completed")
    with pytest.raises(SessionRefused, match="never ran an animal"):
        await rig.lifecycle.resume(session.id)


async def test_resume_refuses_while_another_session_is_open(rig) -> None:
    first = rig.session()
    await rig.run_round(first)
    await rig.lifecycle.end(first.id)

    live = rig.session()
    await rig.run_round(live)

    with pytest.raises(SessionRefused, match="another session"):
        await rig.lifecycle.resume(first.id)


async def test_closing_out_an_orphan_leaves_the_live_session_alone(rig) -> None:
    orphan = rig.session()
    rig.sessions.set_status(orphan.id, "running")
    live = rig.session()
    await rig.run_round(live)
    rig.log.clear()

    await rig.lifecycle.end(orphan.id)

    assert rig.log == []
    assert rig.lifecycle.held == live.id
    assert rig.runner.configured_boxes() == [1, 2]


# --- the handlers' error mapping (app.py) ---------------------------------------


def _mapped(exc: BaseException):  # noqa: ANN202
    """The reply the server's error table gives `exc`; None is INTERNAL."""
    from ephymeris_sidecar.server import resolve_error
    from ephymeris_sidecar.wire_errors import ERRORS

    return resolve_error(ERRORS, exc, {})


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
        (WiringNotLoaded("wiring.json did not load"), "RIG_WIRING_UNLOADED", None),
    ]
    for exc, code, data in cases:
        mapped = _mapped(exc)
        assert isinstance(mapped, CommandError), exc
        assert mapped.code == code
        if data is not None:
            assert mapped.detail == data


def test_a_box_failure_nobody_names_surfaces_as_internal() -> None:
    assert _mapped(_box_refused(2, ValueError("odd"))) is None


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
        sketch_name="GRGL", start_command=build_start_command(None, {}), config_metadata={}, profile=None,
    )


@pytest.fixture(params=["FakeRunner", "SessionRunner"])
async def runner(request: pytest.FixtureRequest, tmp_path: Path, bench):  # noqa: ANN001, ANN201
    # Built inside the test's loop: the real runner binds to it, on real ports.
    made = FakeRunner([]) if request.param == "FakeRunner" else _real_runner(bench.ports)
    made.configure(tmp_path, "2O-Bdisc_12", [_box(2), _box(1)], session_id="s1")
    return made


async def test_a_runner_holds_the_mapping_it_was_given(runner) -> None:  # noqa: ANN001
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


async def test_a_running_box_is_writing_until_its_run_is_ended(runner) -> None:  # noqa: ANN001
    assert runner.writing_boxes() == []
    runner.start_box(1)
    assert runner.writing_boxes() == [1]
    await runner.end_all("operator stop")
    assert runner.writing_boxes() == []


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
    assert runner.configured_boxes() == []


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
    """`(service, set_up)`: `set_up(session, confirmation)` does what the
    Record step's `intan.configure` does, for the fake or against a fake RHX."""
    if request.param == "FakeIntan":
        fake = FakeIntan([])

        async def set_up(session_id: str, confirmation: int = 1) -> None:
            fake.set_up(session_id, confirmation)

        yield fake, set_up
        return

    from ephymeris_sidecar.intan.service import IntanService
    from tests.fake_rhx import FakeRhx
    from ephymeris_sidecar.intan.tests.test_intan_service import config, settings_for

    rhx = await FakeRhx().start()

    async def nothing(_message: dict) -> None:
        return None

    service = IntanService(
        loop=asyncio.get_running_loop(), broadcast=nothing,
        settings=settings_for(rhx, {1: 2, 3: 5}), rig_has_sync=lambda: True,
        pre_roll_s=0.0, post_roll_s=0.0, poll_s=0.05,
    )
    service.start()

    async def set_up(session_id: str, confirmation: int = 1) -> None:
        await service.configure(session_id, config(tmp_path), "x", confirmation=confirmation)

    try:
        yield service, set_up
    finally:
        await service.stop()
        await rhx.stop()


def _ready(service, session_id: str, confirmation: int = 1) -> bool:  # noqa: ANN001
    from ephymeris_sidecar.intan.client import RhxUnavailable

    try:
        service.refuse_unless_ready(session_id, confirmation)
    except (IntanNotReady, RhxUnavailable):
        return False
    return True


async def test_a_recording_is_set_up_for_one_session(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    assert not _ready(service, "s1")
    await set_up("s1")
    assert _ready(service, "s1")
    assert not _ready(service, "s2")


async def test_a_recording_is_set_up_for_one_mapping_confirmation(intan) -> None:  # noqa: ANN001
    """A mapping confirmed again after the Record step may have moved animals
    between boxes; RHX still holds the old ones (`RECORDING.md#record-step`)."""
    service, set_up = intan
    await set_up("s1", 4)
    assert _ready(service, "s1", 4)
    assert not _ready(service, "s1", 5)


async def test_a_recording_already_running_is_not_refused_by_a_later_confirmation(intan) -> None:  # noqa: ANN001
    """Its boxes are recording; the Record step can't be redone mid-run."""
    service, set_up = intan
    await set_up("s1", 4)
    await service.start_recording()
    assert _ready(service, "s1", 5)
    await service.stop_recording()


async def test_a_recording_runs_from_start_to_stop(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1")
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
    await set_up("s1")
    assert await service.stop_recording() is None
    assert not _ready(service, "s1")


async def test_letting_go_forgets_a_set_up_that_never_recorded(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1")
    service.release()
    assert not _ready(service, "s1")


async def test_letting_go_leaves_a_running_recording_alone(intan) -> None:  # noqa: ANN001
    service, set_up = intan
    await set_up("s1")
    await service.start_recording()
    service.release()
    assert service.is_recording and service.run_open_for("s1")
    await service.stop_recording()
