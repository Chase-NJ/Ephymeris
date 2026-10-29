"""The flash queue — `ARCHITECTURE.md#the-flash-queue`, `ports/flashing.py`.

Driven over the real `PortManager` and a fake board tool that notices what runs
beside what, because the rules here are about ports: which state a job waits
on, which it fails on, that only one compile runs on the rig at once, that a
session or Debug flash runs alone, and that restores upload side by side from
one compile.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest

from ephymeris_sidecar.boards.tool import DetectedBoard, FlashFailed
from ephymeris_sidecar.ports import flashing as flashing_module
from ephymeris_sidecar.ports.flashing import FlashJob, FlashQueue, SharedBuilds
from ephymeris_sidecar.ports.manager import FQBN, PortManager
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.protocol import Evt
from ephymeris_sidecar.settings import SidecarSettings
from ephymeris_sidecar.utility import UtilityBaseline

from .test_utility import (  # noqa: F401 - fake_serial is an autouse fixture
    TASK_PATH,
    UTILITY_PATH,
    UTILITY_PROFILE,
    FakeDiscovery,
    FakeTool,
    _noop_output,
    _noop_presence,
    fake_serial,
)

BOXES = (1, 2, 3)


class OverlapTool(FakeTool):
    """Records compiles and uploads in order, notices what overlaps, and can
    hold a box's upload until the test lets it go.

    `beside` is, for every compile and upload, the boxes whose ports were
    `FLASHING` when it began: the whole picture of what ran beside it."""

    def __init__(self) -> None:
        super().__init__()
        self.ports: PortManager | None = None
        self.compiling = 0
        self.compiles_overlapped = False
        self.compiles: list[str] = []
        #: The sketch folder each upload under way reads, by address.
        self.uploading: dict[str, str] = {}
        self.most_uploads = 0
        self.rebuilt_under_an_upload = False
        self.beside: list[tuple[str, frozenset[int]]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.started: list[str] = []
        #: What the board list reports, by hardware id. Remove one to unplug it.
        self.boards = {
            f"HW{b}": DetectedBoard(hardware_id=f"HW{b}", address=address(b), fqbn=FQBN)
            for b in BOXES
        }

    async def list_boards(self) -> list[DetectedBoard]:
        return list(self.boards.values())

    def _flashing(self) -> frozenset[int]:
        assert self.ports is not None
        return frozenset(
            box for box, state in self.ports.current_states().items()
            if state is PortState.FLASHING
        )

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:  # noqa: ANN001
        self.compiles.append(sketch_dir)
        self.beside.append(("compile", self._flashing()))
        self.compiling += 1
        self.compiles_overlapped = self.compiles_overlapped or self.compiling > 1
        self.rebuilt_under_an_upload = (
            self.rebuilt_under_an_upload or sketch_dir in self.uploading.values()
        )
        try:
            on_line("stdout", f"compiling {sketch_dir}")
            await asyncio.sleep(0.01)
            await super().compile(sketch_dir, fqbn, libraries_path, on_line)
        finally:
            self.compiling -= 1

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:  # noqa: ANN001
        self.started.append(address)
        self.beside.append(("upload", self._flashing()))
        self.uploading[address] = sketch_dir
        self.most_uploads = max(self.most_uploads, len(self.uploading))
        try:
            gate = self.gates.get(address)
            if gate is not None:
                await gate.wait()
            await super().upload(sketch_dir, fqbn, address, on_line)
        finally:
            del self.uploading[address]

    def hold(self, box: int) -> asyncio.Event:
        gate = self.gates[address(box)] = asyncio.Event()
        return gate


def address(box: int) -> str:
    return f"/dev/cu.box{box}"


class Rig:
    def __init__(self, reading=nullcontext) -> None:  # noqa: ANN001
        loop = asyncio.get_event_loop()
        self.tool = OverlapTool()
        self.events: list[dict] = []
        self.flashed: list[tuple[int, str, str]] = []

        async def broadcast(message: dict) -> None:
            self.events.append(message)

        self.ports = PortManager(
            loop=loop,
            tool=self.tool,
            on_state_change=lambda box, *_a: self.queue.port_changed(box),
            on_output=_noop_output,
            on_presence=_noop_presence,
        )
        self.tool.ports = self.ports
        settings = SidecarSettings.from_payload(
            {
                "defaultBaud": 9600,
                "boxes": [{"box": b, "hardwareId": f"HW{b}"} for b in BOXES],
            }
        )
        self.ports.update_settings(settings)
        self.queue = FlashQueue(
            loop=loop,
            ports=self.ports,
            discovery=FakeDiscovery,
            broadcast=broadcast,
            reading=reading,
            on_flashed=lambda *args: self.flashed.append(args),
        )

    def job(self, box: int, origin: str = "session", path: str = TASK_PATH, **extra) -> FlashJob:  # noqa: ANN003
        return FlashJob(box=box, origin=origin, prepare=lambda: path, sketch_path=path, **extra)

    async def settle(self) -> None:
        for _ in range(500):
            await asyncio.sleep(0.01)
            if self.queue.idle:
                await asyncio.sleep(0)  # let the last publish land
                return
        raise AssertionError("the flash queue never finished")

    def row(self, box: int) -> dict | None:
        return next(b for b in self.queue.status()["boxes"] if b["box"] == box)["job"]

    def states(self) -> set[PortState]:
        return {self.ports.handler(box).state for box in BOXES}

    def uploaded(self) -> list[str]:
        return [a.rsplit("box", 1)[-1] for a in self.tool.started]

    async def until(self, ready, what: str) -> None:  # noqa: ANN001
        for _ in range(200):
            await asyncio.sleep(0.01)
            if ready():
                return
        raise AssertionError(f"never saw {what}")

    def baseline(self) -> UtilityBaseline:
        return UtilityBaseline(
            loop=asyncio.get_event_loop(),
            ports=self.ports,
            discovery=FakeDiscovery,
            broadcast=lambda _m: asyncio.sleep(0),
            load_profile=lambda _path: UTILITY_PROFILE,
            is_utility=lambda sketch: sketch.path == UTILITY_PATH,
            flashes=self.queue,
        )


@pytest.fixture
async def rig() -> Rig:
    # Built inside the test's loop: the queue and the port manager bind to it.
    r = Rig()
    await r.ports.poll_once()  # every board present
    return r


def run_a_session(rig: Rig, box: int):  # noqa: ANN201
    """Hold a box `IN_SESSION`, the state a session or Debug flash waits on.
    Returns the claim, whose `release` ends it."""
    return rig.ports.claim_session(
        box, "START", on_ready=lambda _seed: None, on_strobe=lambda _code, _ts: None,
        on_lost=lambda _reason: None,
    )


# --- what runs beside what ---------------------------------------------------


async def test_a_session_or_debug_flash_runs_alone(rig: Rig) -> None:
    rig.queue.submit(
        [
            rig.job(1, "baseline", UTILITY_PATH),
            rig.job(2, "session"),
            rig.job(3, "debug"),
        ]
    )
    await rig.settle()

    assert rig.uploaded() == ["1", "2", "3"]
    assert not rig.tool.compiles_overlapped
    # Every compile and upload ran with only its own box flashing.
    assert all(len(flashing) == 1 for _phase, flashing in rig.tool.beside)
    assert [(box, origin) for box, _path, origin in rig.flashed] == [
        (1, "baseline"), (2, "session"), (3, "debug"),
    ]


async def test_restores_compile_once_and_upload_side_by_side(rig: Rig) -> None:
    gates = [rig.tool.hold(box) for box in BOXES]
    rig.queue.submit(rig.job(box, "baseline", UTILITY_PATH) for box in BOXES)
    await rig.until(lambda: len(rig.tool.started) == len(BOXES), "every upload under way")

    assert rig.tool.most_uploads == len(BOXES)
    assert rig.tool.compiles == [UTILITY_PATH]
    assert rig.states() == {PortState.FLASHING}

    for gate in gates:
        gate.set()
    await rig.settle()
    assert not rig.tool.rebuilt_under_an_upload
    assert sorted(box for box, _path, _origin in rig.flashed) == list(BOXES)
    assert all(rig.ports.carried(box).path == UTILITY_PATH for box in BOXES)
    assert rig.states() == {PortState.IDLE}


async def test_a_failed_compile_fails_every_restore_that_shared_it(rig: Rig) -> None:
    rig.tool.fail = FlashFailed("compile", "compile failed: avr-g++ error")
    rig.queue.submit(rig.job(box, "baseline", UTILITY_PATH) for box in BOXES)
    await rig.settle()

    assert rig.tool.compiles == [UTILITY_PATH]
    assert rig.uploaded() == []
    assert {rig.ports.handler(box).state for box in BOXES} == {PortState.ERROR}
    assert rig.flashed == []


async def test_a_session_flash_waits_for_the_restore_of_its_box(rig: Rig) -> None:
    """A session job queued while a restore uploads to its box neither waits
    on the port (and times out) nor uploads beside it, and nothing queued
    behind it passes it."""
    gate = rig.tool.hold(1)
    rig.queue.submit([rig.job(1, "baseline", UTILITY_PATH)])
    await rig.until(lambda: rig.tool.started, "the restore's upload")
    rig.queue.submit([rig.job(1), rig.job(2)])
    for _ in range(20):
        await asyncio.sleep(0.01)
    assert rig.uploaded() == ["1"]
    assert rig.row(1)["state"] == "queued"
    assert rig.row(2)["state"] == "queued"

    gate.set()
    await rig.settle()
    assert rig.uploaded() == ["1", "1", "2"]
    assert [(box, origin) for box, _path, origin in rig.flashed] == [
        (1, "baseline"), (1, "session"), (2, "session"),
    ]
    assert rig.ports.carried(1).path == TASK_PATH
    assert all(len(flashing) == 1 for _phase, flashing in rig.tool.beside)


async def test_restores_queued_behind_a_debug_flash_wait_for_it(rig: Rig) -> None:
    gate = rig.tool.hold(3)
    rig.queue.submit([rig.job(3, "debug")])
    await rig.until(lambda: rig.tool.started, "the Debug flash's upload")
    rig.queue.submit(rig.job(box, "baseline", UTILITY_PATH) for box in (1, 2))
    for _ in range(20):
        await asyncio.sleep(0.01)
    assert rig.uploaded() == ["3"]

    gate.set()
    await rig.settle()
    assert sorted(rig.uploaded()) == ["1", "2", "3"]
    assert rig.uploaded()[0] == "3"


async def test_a_compile_waits_for_uploads_of_an_older_build_of_its_folder() -> None:
    """An upload reads the folder's build from `arduino-cli`'s build
    directory: a compile of a changed folder must not rewrite it mid-upload,
    and an upload of the same build must not compile it again."""
    builds = SharedBuilds()
    events: list[str] = []
    uploading = asyncio.Event()
    finish = asyncio.Event()

    def compile(name: str):  # noqa: ANN202
        async def run() -> None:
            events.append(f"compile {name}")
        return run

    async def flash(name: str, fingerprint: str, hold: bool = False) -> None:
        async with builds.gate("/sk/Utility/BOX_Utility", fingerprint, compile(name)):
            events.append(f"upload {name}")
            if hold:
                uploading.set()
                await finish.wait()
            events.append(f"uploaded {name}")

    first = asyncio.ensure_future(flash("a", "v1", hold=True))
    await uploading.wait()
    joiner = asyncio.ensure_future(flash("b", "v1"))
    changed = asyncio.ensure_future(flash("c", "v2"))
    await joiner
    await asyncio.sleep(0.01)
    assert events == ["compile a", "upload a", "upload b", "uploaded b"]

    finish.set()
    await asyncio.gather(first, changed)
    assert events[4:] == ["uploaded a", "compile c", "upload c", "uploaded c"]


async def test_a_busy_port_waits_without_holding_up_the_rest(rig: Rig) -> None:
    claim = run_a_session(rig, 1)
    rig.queue.submit([rig.job(1), rig.job(2)])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.uploaded() == ["2"]:
            break
    assert rig.uploaded() == ["2"]
    assert rig.row(1)["state"] == "waiting"
    assert "in_session" in rig.row(1)["detail"]

    claim.release("the run ended")  # the port's own change wakes the job
    await rig.settle()
    assert rig.uploaded() == ["2", "1"]
    assert rig.row(1)["state"] == "done"


async def test_a_console_is_taken_for_a_session_flash(rig: Rig) -> None:
    rig.ports.open_passthrough(1)
    rig.queue.submit([rig.job(1)])
    await rig.settle()
    # Lands in IDLE for the runner, not back in the console.
    assert rig.ports.handler(1).state is PortState.IDLE
    assert rig.row(1)["state"] == "done"


async def test_a_faulted_port_fails_at_once(rig: Rig) -> None:
    rig.ports.handler(1).force_error("an earlier flash failed")
    rig.queue.submit([rig.job(1), rig.job(2)])
    await rig.settle()

    assert rig.row(1)["state"] == "failed"
    assert "acknowledge it" in rig.row(1)["detail"]
    assert rig.uploaded() == ["2"]


async def test_a_port_that_never_frees_gives_up(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(flashing_module, "PORT_WAIT_S", 0.05)
    monkeypatch.setattr(flashing_module, "TICK_S", 0.01)
    claim = run_a_session(rig, 1)
    rig.queue.submit([rig.job(1)])
    await rig.settle()
    claim.release("test over")

    assert rig.row(1)["state"] == "failed"
    assert "stayed in_session" in rig.row(1)["detail"]
    assert rig.uploaded() == []


async def test_a_box_with_no_board_fails_by_name(rig: Rig) -> None:
    del rig.tool.boards["HW2"]  # unplugged
    await rig.ports.poll_once()
    rig.queue.submit([rig.job(2)])
    await rig.settle()
    assert rig.row(2)["state"] == "failed"
    assert "HW2" in rig.row(2)["detail"]


# --- outcomes ---------------------------------------------------------------


async def test_a_failed_flash_says_why_and_leaves_the_fault_to_the_operator(rig: Rig) -> None:
    rig.tool.fail = FlashFailed("compile", "compile failed: avr-g++ error")
    rig.queue.submit([rig.job(1, "debug"), rig.job(2, "debug")])
    await rig.settle()

    assert rig.row(1) == {
        "origin": "debug",
        "sketchPath": TASK_PATH,
        "sketchName": "GRGL",
        "state": "failed",
        "detail": "compile failed: avr-g++ error",
    }
    # They asked for it, so the ERROR is theirs to acknowledge; and one failure
    # does not stop the rest.
    assert rig.ports.handler(1).state is PortState.ERROR
    assert rig.row(2)["state"] == "failed"
    assert rig.flashed == []


async def test_a_sketch_gone_from_the_library_is_not_flashed(rig: Rig) -> None:
    rig.queue.submit([rig.job(1, "debug", "/sk/Behavior/Deleted")])
    await rig.settle()
    assert rig.row(1)["state"] == "failed"
    assert "isn't in the sketch library" in rig.row(1)["detail"]
    assert rig.uploaded() == []


async def test_a_debug_flash_opens_its_console(rig: Rig) -> None:
    rig.queue.submit([rig.job(1, "debug", baud=115200)])
    await rig.settle()

    handler = rig.ports.handler(1)
    assert (handler.state, handler.baud) == (PortState.PASSTHROUGH, 115200)
    assert rig.row(1)["detail"] == "console open"


async def test_status_says_what_each_board_carries(rig: Rig) -> None:
    rig.queue.submit([rig.job(2)])
    await rig.settle()

    boxes = {b["box"]: b for b in rig.queue.status()["boxes"]}
    assert boxes[2]["carries"] == {"path": TASK_PATH, "name": "GRGL"}
    assert boxes[1] == {"box": 1, "job": None, "carries": None}
    published = [m["data"] for m in rig.events if m.get("evt") == Evt.FLASH_QUEUE]
    assert published[-1] == rig.queue.status()


async def test_progress_goes_out_by_box_but_a_restore_is_only_logged(rig: Rig) -> None:
    rig.queue.submit([rig.job(1, "baseline", UTILITY_PATH), rig.job(2, "session")])
    await rig.settle()

    progress = [m["data"] for m in rig.events if m.get("evt") == Evt.FLASH_PROGRESS]
    assert {p["box"] for p in progress} == {2}
    assert all("corr" not in m for m in rig.events if m.get("evt") == Evt.FLASH_PROGRESS)


# --- cancelling ---------------------------------------------------------------


async def test_cancel_drops_what_is_queued_and_lets_the_flash_in_hand_finish(rig: Rig) -> None:
    gate = rig.tool.hold(1)
    rig.queue.submit([rig.job(1, "debug"), rig.job(2, "debug")])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.tool.started:
            break

    rig.queue.cancel()
    gate.set()
    await rig.settle()

    assert rig.uploaded() == ["1"]
    assert rig.row(1)["state"] == "done"
    assert rig.row(2) is None


async def test_a_cleared_row_is_not_revived_by_a_late_outcome(rig: Rig) -> None:
    """A new mapping starts clean: the old mapping's flash landing afterwards
    must not show its box as flashed for the new one."""
    gate = rig.tool.hold(1)
    rig.queue.submit([rig.job(1)])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.tool.started:
            break

    rig.queue.cancel(origins=("session",), clear=True)
    gate.set()
    await rig.settle()

    assert rig.uploaded() == ["1"]
    assert rig.row(1) is None


async def test_asking_again_keeps_the_place_in_the_queue(rig: Rig) -> None:
    gate = rig.tool.hold(3)
    rig.queue.submit([rig.job(3), rig.job(1), rig.job(2)])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.tool.started:
            break
    rig.queue.submit([rig.job(1)])
    gate.set()
    await rig.settle()
    assert rig.uploaded() == ["3", "1", "2"]


# --- the baseline's last-moment check ----------------------------------------


async def test_a_queued_restore_never_takes_a_console_opened_while_it_waited(rig: Rig) -> None:
    """`ARCHITECTURE.md#three-rules-it-never-breaks`, across a queue: the restore
    was wanted when it was queued, and the operator opened a console before its
    turn came. It must look again at the last moment, not trust the queueing."""
    baseline = rig.baseline()
    gate = rig.tool.hold(2)
    rig.queue.submit([rig.job(2, "debug")])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.tool.started:
            break
    baseline.ensure([1])
    rig.ports.open_passthrough(1)

    gate.set()
    await rig.settle()

    assert rig.uploaded() == ["2"]
    assert rig.ports.handler(1).state is PortState.PASSTHROUGH
    assert next(b for b in baseline.status()["boxes"] if b["box"] == 1)["state"] == "busy"
    # A restore that decided not to flash leaves no row behind.
    assert rig.row(1) is None


async def test_a_hold_lets_every_restore_in_hand_finish(rig: Rig) -> None:
    baseline = rig.baseline()
    gates = [rig.tool.hold(box) for box in BOXES]
    baseline.ensure()
    await rig.until(lambda: len(rig.tool.started) == len(BOXES), "every upload under way")

    baseline.hold()
    for gate in gates:
        gate.set()
    await rig.settle()

    # Stopping an upload part-way leaves a board nobody can name: all three land.
    assert sorted(rig.uploaded()) == ["1", "2", "3"]
    assert rig.states() == {PortState.IDLE}
    assert all(rig.ports.carried(box).path == UTILITY_PATH for box in BOXES)


async def test_a_hold_drops_queued_restores(rig: Rig) -> None:
    baseline = rig.baseline()
    gate = rig.tool.hold(3)
    rig.queue.submit([rig.job(3, "debug")])
    await rig.until(lambda: rig.tool.started, "the Debug flash's upload")
    baseline.ensure([1, 2])  # queued behind a flash that runs alone

    baseline.hold()
    gate.set()
    await rig.settle()

    assert rig.uploaded() == ["3"]


async def test_a_restore_under_way_decides_again_after_a_hold() -> None:
    """A restore dispatched beside others but still waiting for the rig
    definition's read side decides only once it has it: a hold in between
    leaves its box alone."""
    from ephymeris_sidecar.rig.definition import _ReadWriteLock

    lock = _ReadWriteLock()
    rig = Rig(reading=lock.reading)
    await rig.ports.poll_once()
    baseline = rig.baseline()
    writing = lock.writing()
    await writing.__aenter__()  # a wiring save in progress
    baseline.ensure()
    await asyncio.sleep(0.05)
    assert rig.queue._running  # dispatched, every one waiting to read

    baseline.hold()
    await writing.__aexit__(None, None, None)
    await rig.settle()

    assert rig.uploaded() == []
    assert rig.states() == {PortState.IDLE}
