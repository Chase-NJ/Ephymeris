"""Per-port handler: state machine, reader thread, ring buffer, write path.

One instance per box. Deliberately a *single* object owning both the read loop
and `write()` — `ARCHITECTURE.md#passthrough-send` requires that reads and writes
are never split across separate objects for the same port, so state transitions
can't race a queued write.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal

import serial

from ..tasks.start_command import ParamsExchange, StartCommand, StartRefused
from .states import (
    ACKNOWLEDGE_FROM,
    CLAIM_FROM,
    CLOSE_FROM,
    FINISH_FROM,
    FLASH_OR_RESET,
    IDLE_ONLY,
    OPEN_FROM,
    RELEASE_FROM,
    RESUME_FROM,
    IllegalTransition,
    TakeRefused,
    PortState,
    assert_leaves,
    assert_transition,
)

log = logging.getLogger(__name__)

#: `IN_SESSION` line recognition (`ARCHITECTURE.md#entering-in_session` step 6). Stricter
#: than PASSTHROUGH's opaque text: a data line is exactly `<code>\t<timestamp>`,
#: code 1–3 digits. Anything else is logged but not treated as data.
STROBE_RE = re.compile(r"^(\d{1,3})\t(\d+)$")
SEED_RE = re.compile(r"^SEED\t(\d+)$")
#: Announced before `READY`: which firmware interpreter the sketch is, and
#: how many bytes of RAM it has free with its tables loaded
#: (`TASKS.md#confirming-the-parameters`).
INTERP_RE = re.compile(r"^INTERP=(\d+)$")
FREE_RAM_RE = re.compile(r"^FREE_RAM=(\d+)$")
READY_TOKEN = "READY"


@dataclass(frozen=True)
class Announced:
    """What a board said about itself before `READY`. None for what it did not say."""

    interp: int | None = None
    free_ram: int | None = None

#: How long to wait for the board's `READY` after opening (it reboots via the
#: DTR auto-reset first, so this must cover `setup()`).
SESSION_READY_TIMEOUT_S = 10.0
#: How long the board has to answer one `SET` line with `PARAMS`. Parsing a
#: line takes the Mega well under a millisecond, so silence this long is a
#: sketch that does not speak `SET` (`TASKS.md#the-start-line`).
SESSION_PARAMS_TIMEOUT_S = 3.0
#: Brief window after `START` to catch an optional `SEED` line
#: (`ARCHITECTURE.md#entering-in_session` step 5).
SESSION_SEED_WINDOW_S = 1.5

#: Passthrough scrollback is debug output, not data to retain (`ARCHITECTURE.md#passthrough-read`).
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


class SessionClaim:
    """One run's hold on a port in `IN_SESSION` (`ARCHITECTURE.md#entering-in_session`).

    Exists only once the port has moved `IDLE → IN_SESSION`: `claim_session`
    raises before anything starts, so a holder records a run only once it has
    one. A port holds at most one claim, and a claim is current from that
    transition until the port next leaves `IN_SESSION`:

    * `request_stop()` sends `STOP` and says whether it went out. Never raises.
    * `release(reason)` ends a clean run, `IN_SESSION → IDLE`. Idempotent, and
      a no-op once the claim is not current: it never clears an `ERROR`, and
      never ends a later claim's run.
    * `on_lost(reason)`, given at claim time, runs on the loop when the port
      leaves `IN_SESSION` for `ERROR` (`ARCHITECTURE.md#board-drop`), at most
      once, never after `release`.
    """

    def __init__(self, handler: "PortHandler", address: str, on_lost: Callable[[str], None]) -> None:
        self.box = handler.box
        self.address = address
        self._handler = handler
        self._on_lost = on_lost

    def request_stop(self) -> bool:
        """Ask the board to stop at its next trial boundary (`ARCHITECTURE.md#clean-exit`).
        False when the port has left `IN_SESSION`, has no open port yet (the
        handshake is still opening it), or the write failed."""
        return self._handler._request_stop(self)

    def release(self, reason: str) -> None:
        """`IN_SESSION → IDLE` if this claim is still current; otherwise nothing.
        Blocking: joins the session thread, so call it off the loop."""
        self._handler._release(self, reason)

    def _lost(self, reason: str) -> None:
        try:
            self._on_lost(reason)
        except Exception:  # noqa: BLE001 - the port's own bookkeeping must go on
            log.exception("box %d: on_lost failed", self.box)


#: Opens a serial port: `serial.Serial`'s signature. Injected so a test can
#: drive the real handler and manager with a scripted board behind them.
OpenSerial = Callable[..., Any]


class PortHandler:
    def __init__(
        self,
        box: int,
        loop: asyncio.AbstractEventLoop,
        on_state_change: Callable[[int, PortState, PortState, str], None],
        open_serial: OpenSerial | None = None,
    ) -> None:
        self.box = box
        self._loop = loop
        self._on_state_change = on_state_change
        # Looked up at each open when not given, so `serial.Serial` is what it
        # is at the time of the open.
        self._open_serial = open_serial

        self._state = PortState.IDLE
        self._lock = threading.RLock()
        #: The current `SessionClaim`; set exactly while the state is `IN_SESSION`.
        self._claim: SessionClaim | None = None

        self._serial: serial.Serial | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()
        self._buf = bytearray()
        self._baud: int | None = None

        self._ring: deque[OutputLine] = deque(maxlen=RING_CAPACITY)
        self._pending: list[OutputLine] = []
        self._pending_lock = threading.Lock()
        #: Callbacks hearing each line the board sends, for a caller waiting on a
        #: reply (`send_start`). Guarded by `_pending_lock`, called off it.
        self._listeners: list[Callable[[str], None]] = []

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
        """Move state, enforcing the transition table (`ARCHITECTURE.md#transitions`). Caller must hold the lock."""
        previous = self._state
        if previous == to:
            return
        assert_transition(previous, to)
        self._state = to
        # Leaving IN_SESSION ends the claim, whoever moved the port. Leaving it
        # for ERROR is a lost session, told to the claim's holder.
        lost: SessionClaim | None = None
        if previous == PortState.IN_SESSION:
            claim, self._claim = self._claim, None
            if to == PortState.ERROR:
                lost = claim
        log.info("box %d: %s -> %s (%s)", self.box, previous.value, to.value, reason)
        # Always hand the notification to the loop thread: this is reachable
        # from the reader thread when a board disappears mid-stream. One
        # hand-off per transition, as ever; a lost claim hears of it in the
        # same callback, after the state change is announced.
        self._loop.call_soon_threadsafe(self._announce, previous, to, reason, lost)

    def _announce(
        self, previous: PortState, to: PortState, reason: str, lost: SessionClaim | None
    ) -> None:
        """Runs on the loop. A lost claim hears of it even if the announcement raised."""
        try:
            self._on_state_change(self.box, previous, to, reason)
        finally:
            if lost is not None:
                lost._lost(reason)

    def force_error(self, reason: str) -> None:
        with self._lock:
            if self._state == PortState.ERROR:
                return
            self._teardown_serial()
            self._set_state(PortState.ERROR, reason)

    def _acquire_unless_stopped(self, stop: threading.Event) -> bool:
        """Take the lock from a worker thread, or give up once told to stop.

        Teardown holds the lock while it joins the worker, so a worker blocked
        on it would stall teardown for the whole join timeout and then act on a
        port that has since moved on. True means the lock is held and `stop` is
        clear; the caller must release it.
        """
        while not stop.is_set():
            if self._lock.acquire(timeout=READ_TIMEOUT_S):
                if not stop.is_set():
                    return True
                self._lock.release()
        return False

    def _fail_from_worker(self, stop: threading.Event, reason: str) -> None:
        """`force_error` for a reader thread. A worker that has been told to
        stop no longer owns the port, so its failure changes nothing."""
        if not self._acquire_unless_stopped(stop):
            return
        try:
            if self._state != PortState.ERROR:
                self._teardown_serial()
                self._set_state(PortState.ERROR, reason)
        finally:
            self._lock.release()

    def acknowledge_error(self) -> PortState:
        """`ERROR → IDLE` on the operator's acknowledgement: the only way out of
        `ERROR` (`ARCHITECTURE.md#port-verbs`). A port already `IDLE` has
        nothing to acknowledge, as when a second window got there first."""
        with self._lock:
            if self._state is PortState.IDLE:
                return self._state
            assert_leaves(self._state, ACKNOWLEDGE_FROM, PortState.IDLE)
            self._set_state(PortState.IDLE, "error acknowledged")
            return self._state

    # --- passthrough ------------------------------------------------------

    def open_passthrough(self, address: str, baud: int) -> PortState:
        """Open a console on a port nobody holds: `IDLE → PASSTHROUGH`."""
        with self._lock:
            assert_leaves(self._state, OPEN_FROM, PortState.PASSTHROUGH)
            return self._open_passthrough(address, baud)

    def resume_passthrough(self, address: str, baud: int) -> PortState:
        """Give a flash or reset's port back to the console it took
        (`ARCHITECTURE.md#exclusivity`): `FLASHING`/`RESETTING → PASSTHROUGH`."""
        with self._lock:
            assert_leaves(self._state, RESUME_FROM, PortState.PASSTHROUGH)
            return self._open_passthrough(address, baud)

    def _open_passthrough(self, address: str, baud: int) -> PortState:
        """Caller holds the lock and has checked the verb."""
        try:
            port = self._open(
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
        """Close a console: `PASSTHROUGH → IDLE`, and from nothing else. A close
        that arrives once the port has moved on (a flash took it, it faulted)
        is refused rather than freeing a port the console no longer holds."""
        with self._lock:
            assert_leaves(self._state, CLOSE_FROM, PortState.IDLE)
            self._teardown_serial()
            self._set_state(PortState.IDLE, reason)
            return self._state

    def finish_to_idle(self, reason: str) -> PortState:
        """Conclude a flash or reset that isn't resuming a console:
        `FLASHING`/`RESETTING → IDLE`."""
        with self._lock:
            assert_leaves(self._state, FINISH_FROM, PortState.IDLE)
            self._set_state(PortState.IDLE, reason)
            return self._state

    def release_for(
        self,
        next_state: PortState,
        reason: str,
        *,
        from_: frozenset[PortState] = IDLE_ONLY,
    ) -> bool:
        """Hand the port to a flash or reset, returning whether to auto-resume.

        `from_` is what the caller may take (`ARCHITECTURE.md#port-verbs`):
        `IDLE_ONLY` for the utility baseline, which must never take a console,
        and `IDLE_OR_CONSOLE` for a flash or reset a person asked for. Any
        other port raises `TakeRefused`, with nothing changed. Entering
        `FLASHING`/`RESETTING` from `PASSTHROUGH` releases the console cleanly
        first, and the caller should resume it afterward so the user sees the
        new sketch's output without an extra click (`ARCHITECTURE.md#exclusivity`).
        """
        if next_state not in FLASH_OR_RESET:
            raise ValueError(f"release_for hands a port to a flash or reset, not {next_state.value}")
        with self._lock:
            was_passthrough = self._state == PortState.PASSTHROUGH
            try:
                assert_leaves(self._state, from_, next_state)
            except IllegalTransition as exc:
                raise TakeRefused(exc.current, exc.requested) from None
            if was_passthrough:
                self._teardown_serial()
            self._set_state(next_state, reason)
            return was_passthrough

    # --- session (ARCHITECTURE.md#entering-in_session) -------------------------------

    def claim_session(
        self,
        address: str,
        baud: int,
        command: StartCommand,
        seed: int,
        on_ready: Callable[[int | None, Announced], None],
        on_strobe: Callable[[int, int], None],
        on_lost: Callable[[str], None] = lambda _reason: None,
        on_refused: Callable[[StartRefused], None] = lambda _refused: None,
    ) -> SessionClaim:
        """Enter `IN_SESSION` and run the entry sequence in a worker thread.

        Raises `IllegalTransition` unless the port is `IDLE`, before anything
        starts. The port transition is synchronous (the caller holds the claim
        when this returns); the handshake — open → DTR auto-reset → await
        `READY` → send each `SET` line and hold its `PARAMS` against `command` →
        send `START SEED=<seed>` → optional `SEED` — then runs off the event loop.

        `on_ready(seed, announced)` fires once the handshake resolves, *before* the
        first strobe, so the caller can open the session file and write its
        header (`DATA.md#written-live`); `announced` is what the board said
        before `READY`, or None. `on_strobe(code, ts)` fires for each parsed
        strobe. Both run on the session thread, so the caller's file I/O stays
        off the event loop.

        `on_refused(refusal)` fires, on the session thread, when the board's
        answer to the parameter block refuses the start. `START` has not been
        sent and the port is on its way to `ERROR`, so `on_lost` follows.
        """
        with self._lock:
            assert_leaves(self._state, CLAIM_FROM, PortState.IN_SESSION)
            self._baud = baud
            self._stop = threading.Event()
            self._reader = threading.Thread(
                target=self._session_loop,
                args=(address, baud, command, seed, on_ready, on_strobe, on_refused, self._stop),
                name=f"box{self.box}-session",
                daemon=True,
            )
            self._set_state(PortState.IN_SESSION, "starting session")
            claim = SessionClaim(self, address, on_lost)
            self._claim = claim
            self._reader.start()
            return claim

    def _request_stop(self, claim: SessionClaim) -> bool:
        """`SessionClaim.request_stop`. Doesn't force a transition: the board's
        own end-of-session strobe does (`ARCHITECTURE.md#clean-exit`)."""
        with self._lock:
            if self._claim is not claim or self._serial is None:
                return False
            try:
                self._serial.write(b"STOP\n")
                self._serial.flush()
            except Exception as exc:  # noqa: BLE001 - the reader notices a dead port
                log.warning("box %d: couldn't send STOP: %s", self.box, exc)
                return False
            return True

    def _release(self, claim: SessionClaim, reason: str) -> None:
        """`SessionClaim.release`: `IN_SESSION → IDLE`, stopping the thread."""
        with self._lock:
            if self._claim is not claim:
                return
            # A current claim is one whose port is `IN_SESSION`.
            assert_leaves(self._state, RELEASE_FROM, PortState.IDLE)
            self._teardown_serial()
            self._set_state(PortState.IDLE, reason)

    def _session_loop(
        self,
        address: str,
        baud: int,
        command: StartCommand,
        seed: int,
        on_ready: Callable[[int | None, Announced], None],
        on_strobe: Callable[[int, int], None],
        on_refused: Callable[[StartRefused], None],
        stop: threading.Event,
    ) -> None:
        try:
            # Opening the port toggles DTR, which the Mega's auto-reset circuit
            # interprets as a reset — the same mechanism as a DTR reset (`ARCHITECTURE.md#reset`), reused.
            port = self._open(
                port=address,
                baudrate=baud,
                timeout=READ_TIMEOUT_S,
                write_timeout=WRITE_TIMEOUT_S,
            )
        except (serial.SerialException, OSError) as exc:
            self._fail_from_worker(stop, f"couldn't open {address}: {exc}")
            return

        # Publish the port, unless the session ended while it was opening: then
        # nobody else will close it. Opening can outlast teardown's join, so
        # this is also where a late open is put right.
        if not self._acquire_unless_stopped(stop):
            port.close()
            return
        try:
            self._serial = port
        finally:
            self._lock.release()

        buf = bytearray()
        shake = _Handshake(command, seed)
        ready_deadline = time.monotonic() + SESSION_READY_TIMEOUT_S
        seed_deadline = 0.0

        while not stop.is_set():
            try:
                waiting = port.in_waiting
                chunk = port.read(waiting if waiting else 1)
            except Exception as exc:  # noqa: BLE001 - board yanked mid-session
                # Hard stop (`ARCHITECTURE.md#board-drop`): a drop is exactly what ERROR exists for.
                self._fail_from_worker(stop, f"board disconnected or unreadable: {exc}")
                return

            if chunk:
                buf.extend(chunk)
                for line in self._extract_lines(buf):
                    try:
                        self._dispatch_session_line(line, shake, port, on_ready, on_strobe)
                    except StartRefused as refused:
                        self._refuse_start(stop, refused, on_refused)
                        return

            now = time.monotonic()
            if shake.phase == "ready" and now > ready_deadline:
                self._fail_from_worker(stop, "board never reported READY")
                return
            if shake.phase == "params" and now > shake.params_deadline:
                try:
                    command.verify(None)
                except StartRefused as refused:
                    self._refuse_start(stop, refused, on_refused)
                    return
            if shake.phase == "seed":
                if seed_deadline == 0.0:
                    seed_deadline = now + SESSION_SEED_WINDOW_S
                elif now > seed_deadline:
                    # No SEED arrived — proceed without it.
                    shake.phase = "parse"
                    on_ready(None, shake.announced)

    def _refuse_start(
        self,
        stop: threading.Event,
        refused: StartRefused,
        on_refused: Callable[[StartRefused], None],
    ) -> None:
        """Tell the run why its start was refused, then put the port in `ERROR`
        (which is what `on_lost` answers). `START` was never sent, so the board is
        still waiting at its prompt: the operator fixes the cause and starts again."""
        log.warning("box %d: start refused (%s): %s", self.box, refused.reason, refused)
        try:
            on_refused(refused)
        except Exception:  # noqa: BLE001 - the refusal must still reach the port
            log.exception("box %d: refusal callback failed", self.box)
        self._fail_from_worker(stop, str(refused))

    def _dispatch_session_line(
        self,
        line: str,
        shake: "_Handshake",
        port: serial.Serial,
        on_ready: Callable[[int | None, Announced], None],
        on_strobe: Callable[[int, int], None],
    ) -> None:
        """Handle one complete line according to the handshake phase.

        Raises `StartRefused` when the board's answer to the parameter block
        refuses the start."""
        text = line.strip()
        # Everything is mirrored into scrollback so a raw session log exists for
        # a profile-less sketch and for debugging (`TASKS.md#overview`).
        self._emit(OutputLine("rx", text, time.time()))

        if shake.phase == "ready":
            interp = INTERP_RE.match(text)
            free_ram = FREE_RAM_RE.match(text)
            if interp:
                shake.announced = replace(shake.announced, interp=int(interp.group(1)))
            elif free_ram:
                shake.announced = replace(shake.announced, free_ram=int(free_ram.group(1)))
            elif text.upper() == READY_TOKEN:
                shake.phase = "params"
                self._send_line(port, shake.command.begin_line)
                self._send_line(port, shake.exchange.first_line)
                shake.params_deadline = time.monotonic() + SESSION_PARAMS_TIMEOUT_S
            return

        if shake.phase == "params":
            # One line at a time: the Mega's receive buffer is 64 bytes, and a
            # second line written before the first is parsed could overrun it.
            following = shake.exchange.hear(text)
            if following is not None:
                self._send_line(port, following)
                shake.params_deadline = time.monotonic() + SESSION_PARAMS_TIMEOUT_S
            elif shake.exchange.done:
                self._send_line(port, shake.command.start_line(shake.seed))
                shake.phase = "seed"
            return

        if shake.phase == "seed":
            seed_match = SEED_RE.match(text)
            if seed_match:
                on_ready(int(seed_match.group(1)), shake.announced)
                shake.phase = "parse"
                return
            strobe = STROBE_RE.match(text)
            if strobe:
                # First data line arrived with no SEED — resolve, then process.
                on_ready(None, shake.announced)
                on_strobe(int(strobe.group(1)), int(strobe.group(2)))
                shake.phase = "parse"
            return

        # phase == "parse"
        strobe = STROBE_RE.match(text)
        if strobe:
            on_strobe(int(strobe.group(1)), int(strobe.group(2)))

    def _send_line(self, port: serial.Serial, text: str) -> None:
        port.write((text + "\n").encode("utf-8", errors="replace"))
        port.flush()
        self._emit(OutputLine("tx", text, time.time()))

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

    def send_start(self, command: StartCommand, start_line: str) -> int:
        """Debug Mode's start: the parameter block, confirmed, then `start_line`.

        The same handshake a session makes (`_dispatch_session_line`) over a
        console that is already open: each `SET` line goes out alone, its
        `PARAMS` is waited for, and the final answer is held against `command`.
        Raises `StartRefused` — with `start_line` never written — when the board
        refuses the block or does not answer. Blocks, so call it off the event
        loop. Returns the bytes written for `start_line`.
        """
        answers: queue.Queue[str] = queue.Queue()
        exchange = ParamsExchange(command)
        with self._pending_lock:
            self._listeners.append(answers.put)
        try:
            self.write(command.begin_line)
            self.write(exchange.first_line)
            deadline = time.monotonic() + SESSION_PARAMS_TIMEOUT_S
            while not exchange.done:
                try:
                    text = answers.get(timeout=max(0.0, deadline - time.monotonic()))
                except queue.Empty:
                    command.verify(None)  # nothing answered: always raises
                    raise AssertionError("verify(None) must refuse") from None  # pragma: no cover
                following = exchange.hear(text)
                if following is not None:
                    self.write(following)
                    deadline = time.monotonic() + SESSION_PARAMS_TIMEOUT_S
            return self.write(start_line)
        finally:
            with self._pending_lock:
                self._listeners.remove(answers.put)

    def write(self, text: str, line_ending: str = DEFAULT_LINE_ENDING) -> int:
        """Send to the board. Permitted only in `PASSTHROUGH` (`ARCHITECTURE.md#passthrough-send`).

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

        # Echo into scrollback so sent and received history interleave (`ARCHITECTURE.md#passthrough-send`).
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
                self._fail_from_worker(stop, f"board disconnected or unreadable: {exc}")
                return
            if chunk:
                self._ingest(chunk)

    def _ingest(self, chunk: bytes) -> None:
        """Split into lines and emit. Opaque text, error-replaced (`ARCHITECTURE.md#passthrough-read`)."""
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
            listeners = list(self._listeners)
        if line.dir == "rx":
            for listener in listeners:
                listener(line.text)

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
        """Take everything accumulated since the last tick (`ARCHITECTURE.md#passthrough-read`)."""
        with self._pending_lock:
            if not self._pending:
                return []
            batch = self._pending
            self._pending = []
            return batch

    def scrollback(self) -> list[OutputLine]:
        return list(self._ring)

    def _open(self, **kwargs: Any) -> Any:
        return (self._open_serial or serial.Serial)(**kwargs)

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


@dataclass
class _Handshake:
    """Where one session start is in its handshake, owned by the session thread.

    `ready` → `params` (a `SET` line out, its `PARAMS` awaited, once per line) →
    `seed` (`START` sent, optional `SEED` awaited) → `parse` (strobes).
    """

    command: StartCommand
    seed: int
    phase: str = "ready"
    #: What the board announced before `READY`.
    announced: Announced = field(default_factory=Announced)
    exchange: ParamsExchange = field(init=False)
    params_deadline: float = 0.0

    def __post_init__(self) -> None:
        self.exchange = ParamsExchange(self.command)


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
