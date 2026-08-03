"""Getting lines to and from a board — or something pretending to be one.

The whole conversation is line-oriented, so this is the entire I/O surface. It is
separated from `client.py` for one reason: it makes the uploader testable against
`extras/host_test/tg_board`, which runs the SAME receiver an ATmega2560 runs. A
client that opened its own serial port could only ever be tested by plugging a
board in, and the failure modes worth testing — a board that refuses, a board that
goes silent mid-transfer, a board announcing limits the table exceeds — are
tedious to produce on hardware and trivial to produce here.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


class Link:
    """Line-oriented, both directions, with a timeout on reads."""

    def write_line(self, text: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def read_line(self, timeout: float) -> str | None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass

    def __enter__(self) -> Link:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class SerialLink(Link):
    """A real board, over USB.

    pyserial is imported here rather than at module scope so that framing, CAP
    parsing and every test below work in an environment that has never installed
    it. Only talking to hardware needs it.
    """

    def __init__(self, port: str, baud: int, *, reset: bool = True, settle: float = 2.2) -> None:
        try:
            import serial  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError(
                "talking to a board needs pyserial: pip install pyserial"
            ) from exc

        self._port = serial.Serial(port, baud, timeout=0.2)
        if reset:
            #: Opening the port already pulses DTR on most adapters, which resets
            #: the board and starts the bootloader. Wait it out, then reset
            #: DELIBERATELY, so the banner is this run's and not a leftover from
            #: whatever was in the buffer.
            time.sleep(settle)
            self._port.reset_input_buffer()
            self._port.setDTR(False)
            time.sleep(0.1)
            self._port.setDTR(True)

    def write_line(self, text: str) -> None:
        self._port.write((text + "\n").encode())
        self._port.flush()

    def read_line(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = self._port.readline()
            if raw:
                return raw.decode("utf-8", "replace").rstrip("\r\n")
        return None

    def close(self) -> None:
        self._port.close()


class ProcessLink(Link):
    """A subprocess speaking the protocol on stdin/stdout.

    `tg_board` is the far end. It is not a mock of the receiver — it *is* the
    receiver, compiled by a different compiler, with only the clock and Serial
    replaced.
    """

    def __init__(self, argv: list[str] | list[Path]) -> None:
        self._p = subprocess.Popen(
            [str(a) for a in argv],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1,
        )

    def write_line(self, text: str) -> None:
        assert self._p.stdin is not None
        self._p.stdin.write(text + "\n")
        self._p.stdin.flush()

    def read_line(self, timeout: float) -> str | None:
        #: No timeout handling: a subprocess pipe either has a line or the far end
        #: has exited, and a real deadlock here would hang the test rather than
        #: report a timeout. That is the right trade for a test double -- a
        #: SerialLink timeout models a board that went quiet, which is a real
        #: condition; a subprocess that goes quiet is a bug in the harness.
        assert self._p.stdout is not None
        line = self._p.stdout.readline()
        return line.rstrip("\r\n") if line else None

    def close(self) -> None:
        if self._p.stdin:
            self._p.stdin.close()
        self._p.wait(timeout=10)
