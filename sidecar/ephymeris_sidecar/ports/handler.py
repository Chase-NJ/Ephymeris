"""Per-port handler: state machine, reader thread, ring buffer, write path.

One instance per box. Deliberately a *single* object owning both the read loop
and `write()` — `dashboard.md` §6.4 requires that reads and writes
are never split across separate objects for the same port, so state transitions
can't race a queued write.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Literal

import serial

from .states import IllegalTransition, PortState, assert_transition

log = logging.getLogger(__name__)

#: `IN_SESSION` line recognition (`dashboard.md` §10 step 6). Stricter
#: than PASSTHROUGH's opaque text: a data line is exactly `<code>\t<timestamp>`,
#: code 1–3 digits. Anything else is logged but not treated as data.
STROBE_RE = re.compile(r"^(\d{1,3})\t(\d+)$")
SEED_RE = re.compile(r"^SEED\t(\d+)$")
READY_TOKEN = "READY"

#: How long to wait for the board's `READY` after opening (it reboots via the
#: DTR auto-reset first, so this must cover `setup()`).
SESSION_READY_TIMEOUT_S = 10.0
#: Brief window after `START` to catch an optional `SEED` line (§7 step 5).
SESSION_SEED_WINDOW_S = 1.5

#: Passthrough scrollback is debug output, not data to retain (§6.2).
RING_CAPACITY = 2000

#: Flush a partial line anyway past this many bytes, so a sketch that never
#: emits a newline can't grow the buffer without bound.
MAX_PARTIAL_BYTES = 4096

#: Blocking read timeout; also how often the reader notices a stop request.
READ_TIMEOUT_S = 0.05
WRITE_TIMEOUT_S = 1.0

Direction = Literal["rx", "tx"]

LINE_ENDINGS: dict[str, str] = {
    "none": "",
    "lf": "\n",
    "cr": "\r",
    "crlf": "\r\n",
}
DEFAULT_LINE_ENDING = "lf"


@dataclass(frozen=True)
class OutputLine:
    dir: Direction
    text: str
    ts: float

    def to_json(self) -> dict[str, object]:
        return {"dir": self.dir, "text": self.text, "ts": self.ts}


class PortBusy(Exception):
    """The port isn't in a state that permits this operation."""


class PortHandler:
    def __init__(
        self,
        box: int,
        loop: asyncio.AbstractEventLoop,
        on_state_change: Callable[[int, PortState, PortState, str], None],
    ) -> None:
        self.box = box
        self._loop = loop
        self._on_state_change = on_state_change

        self._state = PortState.IDLE
        self._lock = threading.RLock()

        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._buf = bytearray()
        self._baud: int | None = None

        self._ring: deque[OutputLine] = deque(maxlen=RING_CAPACITY)
        self._pending: list[OutputLine] = []
        self._pending_lock = threading.Lock()

        # Used to tell "a trailing CR that may still become CRLF" apart from
        # "a trailing CR that is all we're ever going to get" — see
        # `flush_stale_partial`.
        self._ingest_seq = 0
        self._seen_seq = -1

    # --- state ------------------------------------------------------------

    @property
    def state(self) -> PortState:
        with self._lock:
            return self._state

    @property
    def baud(self) -> int | None:
        return self._baud

    def _set_state(self, to: PortState, reason: str) -> None:
        """Move state, enforcing the §3.2 table. Caller must hold the lock."""
        previous = self._state
        if previous == to:
            return
        assert_transition(previous, to)
        self._state = to
        log.info("box %d: %s -> %s (%s)", self.box, previous.value, to.value, reason)
        # Always hand the notification to the loop thread: this is reachable
        # from the reader thread when a board disappears mid-stream.
        self._loop.call_soon_threadsafe(
            self._on_state_change, self.box, previous, to, reason
        )

    def force_error(self, reason: str) -> None:
        with self._lock:
            if self._state == PortState.ERROR:
                return
            self._teardown_serial()
            self._set_state(PortState.ERROR, reason)

    def acknowledge_error(self) -> PortState:
        """ERROR → IDLE on user acknowledgement (§3.2)."""
        with self._lock:
            self._set_state(PortState.IDLE, "error acknowledged")
            return self._state

    # --- passthrough ------------------------------------------------------

    def open_passthrough(self, address: str, baud: int) -> PortState:
        with self._lock:
            assert_transition(self._state, PortState.PASSTHROUGH)
            try:
                port = serial.Serial(
                    port=address,
                    baudrate=baud,
                    timeout=READ_TIMEOUT_S,
                    write_timeout=WRITE_TIMEOUT_S,
                )
            except (serial.SerialException, OSError) as exc:
                self._set_state(PortState.ERROR, f"couldn't open {address}: {exc}")
                raise

            self._serial = port
            self._baud = baud
            self._buf.clear()
            self._stop = threading.Event()
            self._reader = threading.Thread(
                target=self._read_loop,
                args=(port, self._stop),
                name=f"box{self.box}-reader",
                daemon=True,
            )
            self._reader.start()
            self._set_state(PortState.PASSTHROUGH, f"opened {address} @ {baud}")
            return self._state

    def close_passthrough(self, reason: str = "closed by user") -> PortState:
        with self._lock:
            assert_transition(self._state, PortState.IDLE)
            self._teardown_serial()
            self._set_state(PortState.IDLE, reason)
            return self._state

    def finish_to_idle(self, reason: str) -> PortState:
        """Conclude a FLASHING/RESETTING operation that isn't auto-resuming."""
        with self._lock:
            self._set_state(PortState.IDLE, reason)
            return self._state

    def echo(self, direction: str, text: str) -> None:
        """Put one line into the console ring buffer from outside the handler.

        The table uploader's mirror: during `UPLOADING` the handler has no
        serial and no reader thread, so this is the only writer — no race with
        the read loop is possible. Filtered upstream to headline lines only;
        the ring's 2000-line cap is for debug output, not hex dumps.
        """
        self._emit(OutputLine("rx" if direction == "rx" else "tx", text, time.time()))

    def release_for(self, next_state: PortState, reason: str) -> bool:
        """Hand the port to a flash or reset, returning whether to auto-resume.

        §3.3: entering `FLASHING`/`RESETTING` forces a clean release of
        `PASSTHROUGH` first, and if passthrough *was* the prior state the caller
        should resume it afterward so the user sees the new sketch's output
        without an extra click.
        """
        with self._lock:
            was_passthrough = self._state == PortState.PASSTHROUGH
            assert_transition(self._state, next_state)
            if was_passthrough:
                self._teardown_serial()
            self._set_state(next_state, reason)
            return was_passthrough

    # --- session (dashboard.md §10) -------------------------------

    def start_session(
        self,
        address: str,
        baud: int,
        start_command: str,
        on_ready: Callable[[int | None], None],
        on_strobe: Callable[[int, int], None],
    ) -> PortState:
        """Enter `IN_SESSION` and run the entry sequence in a worker thread.

        The port transition is synchronous (the caller learns immediately that
        the box was claimed); the handshake — open → DTR auto-reset → await
        `READY` → send `START` → optional `SEED` — then runs off the event loop.

        `on_ready(seed)` fires once the handshake resolves, *before* the first
        strobe, so the caller can open the session file and write its header
        (`data.md` §5.1). `on_strobe(code, ts)` fires for each parsed
        strobe. Both run on the session thread, so the caller's file I/O stays
        off the event loop.
        """
        with self._lock:
            assert_transition(self._state, PortState.IN_SESSION)
            self._baud = baud
            self._stop = threading.Event()
            self._reader = threading.Thread(
                target=self._session_loop,
                args=(address, baud, start_command, on_ready, on_strobe, self._stop),
                name=f"box{self.box}-session",
                daemon=True,
            )
            self._set_state(PortState.IN_SESSION, "starting session")
            self._reader.start()
            return self._state

    def send_session_line(self, text: str) -> None:
        """Write a raw line to the board mid-session (e.g. `STOP`).

        Doesn't force a transition — the board's own end-of-session strobe does
        (`dashboard.md` §8.3). Permitted only in `IN_SESSION`.
        """
        with self._lock:
            if self._state != PortState.IN_SESSION or self._serial is None:
                raise PortBusy(f"box {self.box} is {self._state.value}; not in a session")
            self._serial.write((text + "\n").encode("utf-8", errors="replace"))
            self._serial.flush()

    def end_session(self, reason: str) -> PortState:
        """Conclude a clean run: `IN_SESSION → IDLE`, stopping the thread."""
        with self._lock:
            self._teardown_serial()
            self._set_state(PortState.IDLE, reason)
            return self._state

    def _session_loop(
        self,
        address: str,
        baud: int,
        start_command: str,
        on_ready: Callable[[int | None], None],
        on_strobe: Callable[[int, int], None],
        stop: threading.Event,
    ) -> None:
        try:
            # Opening the port toggles DTR, which the Mega's auto-reset circuit
            # interprets as a reset — the same mechanism as §5's reset, reused.
            port = serial.Serial(
                port=address,
                baudrate=baud,
                timeout=READ_TIMEOUT_S,
                write_timeout=WRITE_TIMEOUT_S,
            )
        except (serial.SerialException, OSError) as exc:
            self.force_error(f"couldn't open {address}: {exc}")
            return

        with self._lock:
            if stop.is_set():
                port.close()
                return
            self._serial = port

        buf = bytearray()
        phase = "ready"
        seed_value: int | None = None
        ready_deadline = time.monotonic() + SESSION_READY_TIMEOUT_S
        seed_deadline = 0.0

        while not stop.is_set():
            try:
                waiting = port.in_waiting
                chunk = port.read(waiting if waiting else 1)
            except Exception as exc:  # noqa: BLE001 - board yanked mid-session
                if not stop.is_set():
                    # §10 hard stop: a drop is exactly what ERROR exists for.
                    self.force_error(f"board disconnected or unreadable: {exc}")
                return

            if chunk:
                buf.extend(chunk)
                for line in self._extract_lines(buf):
                    phase, seed_value = self._dispatch_session_line(
                        line, phase, seed_value, port, start_command, on_ready, on_strobe
                    )

            now = time.monotonic()
            if phase == "ready" and now > ready_deadline:
                self.force_error("board never reported READY")
                return
            if phase == "seed":
                if seed_deadline == 0.0:
                    seed_deadline = now + SESSION_SEED_WINDOW_S
                elif now > seed_deadline:
                    # No SEED arrived — proceed without it.
                    phase = "parse"
                    on_ready(None)

    def _dispatch_session_line(
        self,
        line: str,
        phase: str,
        seed_value: int | None,
        port: serial.Serial,
        start_command: str,
        on_ready: Callable[[int | None], None],
        on_strobe: Callable[[int, int], None],
    ) -> tuple[str, int | None]:
        """Handle one complete line according to the handshake phase."""
        text = line.strip()
        # Everything is mirrored into scrollback so a raw session log exists for
        # a profile-less sketch and for debugging (§6.1 fallback).
        self._emit(OutputLine("rx", text, time.time()))

        if phase == "ready":
            if text.upper() == READY_TOKEN:
                port.write((start_command + "\n").encode("utf-8", errors="replace"))
                port.flush()
                self._emit(OutputLine("tx", start_command, time.time()))
                return "seed", seed_value
            return "ready", seed_value

        if phase == "seed":
            seed_match = SEED_RE.match(text)
            if seed_match:
                on_ready(int(seed_match.group(1)))
                return "parse", int(seed_match.group(1))
            strobe = STROBE_RE.match(text)
            if strobe:
                # First data line arrived with no SEED — resolve, then process.
                on_ready(None)
                on_strobe(int(strobe.group(1)), int(strobe.group(2)))
                return "parse", None
            return "seed", seed_value

        # phase == "parse"
        strobe = STROBE_RE.match(text)
        if strobe:
            on_strobe(int(strobe.group(1)), int(strobe.group(2)))
        return "parse", seed_value

    def _extract_lines(self, buf: bytearray) -> list[str]:
        """Pull all complete lines out of `buf`, leaving any partial tail."""
        lines: list[str] = []
        while True:
            index, skip = _find_terminator(buf)
            if index < 0:
                break
            lines.append(buf[:index].decode("utf-8", errors="replace"))
            del buf[: index + skip]
        return lines

    # --- write ------------------------------------------------------------

    def write(self, text: str, line_ending: str = DEFAULT_LINE_ENDING) -> int:
        """Send to the board. Permitted only in `PASSTHROUGH` (§6.3).

        Enforced here rather than only in the UI, which guards against a queued
        send firing during a mid-flight state transition.
        """
        suffix = LINE_ENDINGS.get(line_ending, LINE_ENDINGS[DEFAULT_LINE_ENDING])
        with self._lock:
            if self._state != PortState.PASSTHROUGH or self._serial is None:
                raise PortBusy(
                    f"box {self.box} is {self._state.value}; sending requires PASSTHROUGH"
                )
            payload = (text + suffix).encode("utf-8", errors="replace")
            written = self._serial.write(payload) or 0

        # Echo into scrollback so sent and received history interleave (§6.3).
        self._emit(OutputLine("tx", text, time.time()))
        return written

    # --- reading ----------------------------------------------------------

    def _read_loop(self, port: serial.Serial, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                waiting = port.in_waiting
                chunk = port.read(waiting if waiting else 1)
            except Exception as exc:  # noqa: BLE001 - board yanked, port revoked, …
                if not stop.is_set():
                    log.warning("box %d: read failed: %s", self.box, exc)
                    self.force_error(f"board disconnected or unreadable: {exc}")
                return
            if chunk:
                self._ingest(chunk)

    def _ingest(self, chunk: bytes) -> None:
        """Split into lines and emit. Opaque text, error-replaced (§6.2)."""
        self._buf.extend(chunk)
        self._ingest_seq += 1

        while True:
            index, skip = _find_terminator(self._buf)
            if index < 0:
                break
            line = self._buf[:index].decode("utf-8", errors="replace")
            del self._buf[: index + skip]
            self._emit(OutputLine("rx", line, time.time()))

        if len(self._buf) > MAX_PARTIAL_BYTES:
            line = self._buf.decode("utf-8", errors="replace")
            self._buf.clear()
            self._emit(OutputLine("rx", line, time.time()))

    def _emit(self, line: OutputLine) -> None:
        self._ring.append(line)
        with self._pending_lock:
            self._pending.append(line)

    def flush_stale_partial(self) -> None:
        """Release a line held back only by an ambiguous trailing CR.

        `_find_terminator` deliberately waits on a trailing `\\r`, since it may
        be the first half of a CRLF split across reads. For a sketch that emits
        bare CR and then goes quiet, that line would otherwise never appear —
        and a debug console that withholds what the board said is worse than
        one that occasionally splits a line early.

        Requires two consecutive quiet ticks, so a genuinely split CRLF (which
        resolves within microseconds) is never affected.
        """
        with self._lock:
            unchanged = self._ingest_seq == self._seen_seq
            self._seen_seq = self._ingest_seq
            if not unchanged or not self._buf or self._buf[-1] != 0x0D:
                return
            line = self._buf[:-1].decode("utf-8", errors="replace")
            self._buf.clear()
        self._emit(OutputLine("rx", line, time.time()))

    def drain(self) -> list[OutputLine]:
        """Take everything accumulated since the last tick (§6.2 batching)."""
        with self._pending_lock:
            if not self._pending:
                return []
            batch = self._pending
            self._pending = []
            return batch

    def scrollback(self) -> list[OutputLine]:
        return list(self._ring)

    def clear_scrollback(self) -> None:
        self._ring.clear()

    # --- teardown ---------------------------------------------------------

    def _teardown_serial(self) -> None:
        """Stop the reader and close the port. Caller must hold the lock."""
        self._stop.set()
        reader, self._reader = self._reader, None
        port, self._serial = self._serial, None

        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)
        if port is not None:
            try:
                port.close()
            except Exception as exc:  # noqa: BLE001 - already gone is fine
                log.debug("box %d: error closing port: %s", self.box, exc)
        self._buf.clear()
        self._baud = None

    def shutdown(self) -> None:
        with self._lock:
            self._teardown_serial()


def _find_terminator(buf: bytearray) -> tuple[int, int]:
    """Locate the next line break. Returns (index, bytes_to_skip).

    Handles `\\n`, `\\r`, and `\\r\\n` — Arduino's `println` emits CRLF, but
    sketches written by hand emit all three.
    """
    nl = buf.find(b"\n")
    cr = buf.find(b"\r")

    if nl < 0 and cr < 0:
        return -1, 0
    if cr < 0 or (0 <= nl < cr):
        return nl, 1
    # CR first: consume a following LF as part of the same terminator.
    if cr + 1 < len(buf) and buf[cr + 1] == 0x0A:
        return cr, 2
    if cr == len(buf) - 1:
        # Might be the first half of a CRLF that hasn't arrived yet.
        return -1, 0
    return cr, 1
