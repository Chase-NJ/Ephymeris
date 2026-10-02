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

    async def close(self) -> None:
        """Release whatever the backend holds (a daemon child, a channel).

        A no-op by default — the subprocess backend holds nothing between
        calls. Called once from `Application.stop()`.
        """
