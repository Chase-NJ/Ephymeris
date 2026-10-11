"""The hardware utility baseline — `ARCHITECTURE.md#hardware-utility-baseline`.

Exercised against the real `PortManager` and a fake board tool, because the
rules that matter here are all about the port state machine: which states a
restore may take, what a failed flash leaves behind, and who owns a console.
A mock port manager would let every one of those through.
"""

from __future__ import annotations

import asyncio
from contextlib import nullcontext

import pytest

from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard, FlashFailed
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports import manager as manager_module
from ephymeris_sidecar.ports.flashing import FlashQueue
from ephymeris_sidecar.ports.manager import FQBN, PortManager
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.settings import SidecarSettings
from ephymeris_sidecar.tasks.profile import (
    Identify,
    TaskProfile,
    Telemetry,
    parse_profile,
    TaskProfileError,
)
from ephymeris_sidecar.utility import UtilityBaseline, UtilityUnavailable

HWID = "TESTBOARD01"
ADDRESS = "/dev/cu.faketest"
UTILITY_PATH = "/sk/Utility/BOX_Utility"
TASK_PATH = "/sk/Behavior/GRGL"


# --- fakes ------------------------------------------------------------------


class FakeTool(BoardTool):
    def __init__(self) -> None:
        self.uploads: list[str] = []
        self.fail: FlashFailed | None = None

    async def list_boards(self) -> list[DetectedBoard]:
        return [DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)]

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:  # noqa: ANN001
        if self.fail:
            raise self.fail

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:  # noqa: ANN001
        self.uploads.append(sketch_dir)


class FakeSerial:
    """A board that greets on open and answers every write with a STATUS line."""

    instances: list["FakeSerial"] = []
    #: Set false to model a board that never answers — a baud mismatch.
    answers = True

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate")
        self.dtr = True
        self.closed = False
        self.written: list[str] = []
        self._pending = bytearray(b"BOX Utility ready.\n" if FakeSerial.answers else b"")
        FakeSerial.instances.append(self)

    @property
    def in_waiting(self) -> int:
        return len(self._pending)

    def read(self, size: int = 1) -> bytes:
        if not self._pending:
            import time

            time.sleep(0.01)  # behave like a blocking read timeout
            return b""
        chunk = bytes(self._pending[:size])
        del self._pending[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.append(data.decode().strip())
        if FakeSerial.answers:
            self._pending.extend(b"STATUS mode=idle light=1\n")
        return len(data)

    def flush(self) -> None:
        pass

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeSketch:
    def __init__(self, path: str, name: str) -> None:
        self.path = path
        self.name = name


class FakeDiscovery:
    libraries_path = "/sk/libraries"
    sketches = [
        FakeSketch(UTILITY_PATH, "BOX_Utility"),
        FakeSketch(TASK_PATH, "GRGL"),
    ]


UTILITY_PROFILE = TaskProfile(
    task_name="Box Utility",
    kind="utility",
    identify=Identify(on="ON LIGHT", off="OFF LIGHT"),
    telemetry=Telemetry(match="STATUS", fields=[]),
)


@pytest.fixture(autouse=True)
def fake_serial(monkeypatch: pytest.MonkeyPatch):
    FakeSerial.instances = []
    FakeSerial.answers = True
    monkeypatch.setattr(handler_module.serial, "Serial", FakeSerial)
    monkeypatch.setattr(manager_module.serial, "Serial", FakeSerial)
    yield FakeSerial


async def _noop_output(_box, _lines):  # noqa: ANN001
    pass


async def _noop_presence(_boards):  # noqa: ANN001
    pass


def make_baseline(
    profile: TaskProfile | None = UTILITY_PROFILE,
    sketch_path: str | None = UTILITY_PATH,
    reading=nullcontext,  # noqa: ANN001
) -> tuple[UtilityBaseline, PortManager, FakeTool, list[dict]]:
    tool = FakeTool()
    manager = PortManager(
        loop=asyncio.get_event_loop(),
        tool=tool,
        on_state_change=lambda *_a: None,
        on_output=_noop_output,
        on_presence=_noop_presence,
    )
    settings = SidecarSettings.from_payload(
        {
            "defaultBaud": 9600,
            "boxes": [{"box": 1, "hardwareId": HWID}],
        }
    )
    manager.update_settings(settings)
    manager._presence = {HWID: DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)}

    events: list[dict] = []

    async def broadcast(message: dict) -> None:
        events.append(message)

    flashes = FlashQueue(
        loop=asyncio.get_event_loop(),
        ports=manager,
        discovery=FakeDiscovery,
        broadcast=broadcast,
        reading=reading,
    )
    baseline = UtilityBaseline(
        loop=asyncio.get_event_loop(),
        ports=manager,
        discovery=FakeDiscovery,
        broadcast=broadcast,
        load_profile=lambda _path: profile,
        # The fakes have no folders to read an `.ino` from; name the utility
        # the way the real predicate would find it.
        is_utility=lambda sketch: sketch_path is not None and sketch.path == sketch_path,
        flashes=flashes,
    )
    baseline.update_settings(settings)
    return baseline, manager, tool, events


async def settle(baseline: UtilityBaseline) -> None:
    """Let the flash queue the baseline restores through run dry."""
    for _ in range(400):
        await asyncio.sleep(0.01)
        if baseline._flashes.idle:
            return
    raise AssertionError("the flash queue never finished")


def box_state(baseline: UtilityBaseline, box: int = 1) -> dict:
    return next(b for b in baseline.status()["boxes"] if b["box"] == box)


# --- restores ---------------------------------------------------------------


async def test_restores_an_idle_box_once() -> None:
    baseline, manager, tool, _ = make_baseline()

    baseline.ensure()
    await settle(baseline)

    assert tool.uploads == [UTILITY_PATH]
    assert manager.handler(1).state is PortState.IDLE
    assert box_state(baseline)["state"] == "ready"

    # A box already believed to be at baseline is not reflashed — this is what
    # keeps the idle-transition hook from turning into a flash loop.
    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH]


async def test_a_rig_definition_write_waits_for_a_restore_then_gets_its_own() -> None:
    """A write that rebuilt the utility while it was being flashed would have
    `rebuilt()` undone by the restore recording what it flashed: the box would
    read ready on the old build. The queue holding the read side for the whole
    restore makes the write wait, and its `rebuilt()` restores the box again."""
    from ephymeris_sidecar.rig.definition import _ReadWriteLock

    lock = _ReadWriteLock()
    baseline, _manager, tool, _ = make_baseline(reading=lock.reading)
    uploading = asyncio.Event()
    release = asyncio.Event()
    upload = tool.upload

    async def slow_upload(*args):
        uploading.set()
        await release.wait()
        await upload(*args)

    tool.upload = slow_upload
    baseline.ensure()
    await asyncio.wait_for(uploading.wait(), 5)

    async def write() -> None:
        async with lock.writing():
            baseline.rebuilt()

    rebuild = asyncio.create_task(write())
    await asyncio.sleep(0.05)
    assert not rebuild.done(), "the write rebuilt the folder under a restore's compile"

    release.set()
    await rebuild
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH, UTILITY_PATH]
    assert box_state(baseline)["state"] == "ready"


async def test_force_reflashes_a_ready_box() -> None:
    baseline, _manager, tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)

    baseline.ensure(force=True)
    await settle(baseline)

    assert tool.uploads == [UTILITY_PATH, UTILITY_PATH]


async def test_never_takes_a_port_someone_else_owns() -> None:
    """`ARCHITECTURE.md#three-rules-it-never-breaks` — a console the user opened is not a restore opportunity."""
    baseline, manager, tool, _ = make_baseline()
    manager.open_passthrough(1)

    baseline.ensure()
    await settle(baseline)

    assert tool.uploads == []
    assert manager.handler(1).state is PortState.PASSTHROUGH
    assert box_state(baseline)["state"] == "busy"


async def test_hold_suspends_restores_until_released() -> None:
    """The session window: restoring here would erase the task sketch."""
    baseline, _manager, tool, _ = make_baseline()
    baseline.hold()

    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == []
    assert baseline.status()["held"] is True

    baseline.release()
    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH]


async def test_a_session_flash_invalidates_the_belief() -> None:
    baseline, manager, tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)

    # As a session flash does it: the flash records what the board carries,
    # then the baseline hears of it.
    await manager.flash(1, TASK_PATH, "GRGL", None, lambda *a: None,
                        suppress_passthrough_resume=True)
    baseline.note_flashed(1, TASK_PATH)
    assert box_state(baseline)["state"] == "unknown"

    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH, TASK_PATH, UTILITY_PATH]


async def test_a_failed_restore_clears_the_error_and_stops_retrying() -> None:
    """A background action must not leave the rig needing manual clearing."""
    baseline, manager, tool, _ = make_baseline()
    tool.fail = FlashFailed("compile", "compile failed", detail="avr-g++: error")

    baseline.ensure()
    await settle(baseline)

    state = box_state(baseline)
    assert state["state"] == "failed"
    assert "compile failed" in (state["detail"] or "")
    # Not ERROR: the operator never asked for this flash, so they are not left
    # with an acknowledgement to make before the box can be used.
    assert manager.handler(1).state is PortState.IDLE

    # Sticky — otherwise the ERROR→IDLE transition above would trigger another
    # doomed attempt, forever.
    tool.fail = None
    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == []


async def test_a_vanished_board_drops_the_belief() -> None:
    baseline, manager, tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)

    # As the presence poll does it: the manager notices, then the baseline.
    board = manager._presence[HWID]
    manager._update_presence([])
    baseline.note_presence([])
    assert box_state(baseline)["state"] == "unavailable"

    manager._update_presence([board])
    baseline.note_presence([HWID])
    baseline.ensure()
    await settle(baseline)
    # The board that came back may not be the one that left.
    assert tool.uploads == [UTILITY_PATH, UTILITY_PATH]


# --- resolution -------------------------------------------------------------


async def test_a_non_utility_sketch_is_refused_with_a_reason() -> None:
    behavior = TaskProfile(task_name="GRGL", kind="behavior")
    baseline, _manager, tool, _ = make_baseline(profile=behavior)

    baseline.ensure()
    await settle(baseline)

    assert tool.uploads == []
    assert "must declare" in (baseline.status()["message"] or "")


async def test_a_library_without_a_box_utility_says_so() -> None:
    """The utility is generated and found, never chosen — so its absence is a
    damaged install worth a sentence, and nothing is flashed."""
    baseline, _manager, tool, _ = make_baseline(profile=None, sketch_path=None)
    baseline.ensure()
    await settle(baseline)
    status = baseline.status()
    assert status["configured"] is False
    assert "no box utility" in (status["message"] or "")
    assert status["canIdentify"] is False
    assert tool.uploads == []


async def test_a_rebuilt_utility_is_restored_to_every_box_that_carried_the_old_one() -> None:
    """A rewiring rebuilds the utility; every box still carries the old build
    (old pins, old channel names), so believing it current would be wrong."""
    baseline, _manager, tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH]

    baseline.rebuilt()
    await settle(baseline)
    assert tool.uploads == [UTILITY_PATH, UTILITY_PATH]


# --- identify ---------------------------------------------------------------


async def test_identify_lights_a_baseline_box_and_puts_it_out(fake_serial) -> None:
    baseline, manager, _tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)

    delivered, state = await baseline.identify(1, True)
    assert delivered is True
    assert state["identifying"] is True
    assert manager.handler(1).state is PortState.PASSTHROUGH
    assert fake_serial.instances[-1].written == ["ON LIGHT"]

    delivered, state = await baseline.identify(1, False)
    assert delivered is True
    assert state["identifying"] is False
    # We opened the console, so we close it again.
    assert manager.handler(1).state is PortState.IDLE


async def test_identify_leaves_a_users_console_open(fake_serial) -> None:
    baseline, manager, _tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)
    manager.open_passthrough(1)

    await baseline.identify(1, True)
    await baseline.identify(1, False)

    assert manager.handler(1).state is PortState.PASSTHROUGH
    assert fake_serial.instances[-1].written == ["ON LIGHT", "OFF LIGHT"]


async def test_identify_reports_a_silent_board_rather_than_claiming_success() -> None:
    """The baud-mismatch case — sent into the void must not read as delivered."""
    baseline, _manager, _tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)
    FakeSerial.answers = False

    delivered, state = await baseline.identify(1, True)

    assert delivered is False
    assert "baud" in (state["detail"] or "")


async def test_identify_declines_a_box_not_at_baseline() -> None:
    baseline, _manager, _tool, _ = make_baseline()

    delivered, _state = await baseline.identify(1, True)

    assert delivered is False


async def test_identify_without_an_identify_pair_is_a_typed_refusal() -> None:
    plain = TaskProfile(task_name="Box Utility", kind="utility")
    baseline, _manager, _tool, _ = make_baseline(profile=plain)

    with pytest.raises(UtilityUnavailable):
        await baseline.identify(1, True)


async def test_stop_extinguishes_everything(fake_serial) -> None:
    baseline, manager, _tool, _ = make_baseline()
    baseline.ensure()
    await settle(baseline)
    await baseline.identify(1, True)

    await baseline.stop()

    assert fake_serial.instances[-1].written[-1] == "OFF LIGHT"
    assert manager.handler(1).state is PortState.IDLE


# --- the profile field ------------------------------------------------------


def test_identify_parses_from_task_json() -> None:
    profile = parse_profile(
        {
            "taskName": "Box Utility",
            "kind": "utility",
            "identify": {"on": "ON LIGHT", "off": "OFF LIGHT"},
        }
    )
    assert profile.identify == Identify(on="ON LIGHT", off="OFF LIGHT")
    assert profile.to_json()["identify"] == {"on": "ON LIGHT", "off": "OFF LIGHT"}


def test_a_half_declared_identify_is_malformed() -> None:
    """A box that can be lit but not unlit would announce itself forever."""
    with pytest.raises(TaskProfileError):
        parse_profile(
            {"taskName": "Box Utility", "kind": "utility", "identify": {"on": "ON LIGHT"}}
        )


def test_no_identify_block_is_the_normal_case() -> None:
    assert parse_profile({"taskName": "GRGL"}).identify is None
    assert "identify" not in parse_profile({"taskName": "GRGL"}).to_json()
