"""The flash queue — `ARCHITECTURE.md#the-flash-queue`, `ports/flashing.py`.

Driven over the real `PortManager` and a fake board tool that notices two
flashes overlapping, because the rules here are about ports: which state a job
waits on, which it fails on, and that only one compile runs on the rig at once.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest

from ephymeris_sidecar.boards.tool import DetectedBoard, FlashFailed
from ephymeris_sidecar.ports import flashing as flashing_module
from ephymeris_sidecar.ports.flashing import FlashJob, FlashQueue
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
    """Records uploads in order, flags any two flashes at once, and can hold a
    box's upload until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.overlapped = False
        self.gates: dict[str, asyncio.Event] = {}
        self.started: list[str] = []

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:  # noqa: ANN001
        self.active += 1
        self.overlapped = self.overlapped or self.active > 1
        try:
            on_line("stdout", f"compiling {sketch_dir}")
            await asyncio.sleep(0.01)
            await super().compile(sketch_dir, fqbn, libraries_path, on_line)
        except BaseException:
            self.active -= 1
            raise

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:  # noqa: ANN001
        try:
            self.started.append(address)
            gate = self.gates.get(address)
            if gate is not None:
                await gate.wait()
            await super().upload(sketch_dir, fqbn, address, on_line)
        finally:
            self.active -= 1

    def hold(self, box: int) -> asyncio.Event:
        gate = self.gates[address(box)] = asyncio.Event()
        return gate


def address(box: int) -> str:
    return f"/dev/cu.box{box}"


class Rig:
    def __init__(self) -> None:
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
        settings = SidecarSettings.from_payload(
            {
                "defaultBaud": 9600,
                "boxes": [{"box": b, "hardwareId": f"HW{b}"} for b in BOXES],
            }
        )
        self.ports.update_settings(settings)
        self.ports._presence = {
            f"HW{b}": DetectedBoard(hardware_id=f"HW{b}", address=address(b), fqbn=FQBN)
            for b in BOXES
        }
        self.queue = FlashQueue(
            loop=loop,
            ports=self.ports,
            discovery=FakeDiscovery,
            broadcast=broadcast,
            reading=nullcontext,
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

    def uploaded(self) -> list[str]:
        return [a.rsplit("box", 1)[-1] for a in self.tool.started]


@pytest.fixture
async def rig() -> Rig:
    # Built inside the test's loop: the queue and the port manager bind to it.
    return Rig()


# --- one at a time ----------------------------------------------------------


async def test_never_two_flashes_at_once_whoever_asked(rig: Rig) -> None:
    rig.queue.submit(
        [
            rig.job(1, "baseline", UTILITY_PATH),
            rig.job(2, "session"),
            rig.job(3, "debug"),
        ]
    )
    await rig.settle()

    assert rig.uploaded() == ["1", "2", "3"]
    assert not rig.tool.overlapped
    assert [(box, origin) for box, _path, origin in rig.flashed] == [
        (1, "baseline"), (2, "session"), (3, "debug"),
    ]


async def test_a_busy_port_waits_without_holding_up_the_rest(rig: Rig) -> None:
    rig.ports.handler(1)._state = PortState.IN_SESSION
    rig.queue.submit([rig.job(1), rig.job(2)])
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.uploaded() == ["2"]:
            break
    assert rig.uploaded() == ["2"]
    assert rig.row(1)["state"] == "waiting"
    assert "in_session" in rig.row(1)["detail"]

    rig.ports.handler(1)._state = PortState.IDLE
    rig.queue.port_changed(1)
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
    rig.ports.handler(1)._state = PortState.RESETTING
    rig.queue.submit([rig.job(1)])
    await rig.settle()

    assert rig.row(1)["state"] == "failed"
    assert "stayed resetting" in rig.row(1)["detail"]
    assert rig.uploaded() == []


async def test_a_box_with_no_board_fails_by_name(rig: Rig) -> None:
    rig.ports._presence.pop("HW2")
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
    baseline = UtilityBaseline(
        loop=asyncio.get_event_loop(),
        ports=rig.ports,
        discovery=FakeDiscovery,
        broadcast=lambda _m: asyncio.sleep(0),
        load_profile=lambda _path: UTILITY_PROFILE,
        is_utility=lambda sketch: sketch.path == UTILITY_PATH,
        flashes=rig.queue,
    )
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


async def test_a_hold_drops_queued_restores(rig: Rig) -> None:
    baseline = UtilityBaseline(
        loop=asyncio.get_event_loop(),
        ports=rig.ports,
        discovery=FakeDiscovery,
        broadcast=lambda _m: asyncio.sleep(0),
        load_profile=lambda _path: UTILITY_PROFILE,
        is_utility=lambda sketch: sketch.path == UTILITY_PATH,
        flashes=rig.queue,
    )
    gate = rig.tool.hold(1)
    baseline.ensure()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if rig.tool.started:
            break

    baseline.hold()
    gate.set()
    await rig.settle()

    # The restore in hand finished; the two behind it never started.
    assert rig.uploaded() == ["1"]
