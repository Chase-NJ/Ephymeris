"""Flash and reset orchestration — `dashboard.md` §6.1, §5, §3.3."""

from __future__ import annotations

import asyncio

import pytest

from ephymeris_sidecar.boards.cli_tool import _failure_message
from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard, FlashFailed
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports import manager as manager_module
from ephymeris_sidecar.ports.manager import FQBN, PortManager, PortNotBound
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.settings import SidecarSettings

HWID = "TESTBOARD01"
ADDRESS = "/dev/cu.faketest"


class FakeTool(BoardTool):
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_compile: FlashFailed | None = None
        self.fail_upload: FlashFailed | None = None

    async def list_boards(self) -> list[DetectedBoard]:
        return [DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)]

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:
        self.calls.append(("compile", sketch_dir, fqbn, libraries_path))
        on_line("stdout", "compiling…")
        if self.fail_compile:
            raise self.fail_compile

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:
        self.calls.append(("upload", sketch_dir, fqbn, address))
        on_line("stderr", "avrdude: writing flash")
        if self.fail_upload:
            raise self.fail_upload


class FakeSerial:
    instances: list["FakeSerial"] = []

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate")
        self.dtr = True
        self.closed = False
        self.dtr_history: list[bool] = []
        FakeSerial.instances.append(self)

    @property
    def in_waiting(self) -> int:
        return 0

    def read(self, _size: int = 1) -> bytes:
        import time as _time

        _time.sleep(0.05)  # behave like a blocking read timeout
        return b""

    def write(self, data: bytes) -> int:
        return len(data)

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def __setattr__(self, name, value) -> None:
        if name == "dtr" and "dtr_history" in self.__dict__:
            self.__dict__["dtr_history"].append(value)
        super().__setattr__(name, value)


@pytest.fixture(autouse=True)
def fake_serial(monkeypatch: pytest.MonkeyPatch):
    FakeSerial.instances = []
    monkeypatch.setattr(handler_module.serial, "Serial", FakeSerial)
    monkeypatch.setattr(manager_module.serial, "Serial", FakeSerial)
    yield FakeSerial


async def _noop_output(_box, _lines):  # noqa: ANN001
    pass


async def _noop_presence(_boards):  # noqa: ANN001
    pass


def make_manager() -> tuple[PortManager, FakeTool, list[tuple], list[tuple]]:
    tool = FakeTool()
    states: list[tuple] = []
    progress: list[tuple] = []
    manager = PortManager(
        loop=asyncio.get_event_loop(),
        tool=tool,
        on_state_change=lambda *a: states.append(a),
        on_output=_noop_output,
        on_presence=_noop_presence,
    )
    manager.update_settings(
        SidecarSettings.from_payload(
            {"defaultBaud": 115200, "boxes": [{"box": 1, "hardwareId": HWID}]}
        )
    )
    # Presence normally comes from the poll loop; inject it directly.
    manager._presence = {HWID: DetectedBoard(hardware_id=HWID, address=ADDRESS, fqbn=FQBN)}
    return manager, tool, states, progress


def teardown_function(_fn) -> None:
    pass


# --- flash ----------------------------------------------------------------


async def test_flash_from_idle_returns_to_idle() -> None:
    manager, tool, _, progress = make_manager()

    state, resumed = await manager.flash(1, "/sk/clean", "clean", "/sk/libraries",
                                         lambda *a: progress.append(a))

    assert state is PortState.IDLE
    assert resumed is False
    assert [c[0] for c in tool.calls] == ["compile", "upload"]
    # compile gets the shared libraries path; upload gets the resolved address
    assert tool.calls[0][3] == "/sk/libraries"
    assert tool.calls[1][3] == ADDRESS


async def test_flash_from_passthrough_auto_resumes_at_prior_baud(fake_serial) -> None:
    """§3.3 — the user sees the new sketch's output without an extra click."""
    manager, _tool, _, progress = make_manager()
    manager.open_passthrough(1, baud=9600)

    state, resumed = await manager.flash(1, "/sk/clean", "clean", None,
                                         lambda *a: progress.append(a))

    assert state is PortState.PASSTHROUGH
    assert resumed is True
    reopened = fake_serial.instances[-1]
    assert reopened.baudrate == 9600  # prior baud, not the default
    # The pre-flash port was cleanly released before arduino-cli took over.
    assert fake_serial.instances[0].closed is True
    manager.handler(1).shutdown()


async def test_suppress_passthrough_resume_forces_idle(fake_serial) -> None:
    """`dashboard.md` §7.4 — the session flash sequence needs IDLE.

    Without this the port would auto-resume PASSTHROUGH and the runner could
    never claim it, since IN_SESSION entry requires IDLE.
    """
    manager, _tool, _, progress = make_manager()
    manager.open_passthrough(1, baud=9600)

    state, resumed = await manager.flash(
        1, "/sk/clean", "clean", None, lambda *a: progress.append(a),
        suppress_passthrough_resume=True,
    )

    assert state is PortState.IDLE
    assert resumed is False
    # The pre-flash port was still cleanly released.
    assert fake_serial.instances[0].closed is True


async def test_compile_failure_lands_in_error_and_never_uploads() -> None:
    """§4 — ERROR with the parsed message, no silent fall back to IDLE."""
    manager, tool, _, _ = make_manager()
    tool.fail_compile = FlashFailed("compile", "clean.ino:3: error: expected ';'")

    with pytest.raises(FlashFailed):
        await manager.flash(1, "/sk/clean", "clean", None, lambda *a: None)

    assert manager.handler(1).state is PortState.ERROR
    assert [c[0] for c in tool.calls] == ["compile"]


async def test_upload_failure_lands_in_error() -> None:
    manager, tool, _, _ = make_manager()
    tool.fail_upload = FlashFailed("upload", "avrdude: stk500v2_getsync(): timeout")

    with pytest.raises(FlashFailed):
        await manager.flash(1, "/sk/clean", "clean", None, lambda *a: None)

    assert manager.handler(1).state is PortState.ERROR


async def test_flash_progress_is_tagged_with_its_phase() -> None:
    manager, _tool, _, progress = make_manager()
    await manager.flash(1, "/sk/clean", "clean", None, lambda *a: progress.append(a))

    phases = [p[0] for p in progress]
    assert phases[0] == "compile"
    assert "upload" in phases


async def test_the_manager_echoes_no_command_of_its_own() -> None:
    """The command echo belongs to the backend that runs the command.

    This layer knows neither which backend will serve the call nor what it will
    send, so a line composed here is a guess. It was one: the old echo omitted
    `--libraries`, and when a packaged build stopped finding its bundled
    library the console showed a compile with no libraries argument at all —
    pointing at a missing path rather than the malformed one being sent
    (v1.1.0-rc.2). `FakeTool` emits no `$` line, so nothing here may either.
    """
    manager, _tool, _, progress = make_manager()
    await manager.flash(1, "/sk/clean", "clean", "/libs", lambda *a: progress.append(a))

    assert not [line for _phase, _stream, line in progress if line.startswith("$ ")]


async def test_flash_on_unbound_box_is_rejected_before_touching_state() -> None:
    manager, _tool, _, _ = make_manager()
    with pytest.raises(PortNotBound):
        await manager.flash(4, "/sk/clean", "clean", None, lambda *a: None)
    assert manager.handler(4).state is PortState.IDLE


# --- reset ----------------------------------------------------------------


async def test_reset_from_idle_pulses_dtr_and_returns_to_idle(fake_serial) -> None:
    manager, _tool, _, _ = make_manager()

    state, resumed = await manager.reset(1)

    assert state is PortState.IDLE
    assert resumed is False
    pulse_port = fake_serial.instances[-1]
    assert pulse_port.port == ADDRESS
    # §5: dtr False → delay → dtr True (initial True assert precedes open()).
    assert pulse_port.dtr_history == [True, False, True]
    assert pulse_port.closed is True


async def test_reset_from_passthrough_auto_resumes(fake_serial) -> None:
    manager, _tool, _, _ = make_manager()
    manager.open_passthrough(1, baud=57600)

    state, resumed = await manager.reset(1)

    assert state is PortState.PASSTHROUGH
    assert resumed is True
    assert fake_serial.instances[-1].baudrate == 57600
    manager.handler(1).shutdown()


async def test_reset_failure_lands_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    manager, _tool, _, _ = make_manager()

    def explode(_address: str) -> None:
        raise OSError("port vanished")

    monkeypatch.setattr(manager_module, "_dtr_pulse", explode)

    with pytest.raises(OSError):
        await manager.reset(1)

    assert manager.handler(1).state is PortState.ERROR


# --- failure-message extraction ------------------------------------------


def test_failure_message_prefers_the_error_line() -> None:
    payload = {
        "compiler_err": "In file included from x\nclean.ino:3:5: error: expected ';'\nexit status 1",
        "success": False,
    }
    assert _failure_message("compile", payload, 1) == "clean.ino:3:5: error: expected ';'"


def test_failure_message_falls_back_to_last_line_then_generic() -> None:
    assert _failure_message("upload", {"stderr": "a\nfinal line"}, 1) == "final line"
    assert _failure_message("upload", {}, 2) == "upload failed (arduino-cli exited 2)"
