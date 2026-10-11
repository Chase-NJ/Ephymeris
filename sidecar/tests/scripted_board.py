"""A real `PortManager` with scripted boards behind it.

The manager, its handlers, their state machine and the session thread are the
real ones. Only the two edges are faked: `serial.Serial`, through the
manager's `open_serial`, and the board list, through `note_boards`. A test
plays the board by feeding the lines it would print (`READY`, `SEED`,
strobes) and reading what the sidecar wrote back.
"""

from __future__ import annotations

import asyncio
import threading
import time

from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard
from ephymeris_sidecar.ports import handler as handler_module
from ephymeris_sidecar.ports.manager import PortManager
from ephymeris_sidecar.ports.states import PortState
from ephymeris_sidecar.settings import SidecarSettings


class ScriptedBoard:
    """One opened serial port: what the board says, and what it was sent."""

    def __init__(self, *_args, **kwargs) -> None:
        self.port = kwargs.get("port")
        self.baudrate = kwargs.get("baudrate")
        self.dtr = True
        self.closed = False
        self.written = bytearray()
        self._out = bytearray()
        self._lock = threading.Lock()
        self._fail = False

    def say(self, text: str) -> None:
        """Queue lines the board prints."""
        with self._lock:
            self._out.extend(text.encode())

    def unplug(self) -> None:
        """The next read fails, as a board pulled mid-session does."""
        self._fail = True

    @property
    def in_waiting(self) -> int:
        with self._lock:
            return len(self._out)

    def read(self, size: int = 1) -> bytes:
        if self._fail:
            raise OSError("device disconnected")
        with self._lock:
            if self._out:
                chunk = bytes(self._out[:size])
                del self._out[:size]
                return chunk
        time.sleep(handler_module.READ_TIMEOUT_S)
        return b""

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        pass

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _NoTool(BoardTool):
    """Presence comes from `note_boards`; nothing here is ever asked."""

    async def list_boards(self) -> list[DetectedBoard]:
        raise AssertionError("the presence poll is not running in these tests")

    async def compile(self, *_args) -> None:  # noqa: ANN002
        raise AssertionError("nothing is compiled in these tests")

    async def upload(self, *_args) -> None:  # noqa: ANN002
        raise AssertionError("nothing is uploaded in these tests")


class Bench:
    """The rig's ports: a real `PortManager` and the boards it has opened."""

    def __init__(self, loop: asyncio.AbstractEventLoop, boxes: tuple[int, ...]) -> None:
        #: Every port opened, by address, latest last.
        self.opened: dict[str, list[ScriptedBoard]] = {}
        #: Every announced change, as `(box, from, to, reason)`.
        self.changes: list[tuple[int, PortState, PortState, str]] = []

        async def nothing(*_args) -> None:  # noqa: ANN002
            return None

        self.ports = PortManager(
            loop=loop,
            tool=_NoTool(),
            on_state_change=lambda *change: self.changes.append(change),
            on_output=nothing,
            on_presence=nothing,
            open_serial=self._open,
        )
        self.ports.update_settings(
            SidecarSettings.from_payload(
                {"boxes": [{"box": box, "hardwareId": f"HW{box}"} for box in boxes]}
            )
        )
        self._boxes = boxes

    async def plug_in(self) -> "Bench":
        await self.ports.note_boards(
            [DetectedBoard(hardware_id=f"HW{box}", address=f"/dev/box{box}") for box in self._boxes]
        )
        return self

    def _open(self, *args, **kwargs) -> ScriptedBoard:  # noqa: ANN002, ANN003
        board = ScriptedBoard(*args, **kwargs)
        self.opened.setdefault(str(kwargs.get("port")), []).append(board)
        return board

    def board(self, box: int) -> ScriptedBoard:
        """The port most recently opened for `box`."""
        return self.opened[f"/dev/box{box}"][-1]

    def state(self, box: int) -> PortState:
        return self.ports.current_states()[box]

    async def wait_for_board(self, box: int, timeout: float = 5.0) -> ScriptedBoard:
        """The board once the session thread has opened its port."""
        await until(lambda: bool(self.opened.get(f"/dev/box{box}")), timeout=timeout)
        return self.board(box)

    async def run_handshake(self, box: int, seed: int | None = None) -> ScriptedBoard:
        """Play a board through READY, and SEED when given, up to the first strobe."""
        board = await self.wait_for_board(box)
        board.say("READY\n")
        await until(lambda: b"START" in bytes(board.written))
        if seed is not None:
            board.say(f"SEED\t{seed}\n")
        return board

    def shutdown(self) -> None:
        for box in self._boxes:
            self.ports.handler(box).shutdown()


async def until(predicate, *, timeout: float = 5.0) -> None:  # noqa: ANN001
    """Yield to the loop until `predicate()` holds. The ceiling only trips on a hang."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.005)
