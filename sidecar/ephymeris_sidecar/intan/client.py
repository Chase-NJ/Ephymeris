"""The RHX command socket: get / set / execute / livenotes.

The protocol is bare text with no framing (`IntanRHX_TCPDocumentation.pdf`,
"Syntax of commands"): a `get` answers `Return: <Name> <value>`, while a `set`
or `execute` answers **nothing at all on success** and an error sentence on
failure. Intan's own example clients paper over that with `time.sleep(0.1)`
after every command. Two things are wrong with copying them:

  * a sleep confirms nothing -- a refused `set` looks exactly like an accepted
    one, and a recording configured on refused commands is a recording saved
    somewhere else, in some other format;
  * two writes with no reply between them can share one TCP segment, and RHX
    reads a segment as one command. That, not slowness, is what the sleeps are
    really for.

So every write here is ONE transmission that ends in a `get` -- the *sentinel*.
Commands in a transmission are `;`-separated (the documented batching form) and
RHX answers them in order, so whatever arrives before the sentinel's reply is
this transmission's error text, and the reply itself is the receipt. No two
transmissions are ever in flight (`_lock`), so nothing coalesces.

THE SENTINEL IS AN ASSUMPTION ABOUT RHX, AND IT IS FENCED. The documentation
shows batching with `set` only. If a build of RHX does not answer a `get` that
rides a batch, the first transmission times out waiting for its receipt; the
client then drops to the examples' discipline -- one command per transmission,
a fixed settle after each -- for the rest of the connection, and says so in the
log. Slower and blind to refusals, but correct, which is the `grpcio` rule:
degrade, don't disappear. Values that matter are read back either way
(`set(..., verify=True)`), and that works in both modes.
"""

from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger(__name__)

HOST = "127.0.0.1"

#: How long a reply may take. RHX answers a `get` in milliseconds; this is the
#: bound on "RHX is wedged", not an expected latency.
REPLY_TIMEOUT_S = 2.0
#: The examples' settle, used only in the fallback discipline.
SETTLE_S = 0.1
#: A quiet gap that ends a reply. Replies carry no terminator, so "no more
#: bytes for this long" is the only end-of-message there is.
QUIET_S = 0.03
#: Commands per transmission when batching. RHX reads a transmission into a
#: fixed buffer; forty short `set`s stay far inside the examples' 1024 bytes.
BATCH_BYTES = 900

_SENTINEL = "get version"
_SENTINEL_REPLY = re.compile(r"Return:\s*Version\s+\S+\s*$", re.IGNORECASE)
_RETURN = re.compile(r"Return:\s*(\S+)\s*(.*)$", re.IGNORECASE | re.DOTALL)

RUN_MODES = ("stop", "run", "record", "trigger")


class RhxError(Exception):
    """Anything that went wrong talking to RHX."""


class RhxUnavailable(RhxError):
    """No connection: RHX is not running, its command server is not open, or
    the socket died. Distinct from a refusal because the remedy is a person
    clicking Connect in RHX, not a different command."""


class RhxCommandFailed(RhxError):
    """RHX answered, and the answer was no."""

    def __init__(self, command: str, reply: str) -> None:
        super().__init__(f"RHX refused {command!r}: {reply.strip() or 'no value came back'}")
        self.command = command
        self.reply = reply


def rhx_path(path: str) -> str:
    """A filesystem path in the spelling RHX's examples use: forward slashes."""
    return str(path).replace("\\", "/")


def rhx_bool(value: bool) -> str:
    return "true" if value else "false"


def parse_bool(text: str) -> bool:
    return text.strip().lower() == "true"


class RhxCommandClient:
    """One connection to RHX's command server. Safe to share: calls serialise."""

    def __init__(
        self,
        port: int,
        *,
        host: str = HOST,
        reply_timeout_s: float = REPLY_TIMEOUT_S,
        settle_s: float = SETTLE_S,
    ) -> None:
        self._host = host
        self._port = port
        self._reply_timeout_s = reply_timeout_s
        self._settle_s = settle_s
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        #: None until the first write settles the question; see the module doc.
        self._sentinel_works: bool | None = None

    # --- connection -------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing() and not self.peer_closed

    @property
    def peer_closed(self) -> bool:
        """RHX hung up. Known WITHOUT sending anything: the transport feeds EOF
        to the reader the moment the peer closes, whether or not anyone is
        reading. That is what lets a disconnect be noticed between polls --
        pressing Disconnect in RHX's Remote TCP Control dialog closes this
        socket, and nothing would otherwise look at it until the next command."""
        return self._reader is not None and self._reader.at_eof()

    @property
    def confirms_writes(self) -> bool | None:
        """Whether a refused `set` is being detected. None = not yet known."""
        return self._sentinel_works

    async def connect(self, timeout_s: float = 2.0) -> None:
        await self.close()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout_s
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise RhxUnavailable(
                f"nothing is listening on {self._host}:{self._port}. In RHX, open "
                "Network → Remote TCP Control and press Connect on the Commands tab."
            ) from exc
        self._sentinel_works = None

    async def close(self) -> None:
        writer, self._reader, self._writer = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            await asyncio.wait_for(writer.wait_closed(), 1.0)
        except (OSError, asyncio.TimeoutError):
            pass

    # --- the four verbs ---------------------------------------------------

    async def get(self, parameter: str) -> str:
        """The parameter's current value, as RHX spells it."""
        async with self._lock:
            reply = await self._exchange(f"get {parameter}")
        match = _RETURN.search(reply)
        if match is None:
            raise RhxCommandFailed(f"get {parameter}", reply)
        name, value = match.group(1), match.group(2).strip()
        # Most replies are `Return: <Name> <value>`. A few are NAMELESS on the
        # real RHX -- `Return: 704383` for CurrentTimestamp, `Return: 48.3626`
        # for CurrentTimeSeconds -- and read as name-then-value they come back
        # empty, which `start_recording` then fails to parse as a number.
        return value if value else name

    async def set(self, parameter: str, value: str | int | float | bool, *, verify: bool = False) -> None:
        """Set one parameter. `verify` reads it back and refuses a mismatch.

        Verify the values a recording cannot be wrong about -- where it is
        saved, in what format, under what name. It is the only check that works
        in the fallback discipline, and the only one that catches RHX
        *accepting* a command and storing something else (a path cut at its
        first space, say).
        """
        text = rhx_bool(value) if isinstance(value, bool) else str(value)
        await self.send([f"set {parameter} {text}"])
        if not verify:
            return
        stored = await self.get(parameter)
        if stored.strip().lower() != text.strip().lower():
            raise RhxCommandFailed(
                f"set {parameter} {text}", f"RHX stored {stored!r} instead"
            )

    async def execute(self, action: str, argument: str | None = None) -> None:
        await self.send([f"execute {action}" + (f" {argument}" if argument else "")])

    async def livenote(self, note: str) -> None:
        """Append a timestamped line to the recording's notes file. Ignored by
        RHX when it is not recording, by its own rule."""
        await self.send([f"livenotes {note.replace(';', ',')}"])

    async def send(self, commands: list[str]) -> None:
        """Send writes, batched into as few transmissions as fit."""
        if not commands:
            return
        async with self._lock:
            if self._sentinel_works is False:
                for command in commands:
                    await self._write_blind(command)
                return
            for batch in _batches(commands):
                await self._write_confirmed(batch)
                if self._sentinel_works is False:
                    # The probe just failed mid-list. What was in that batch is
                    # of unknown fate, so it is resent one at a time -- every
                    # command here is an idempotent `set` or a repeatable
                    # `execute`, which is what makes that safe.
                    for command in batch:
                        await self._write_blind(command)

    # --- run mode ---------------------------------------------------------

    async def run_mode(self) -> str:
        return (await self.get("runmode")).strip().lower()

    async def set_run_mode(self, mode: str, *, timeout_s: float = 10.0) -> None:
        """Change run mode and WAIT for it to take.

        The documentation is explicit that this one is not immediate ("pause
        for a fraction of a second or continually query RunMode"), and RHX
        refuses it outright while an upload is in progress -- so that is checked
        first rather than discovered as a silent no-op.
        """
        mode = mode.lower()
        if mode not in RUN_MODES:
            raise ValueError(f"unknown run mode {mode!r}")
        if mode != "stop":
            await self._wait_for_upload(timeout_s)
        # ALONE, and unconfirmed. Observed on the real RHX: whatever follows a
        # `set runmode run` in the same transmission is not answered until
        # acquisition STOPS -- RHX enters its run loop from inside the batch and
        # finishes the batch on the way out, a minute or an hour later. So a
        # sentinel here is never answered in time (it read as "RHX stopped
        # answering" on every Start All), and its reply turns up after the next
        # `set runmode stop`, where it would answer some other question. The
        # receipt for this command is the poll below instead.
        async with self._lock:
            await self._read_available()
            self._writer_or_raise().write(f"set runmode {mode}".encode("utf-8"))
            await self._drain()
        deadline = asyncio.get_running_loop().time() + timeout_s
        patience = timeout_s
        seen = "unknown"
        while True:
            try:
                seen = await self.run_mode()
            except RhxUnavailable:
                # Quiet is not gone. RHX can still be busy with the change it
                # was just asked for; only a CLOSED socket ends the wait.
                if not self.connected:
                    raise
            if seen == mode:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise RhxCommandFailed(f"set runmode {mode}", f"still {seen!r} after {patience:g}s")
            await asyncio.sleep(0.05)

    async def _wait_for_upload(self, timeout_s: float) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while parse_bool(await self.get("uploadinprogress")):
            if asyncio.get_running_loop().time() >= deadline:
                raise RhxCommandFailed("get uploadinprogress", "an upload never finished")
            await asyncio.sleep(0.1)

    # --- transport --------------------------------------------------------

    async def _write_confirmed(self, batch: list[str]) -> None:
        if any(command.lower().startswith("set runmode") for command in batch):
            # See `set_run_mode`: nothing may ride behind a run-mode change.
            raise ValueError("`set runmode` must go through set_run_mode(), never a batch")
        reply = await self._exchange(";".join([*batch, _SENTINEL]), expect=_SENTINEL_REPLY)
        if reply is None:
            if self._sentinel_works is None:
                log.warning(
                    "RHX did not answer a get that rode a batch; falling back to one "
                    "command per transmission. Refused commands will not be detected."
                )
                self._sentinel_works = False
                return
            raise RhxUnavailable("RHX stopped answering")
        self._sentinel_works = True
        errors = _SENTINEL_REPLY.sub("", reply).strip()
        if errors:
            raise RhxCommandFailed("; ".join(batch), errors)

    async def _write_blind(self, command: str) -> None:
        self._writer_or_raise().write(command.encode("utf-8"))
        await self._drain()
        await asyncio.sleep(self._settle_s)
        # Anything that did come back is an error sentence for this command.
        stray = await self._read_available()
        if stray.strip():
            raise RhxCommandFailed(command, stray)

    async def _exchange(self, transmission: str, expect: re.Pattern[str] | None = None) -> str | None:
        """Write one transmission and read its reply.

        With `expect`, reads until the pattern closes the reply and returns None
        on timeout (the caller decides what silence means). Without, a reply is
        required and silence is `RhxUnavailable`.
        """
        # A reply nobody read belongs to a transmission that timed out; leaving
        # it would be answered to the NEXT question.
        await self._read_available()
        self._writer_or_raise().write(transmission.encode("utf-8"))
        await self._drain()

        reader = self._reader
        assert reader is not None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._reply_timeout_s
        text = ""
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                if expect is not None:
                    return None
                raise RhxUnavailable(f"RHX did not answer {transmission!r}")
            try:
                # Once something has arrived, a short quiet gap ends the reply.
                chunk = await asyncio.wait_for(
                    reader.read(4096), min(remaining, QUIET_S) if text and expect is None else remaining
                )
            except asyncio.TimeoutError:
                if text and expect is None:
                    return text
                continue
            except OSError as exc:
                await self.close()
                raise RhxUnavailable("the RHX command socket failed") from exc
            if not chunk:
                await self.close()
                raise RhxUnavailable("RHX closed the command socket")
            text += chunk.decode("utf-8", errors="replace")
            if expect is not None and expect.search(text):
                return text

    async def _read_available(self) -> str:
        reader = self._reader
        if reader is None:
            return ""
        text = ""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(4096), 0.001)
            except (asyncio.TimeoutError, OSError):
                return text
            if not chunk:
                return text
            text += chunk.decode("utf-8", errors="replace")

    def _writer_or_raise(self) -> asyncio.StreamWriter:
        if not self.connected:
            raise RhxUnavailable("not connected to RHX")
        assert self._writer is not None
        return self._writer

    async def _drain(self) -> None:
        assert self._writer is not None
        try:
            await self._writer.drain()
        except OSError as exc:
            await self.close()
            raise RhxUnavailable("the RHX command socket failed") from exc


def _batches(commands: list[str]) -> list[list[str]]:
    out: list[list[str]] = []
    current: list[str] = []
    size = 0
    for command in commands:
        cost = len(command.encode("utf-8")) + 1
        if current and size + cost > BATCH_BYTES:
            out.append(current)
            current, size = [], 0
        current.append(command)
        size += cost
    if current:
        out.append(current)
    return out
