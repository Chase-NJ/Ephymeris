"""Board tooling interface.

Two backends sit behind this interface — the `arduino-cli` gRPC daemon and the
subprocess fallback (`ARCHITECTURE.md#flashing`) — and the callers never know
which one is running.

Everything above this line works in terms of `DetectedBoard`, never in terms of
`arduino-cli` output.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

#: Progress callback: (stream, text) — `stream` is "stdout" or "stderr".
ProgressLine = Callable[[str, str], None]

#: How many timeouts avrdude may report during one upload before it is called
#: stalled. A working upload recovers from a few (three, through a good hub). A
#: board whose page writes never land reports four per page, a round every
#: ~5.5 s, until the upload timeout. Twelve is three such rounds: about 16 s
#: rather than two minutes of a box shown flashing (`ARCHITECTURE.md#flashing`).
STALL_TIMEOUTS = 12

STALLED_MESSAGE = (
    "the board stopped answering mid-upload (avrdude kept timing out) — check the "
    "USB cable, any hub between it and the computer, and the box's power, then flash again"
)


class FlashFailed(Exception):
    """A compile or upload step failed.

    Carries which phase failed and the tool output that explains why, so the
    frontend gets a parsed message rather than a bare exit code
    (`ARCHITECTURE.md#flashing`).
    """

    def __init__(self, phase: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.phase = phase
        self.message = message
        self.detail = detail


class StallWatch:
    """Wraps an upload's `on_line` and counts the timeouts avrdude reports.

    Every line still reaches `on_line`. `stalled` turns true once there have
    been too many to be a hiccup (`STALL_TIMEOUTS`); the backend then ends the
    upload and raises `failure()`. Only a backend that sees avrdude's lines as
    they happen can use it.
    """

    def __init__(self, on_line: ProgressLine) -> None:
        self._on_line = on_line
        self._timeouts = 0

    def __call__(self, stream: str, text: str) -> None:
        self._on_line(stream, text)
        if stream == "stderr" and "timeout" in text.lower():
            self._timeouts += 1

    @property
    def stalled(self) -> bool:
        return self._timeouts >= STALL_TIMEOUTS

    @staticmethod
    def failure() -> FlashFailed:
        return FlashFailed("upload", STALLED_MESSAGE)


def failure_line(phase: str, lines: list[str]) -> str | None:
    """The tool output line that explains a failed phase, or None.

    A compile's first `error:` line is the cause; the rest follow from it. An
    upload's last one is the verdict: avrdude reports every retried timeout
    as an error before the one it gave up on. With no `error:` line, the last
    thing said.
    """
    lines = [line.strip() for line in lines if line.strip()]
    errors = [line for line in lines if "error:" in line.lower()]
    if errors:
        return errors[0] if phase == "compile" else errors[-1]
    return lines[-1] if lines else None


@dataclass(frozen=True)
class DetectedBoard:
    """A board the OS can currently see.

    `hardware_id` (the USB serial number) is the stable identity boxes bind to;
    `address` is explicitly the part that is *not* stable, since Windows
    renumbers COM ports across reboots and re-enumeration.
    """

    hardware_id: str
    address: str
    fqbn: str | None = None
    label: str | None = None

    def to_json(self, box_id: int | None = None) -> dict[str, object]:
        return {
            "hardwareId": self.hardware_id,
            "address": self.address,
            "fqbn": self.fqbn,
            "boxId": box_id,
        }


class BoardTool(ABC):
    """Board discovery and (from Phase 7) flashing."""

    @abstractmethod
    async def list_boards(self) -> list[DetectedBoard]:
        """Enumerate connected boards without opening any port.

        Must never open a serial port: presence polling is out-of-band
        (`ARCHITECTURE.md#board-discovery`)
        precisely so it never contends with the per-port state machine for
        ownership.
        """

    @abstractmethod
    async def compile(
        self,
        sketch_dir: str,
        fqbn: str,
        libraries_path: str | None,
        on_line: ProgressLine,
    ) -> None:
        """Compile a sketch, streaming progress to `on_line`.

        Does not touch any serial port. Raises `FlashFailed` on error with the
        compiler's actual message, never a bare exit status.
        """

    @abstractmethod
    async def upload(
        self,
        sketch_dir: str,
        fqbn: str,
        address: str,
        on_line: ProgressLine,
    ) -> None:
        """Upload a compiled sketch to `address`, streaming progress.

        The caller owns the state machine and must have released the port
        (`ARCHITECTURE.md#exclusivity`) before calling. Raises `FlashFailed`
        on error.
        """

    def set_binary(self, binary: str | None) -> None:
        """Use the `arduino-cli` at `binary`, or the bundled one for `None`:
        the Settings override, applied on every `settings.push`.

        A no-op by default, for a backend that runs no binary.
        """

    async def close(self) -> None:
        """Release whatever the backend holds (a daemon child, a channel).

        A no-op by default — the subprocess backend holds nothing between
        calls. Called once from `Application.stop()`.
        """
