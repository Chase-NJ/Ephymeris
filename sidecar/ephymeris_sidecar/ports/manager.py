"""Owns the six port handlers, the binding map, and the background loops.

Two loops run here:

* **Presence poll** (`ARCHITECTURE.md#board-discovery`) — out-of-band, never opens a
  port, so it takes no part in the per-port state machine and can run
  regardless of what any port is doing.
* **Output flush** (`ARCHITECTURE.md#passthrough-read`) — batches accumulated lines and pushes them at a
  fixed 20Hz rather than one message per line, which six chatty boxes would
  otherwise turn into a flood.

Kept free of protocol/message concerns: callers supply callbacks and format the
wire messages themselves.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import serial

from ..boards.tool import BoardTool, DetectedBoard
from ..settings import BOX_COUNT, SidecarSettings
from .handler import DEFAULT_LINE_ENDING, OutputLine, PortHandler
from .states import PortState

log = logging.getLogger(__name__)

#: All six boxes are Mega2560 R3s (`ARCHITECTURE.md#flashing`).
FQBN = "arduino:avr:mega"

#: Progress callback for flash/reset: (phase, stream, text).
PhaseProgress = Callable[[str, str, str], None]

#: A short continuous interval of roughly 1–2s (`ARCHITECTURE.md#board-discovery`).
POLL_INTERVAL_S = 1.5
#: Batch and flush on a fixed tick (`ARCHITECTURE.md#passthrough-read`).
FLUSH_INTERVAL_S = 0.05
#: Don't re-log an unreachable arduino-cli on every single poll.
FAILURE_LOG_EVERY = 40

StateCallback = Callable[[int, PortState, PortState, str], None]
OutputCallback = Callable[[int, list[OutputLine]], Awaitable[None]]
PresenceCallback = Callable[[list[dict[str, object]]], Awaitable[None]]


class PortNotBound(Exception):
    """No board is bound to that box number."""


class BoardNotDetected(Exception):
    """A board is bound but isn't currently plugged in."""


class PortManager:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        tool: BoardTool,
        on_state_change: StateCallback,
        on_output: OutputCallback,
        on_presence: PresenceCallback,
    ) -> None:
        self._loop = loop
        self._tool = tool
        self._on_output = on_output
        self._on_presence = on_presence

        self._handlers: dict[int, PortHandler] = {
            box: PortHandler(box, loop, on_state_change) for box in range(1, BOX_COUNT + 1)
        }
        self._settings = SidecarSettings()
        self._presence: dict[str, DetectedBoard] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._poll_failures = 0

    # --- lifecycle --------------------------------------------------------

    def start(self) -> None:
        self._tasks = [
            self._loop.create_task(self._poll_loop(), name="presence-poll"),
            self._loop.create_task(self._flush_loop(), name="output-flush"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
        for handler in self._handlers.values():
            handler.shutdown()

    def update_settings(self, settings: SidecarSettings) -> None:
        self._settings = settings

    # --- lookups ----------------------------------------------------------

    def handler(self, box: int) -> PortHandler:
        handler = self._handlers.get(box)
        if handler is None:
            raise PortNotBound(f"box {box} does not exist")
        return handler

    def resolve_address(self, box: int) -> str:
        """box → hardware_id → current port address.

        The indirection is the point: box number is the stable key, the address
        is whatever the OS happens to be calling that board right now (`ARCHITECTURE.md#box-bindings`).
        """
        hardware_id = self._settings.hardware_id_for(box)
        if not hardware_id:
            raise PortNotBound(f"No board is bound to box {box}. Assign one in Config.")
        board = self._presence.get(hardware_id)
        if board is None:
            raise BoardNotDetected(
                f"The board bound to box {box} ({hardware_id}) isn't currently detected."
            )
        return board.address

    def current_states(self) -> dict[int, PortState]:
        return {box: handler.state for box, handler in sorted(self._handlers.items())}

    def presence_json(self) -> list[dict[str, object]]:
        bound: dict[str, int] = {
            binding.hardware_id: binding.box
            for binding in self._settings.boxes
            if binding.hardware_id
        }
        return [
            board.to_json(box_id=bound.get(hardware_id))
            for hardware_id, board in sorted(self._presence.items())
        ]

    # --- operations -------------------------------------------------------

    def open_passthrough(self, box: int, baud: int | None = None) -> PortState:
        address = self.resolve_address(box)
        rate = baud or self._settings.default_baud
        return self.handler(box).open_passthrough(address, rate)

    def close_passthrough(self, box: int) -> PortState:
        return self.handler(box).close_passthrough()

    def send(self, box: int, text: str, line_ending: str = DEFAULT_LINE_ENDING) -> int:
        return self.handler(box).write(text, line_ending)

    def acknowledge_error(self, box: int) -> PortState:
        return self.handler(box).acknowledge_error()

    async def flash(
        self,
        box: int,
        sketch_dir: str,
        sketch_name: str,
        libraries_path: str | None,
        on_progress: PhaseProgress,
        suppress_passthrough_resume: bool = False,
    ) -> tuple[PortState, bool]:
        """Compile + upload (`ARCHITECTURE.md#flashing`).

        Entering FLASHING force-releases PASSTHROUGH first, and on success the
        prior passthrough is auto-resumed at its old baud so the user sees the
        new sketch's output without an extra click (`ARCHITECTURE.md#exclusivity`). Failures land in
        ERROR with the parsed message — never a silent fall back to IDLE.

        `suppress_passthrough_resume` forces the port to IDLE afterward instead,
        so the session flash sequence can claim it for `IN_SESSION`
        (`ARCHITECTURE.md#flash-sequence`).
        """
        address = self.resolve_address(box)
        handler = self.handler(box)
        prior_baud = handler.baud or self._settings.default_baud
        was_passthrough = handler.release_for(
            PortState.FLASHING, f"flashing {sketch_name}"
        )
        # The session flow wants IDLE regardless of the pre-flash state.
        resume = was_passthrough and not suppress_passthrough_resume

        try:
            # No command echo here. This layer knows neither which backend will
            # run (daemon or subprocess) nor the arguments it will send, so
            # anything written here is a guess that drifts — and did: the old
            # hand-written line omitted `--libraries`, which is exactly the
            # argument that was malformed when a packaged build stopped finding
            # its bundled library. Each backend echoes its own real invocation
            # (`boards/cli_tool.py`, `boards/grpc_tool.py`).
            await self._tool.compile(
                sketch_dir, FQBN, libraries_path,
                lambda stream, text: on_progress("compile", stream, text),
            )
            await self._tool.upload(
                sketch_dir, FQBN, address,
                lambda stream, text: on_progress("upload", stream, text),
            )
        except Exception as exc:
            handler.force_error(f"flash failed: {exc}")
            raise

        return self._conclude(handler, address, prior_baud, resume,
                              f"flashed {sketch_name}")

    async def reset(self, box: int) -> tuple[PortState, bool]:
        """DTR-toggle reset (`ARCHITECTURE.md#reset`).

        A serial-layer operation, deliberately not routed through arduino-cli.
        Auto-resumes passthrough afterward if that was the prior state (`ARCHITECTURE.md#exclusivity`).
        """
        address = self.resolve_address(box)
        handler = self.handler(box)
        prior_baud = handler.baud or self._settings.default_baud
        was_passthrough = handler.release_for(PortState.RESETTING, "reset (DTR toggle)")

        try:
            # Blocking serial work stays off the event loop.
            await asyncio.to_thread(_dtr_pulse, address)
        except Exception as exc:
            handler.force_error(f"reset failed: {exc}")
            raise

        return self._conclude(handler, address, prior_baud, was_passthrough, "reset complete")

    def start_session(
        self,
        box: int,
        start_command: str,
        on_ready: "Callable[[int | None], None]",
        on_strobe: "Callable[[int, int], None]",
    ) -> PortState:
        """Enter `IN_SESSION` on one box (`ARCHITECTURE.md#entering-in_session`).

        The box must be `IDLE` (the flash sequence leaves it there via
        `suppressPassthroughResume`). Baud is the session default.
        """
        address = self.resolve_address(box)
        handler = self.handler(box)
        return handler.start_session(
            address, self._settings.default_baud, start_command, on_ready, on_strobe
        )

    def stop_session(self, box: int) -> None:
        """Send `STOP` to a running box; the board's end strobe ends the run."""
        self.handler(box).send_session_line("STOP")

    def end_session(self, box: int, reason: str) -> PortState:
        """Conclude a run cleanly: `IN_SESSION → IDLE`."""
        return self.handler(box).end_session(reason)

    def _conclude(
        self,
        handler: PortHandler,
        address: str,
        baud: int,
        was_passthrough: bool,
        reason: str,
    ) -> tuple[PortState, bool]:
        """Land the port after a flash/reset: auto-resume or return to IDLE."""
        if was_passthrough:
            try:
                handler.open_passthrough(address, baud)
                return handler.state, True
            except Exception as exc:  # noqa: BLE001 - handler is already in ERROR
                log.warning(
                    "box %d: auto-resume failed after %s: %s", handler.box, reason, exc
                )
                return handler.state, False
        handler.finish_to_idle(reason)
        return handler.state, False

    # --- background loops -------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            try:
                boards = await self._tool.list_boards()
            except Exception as exc:  # noqa: BLE001 - missing binary, timeout, …
                self._note_poll_failure(exc)
            else:
                self._poll_failures = 0
                if self._update_presence(boards):
                    await self._on_presence(self.presence_json())
            await asyncio.sleep(POLL_INTERVAL_S)

    def _note_poll_failure(self, exc: Exception) -> None:
        if self._poll_failures % FAILURE_LOG_EVERY == 0:
            log.warning("board presence poll failed: %s", exc)
        self._poll_failures += 1

    def _update_presence(self, boards: list[DetectedBoard]) -> bool:
        latest = {board.hardware_id: board for board in boards}
        if latest == self._presence:
            return False

        appeared = set(latest) - set(self._presence)
        vanished = set(self._presence) - set(latest)
        for hardware_id in appeared:
            log.info("board appeared: %s at %s", hardware_id, latest[hardware_id].address)
        for hardware_id in vanished:
            log.info("board vanished: %s", hardware_id)

        self._presence = latest
        return True

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            for box, handler in self._handlers.items():
                handler.flush_stale_partial()
                batch = handler.drain()
                if batch:
                    await self._on_output(box, batch)


def _dtr_pulse(address: str) -> None:
    """The reset sequence (`ARCHITECTURE.md#reset`): dtr low → ~100ms → dtr high.

    The Mega2560 R3's auto-reset circuit fires on the DTR edge. Runs in a
    worker thread; the port is opened fresh and closed again, the state
    machine having already released any prior owner.
    """
    port = serial.Serial()
    port.port = address
    port.dtr = True
    port.open()
    try:
        port.dtr = False
        time.sleep(0.1)
        port.dtr = True
        time.sleep(0.05)
    finally:
        port.close()
