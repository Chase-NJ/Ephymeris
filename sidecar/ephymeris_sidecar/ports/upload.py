"""`PortLink` — the compiler transport's `Link`, over one box's serial port.

Opens its OWN `serial.Serial` rather than borrowing the handler's. The
handler's reader thread owns its port's bytes and pushes them into a ring
buffer the 20 Hz flusher DRAINS; there is no way to *take* a line out of that,
and the upload conversation is request/response with deadlines. So the port is
claimed through the state machine (`UPLOADING`), the handler's serial is torn
down, and this link holds the only handle for the duration.

PROGRESS IS EXTRACTED HERE, NOT HOOKED INTO THE VENDORED CLIENT.
`taskgraph.transport.client.upload` has no progress callback, and adding one
would put a two-repo lockstep under a UI nicety. Instead `write_line`
recognises `TABLE CHUNK n …` going out and `read_line` recognises `TABLE ACK
n` coming back — and progress is reported on the ACK, because an acknowledged
chunk is progress the BOARD confirmed rather than bytes this side hopes
arrived. The vendored client is used unmodified, which is the point of the
vendoring.

The `mirror` callback echoes the conversation's headline lines into the box's
console ring buffer — banner, `TABLE BEGIN/END/OK/FAIL` — deliberately NOT the
hex chunks, which would blow the 2000-line cap in one upload and bury anything
worth reading.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

import serial

#: The conversation's own framing, matched loosely on purpose: these drive
#: progress and mirroring only, never correctness — the vendored client is the
#: authority on what a reply means.
_CHUNK_RE = re.compile(r"^TABLE CHUNK (\d+) ")
_ACK_RE = re.compile(r"^TABLE ACK (\d+)$")
_MIRROR_RE = re.compile(r"^(TABLE (BEGIN|END|OK|FAIL)|READY$|CAP )")

#: Serial read granularity. Small enough that read_line's deadline is honest,
#: large enough not to syscall per byte.
_READ_TIMEOUT_S = 0.2

ProgressFn = Callable[[str, int | None, int | None, str | None], None]
MirrorFn = Callable[[str, str], None]


class PortLink:
    """The three-method `Link` interface, plus the reset that starts a run.

    Opening with `reset=True` toggles DTR by the act of opening — the Mega's
    auto-reset — which is what makes the banner readable: the board boots and
    announces itself to a listener that is already there.
    """

    def __init__(
        self,
        address: str,
        baud: int,
        *,
        reset: bool = True,
        settle: float = 2.2,
        on_progress: ProgressFn | None = None,
        mirror: MirrorFn | None = None,
    ) -> None:
        self._on_progress = on_progress
        self._mirror = mirror
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._serial = serial.Serial(
            port=address,
            baudrate=baud,
            timeout=_READ_TIMEOUT_S,
            write_timeout=5.0,
        )
        if reset:
            # Mirrors upstream SerialLink exactly, and the ORDER is the point:
            # opening pulled DTR and rebooted the board, so its banner lands
            # during the settle — flush that, then pulse DTR DELIBERATELY so
            # the banner read next is this run's. The first cut flushed
            # without re-resetting, which silently discarded a boot-time READY
            # and made every legacy sketch look mute at its own baud.
            time.sleep(settle)
            self._serial.reset_input_buffer()
            self._serial.setDTR(False)
            time.sleep(0.1)
            self._serial.setDTR(True)

    # --- Link -------------------------------------------------------------

    def write_line(self, text: str) -> None:
        match = _CHUNK_RE.match(text)
        if match and self._on_progress:
            # The chunk is LEAVING; the matching ACK is what confirms it. This
            # call only moves the "transfer" phase's denominator display.
            self._on_progress("transfer", int(match.group(1)), None, None)
        if self._mirror and _MIRROR_RE.match(text):
            self._mirror("tx", text)
        self._serial.write((text + "\n").encode("ascii", errors="replace"))

    def read_line(self, timeout: float) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                line = self._take_line()
            if line is not None:
                match = _ACK_RE.match(line)
                if match and self._on_progress:
                    self._on_progress("transfer", int(match.group(1)), None, None)
                if self._mirror and _MIRROR_RE.match(line):
                    self._mirror("rx", line)
                return line
            if time.monotonic() >= deadline:
                return None
            chunk = self._serial.read(256)
            if chunk:
                with self._lock:
                    self._buf.extend(chunk)

    def close(self) -> None:
        try:
            self._serial.close()
        except (serial.SerialException, OSError):
            pass

    def __enter__(self) -> PortLink:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- framing ----------------------------------------------------------

    def _take_line(self) -> str | None:
        """One complete line out of the buffer, tolerating CR/LF/CRLF.

        The same tolerance the handler's `_extract_lines` applies, restated
        here because this buffer is CONSUMED by the conversation rather than
        drained by a flusher — the two owners must never share bytes.
        """
        for i, byte in enumerate(self._buf):
            if byte in (0x0A, 0x0D):
                raw = bytes(self._buf[:i])
                # Swallow a paired \r\n.
                skip = i + 1
                if byte == 0x0D and skip < len(self._buf) and self._buf[skip] == 0x0A:
                    skip += 1
                del self._buf[:skip]
                if not raw:
                    return self._take_line()
                return raw.decode("utf-8", errors="replace")
        return None
