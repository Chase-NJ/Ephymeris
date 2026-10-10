"""Flash and reset orchestration — `ARCHITECTURE.md#flashing`, `ARCHITECTURE.md#reset`, `ARCHITECTURE.md#exclusivity`."""

from __future__ import annotations

import asyncio

import pytest

from ephymeris_sidecar.boards.cli_tool import _failure_message
from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard, FlashFailed
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports import manager as manager_module
from ephymeris_sidecar.ports.manager import (
    FQBN,
    CarriedSketch,
    PortManager,
    PortNotBound,
    sketch_fingerprint,
)
from ephymeris_sidecar.ports.states import IllegalTransition, PortState
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
    """`ARCHITECTURE.md#exclusivity` — the user sees the new sketch's output without an extra click."""
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
    """`ARCHITECTURE.md#flash-sequence` — the session flash sequence needs IDLE.

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
    """`ARCHITECTURE.md#flashing` — ERROR with the parsed message, no silent fall back to IDLE."""
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


# --- what a board carries (ARCHITECTURE.md#what-a-board-carries) -----------


def _sketch(root, name: str = "GRGL"):  # noqa: ANN001, ANN202
    folder = root / name
    folder.mkdir()
    (folder / f"{name}.ino").write_text("void setup() {}\n")
    (folder / "TaskPins.h").write_text("#define VALVE 4\n")
    return folder


async def test_a_flash_records_the_folder_it_compiled(tmp_path) -> None:  # noqa: ANN001
    manager, _tool, _, _ = make_manager()
    folder = _sketch(tmp_path)
    assert manager.carried(1) is None

    await manager.flash(1, str(folder), "GRGL", None, lambda *a: None)

    assert manager.carried(1) == CarriedSketch(str(folder), sketch_fingerprint(str(folder)))


@pytest.mark.parametrize("phase", ["compile", "upload"])
async def test_a_failed_flash_leaves_nothing_known(tmp_path, phase: str) -> None:  # noqa: ANN001
    """An upload that died halfway leaves a board nobody can name, and one
    whose compile failed is not worth trusting either."""
    manager, tool, _, _ = make_manager()
    first, second = _sketch(tmp_path), _sketch(tmp_path, "BOX_Utility")
    await manager.flash(1, str(first), "GRGL", None, lambda *a: None)
    setattr(tool, f"fail_{phase}", FlashFailed(phase, f"{phase} failed"))

    with pytest.raises(FlashFailed):
        await manager.flash(1, str(second), "BOX_Utility", None, lambda *a: None)

    assert manager.carried(1) is None


async def test_a_flash_refused_by_a_busy_port_keeps_the_record(tmp_path) -> None:  # noqa: ANN001
    manager, _tool, _, _ = make_manager()
    folder = _sketch(tmp_path)
    await manager.flash(1, str(folder), "GRGL", None, lambda *a: None)
    manager.handler(1).release_for(PortState.RESETTING, "a reset in progress")

    with pytest.raises(IllegalTransition):
        await manager.flash(1, str(_sketch(tmp_path, "Other")), "Other", None, lambda *a: None)

    # The board was never touched.
    assert manager.carried(1) is not None and manager.carried(1).is_of(str(folder))


async def test_a_vanished_board_takes_the_record_with_it(tmp_path) -> None:  # noqa: ANN001
    manager, _tool, _, _ = make_manager()
    await manager.flash(1, str(_sketch(tmp_path)), "GRGL", None, lambda *a: None)

    manager._update_presence([])
    assert manager.carried(1) is None


async def test_rebinding_a_box_forgets_it_and_only_it(tmp_path) -> None:  # noqa: ANN001
    manager, _tool, _, _ = make_manager()
    other = DetectedBoard(hardware_id="TESTBOARD02", address="/dev/cu.other", fqbn=FQBN)
    manager._presence[other.hardware_id] = other
    manager.update_settings(
        SidecarSettings.from_payload({
            "defaultBaud": 115200,
            "boxes": [{"box": 1, "hardwareId": HWID}, {"box": 2, "hardwareId": "TESTBOARD02"}],
        })
    )
    await manager.flash(1, str(_sketch(tmp_path)), "GRGL", None, lambda *a: None)
    await manager.flash(2, str(_sketch(tmp_path, "Other")), "Other", None, lambda *a: None)

    # Box 2 now answers with box 1's old board; box 1 is unchanged.
    manager.update_settings(
        SidecarSettings.from_payload({
            "defaultBaud": 9600,
            "boxes": [{"box": 1, "hardwareId": HWID}, {"box": 2, "hardwareId": "TESTBOARD03"}],
        })
    )
    assert manager.carried(1) is not None
    assert manager.carried(2) is None


def test_the_fingerprint_follows_content_not_noise(tmp_path) -> None:  # noqa: ANN001
    folder = _sketch(tmp_path)
    before = sketch_fingerprint(str(folder))

    (folder / ".DS_Store").write_bytes(b"\0finder")
    assert sketch_fingerprint(str(folder)) == before

    (folder / "TaskPins.h").write_text("#define VALVE 5\n")
    assert sketch_fingerprint(str(folder)) != before

    # So does a file going away; a folder that is not there hashes as empty.
    (folder / "TaskPins.h").unlink()
    assert sketch_fingerprint(str(folder)) != before
    assert sketch_fingerprint(str(tmp_path / "missing")) == sketch_fingerprint(str(tmp_path / "gone"))


# --- reset ----------------------------------------------------------------


async def test_reset_from_idle_pulses_dtr_and_returns_to_idle(fake_serial) -> None:
    manager, _tool, _, _ = make_manager()

    state, resumed = await manager.reset(1)

    assert state is PortState.IDLE
    assert resumed is False
    pulse_port = fake_serial.instances[-1]
    assert pulse_port.port == ADDRESS
    # `ARCHITECTURE.md#reset`: dtr False → delay → dtr True (initial True assert precedes open()).
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
