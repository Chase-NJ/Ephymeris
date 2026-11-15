"""WebSocket server and command dispatch.

The server binds loopback-only on an ephemeral port and prints its handshake
line on stdout for the Tauri shell to capture:

    EPHYMERIS_WS_PORT=<port> EPHYMERIS_WS_TOKEN=<token>

Everything else this process logs goes to stderr, so stdout stays a clean,
single-purpose channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import inspect
import threading
from typing import Any, Awaitable, Callable, Sequence

import websockets
from websockets.asyncio.server import ServerConnection, serve

from . import __version__
from .protocol import (
    COMMAND_ARGS,
    PROTOCOL_VERSION,
    Cmd,
    ErrCode,
    Evt,
    WireShapeError,
    event,
    reply_err,
    reply_ok,
    validate_command_args,
    validate_command_result,
    wire_validation_enabled,
)

log = logging.getLogger(__name__)

#: How long a freshly-connected client has to authenticate before it is dropped.
AUTH_TIMEOUT_S = 5.0

#: A command's arguments, already checked against `protocol/schema.py`.
Args = dict[str, Any]

#: A handler takes its command's arguments and returns its result. It never
#: sees the connection or the envelope: everything about the wire is here.
CommandHandler = Callable[[Args], Awaitable[Any]]


class CommandError(Exception):
    """A typed error reply. A handler raises one for a refusal only the wire
    layer can name (an argument value the schema cannot describe); an error
    table's mapper returns one for an exception a domain module raised."""

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


#: `(exception, the command's args) -> its reply`, or None to leave it to a
#: later entry of the table, and failing that to INTERNAL.
ErrorMapper = Callable[[Any, Args], "CommandError | None"]
ErrorTable = Sequence[tuple[type[BaseException], ErrorMapper]]

#: The current state behind an event: one payload, a list of them (one per
#: box), or None for nothing to say. May be a coroutine function.
SnapshotProvider = Callable[[], Any]


def resolve_error(table: ErrorTable, exc: BaseException, args: Args) -> CommandError | None:
    """The reply `table` gives `exc`: the first entry whose type matches and
    whose mapper answers, or None, which the server reports as INTERNAL."""
    if isinstance(exc, CommandError):
        return exc
    for kind, mapper in table:
        if isinstance(exc, kind):
            mapped = mapper(exc, args)
            if mapped is not None:
                return mapped
    return None


def _payloads(built: Any) -> list[Any]:
    if built is None:
        return []
    if isinstance(built, dict):
        return [built]
    return list(built)


class SidecarServer:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self._token = token
        self._clients: set[ServerConnection] = set()
        self._handlers: dict[str, CommandHandler] = {}
        self._errors: ErrorTable = ()
        self._snapshots: dict[str, SnapshotProvider] = {}
        self._inflight: set[asyncio.Task[None]] = set()
        self._shutdown = asyncio.Event()
        self._bound = asyncio.Event()

    # --- what the application plugs in ------------------------------------

    def register(self, name: str, handler: CommandHandler) -> None:
        """Route `name` to `handler`, once. Only a command the schema declares:
        its arguments are checked against that declaration before `handler`
        runs (`ARCHITECTURE.md#dispatch`)."""
        if name not in COMMAND_ARGS or name == Cmd.AUTH:
            raise ValueError(f"{name!r} is not a command protocol/schema.py declares")
        if name in self._handlers:
            raise ValueError(f"{name!r} is registered twice")
        self._handlers[name] = handler

    def unhandled(self) -> set[str]:
        """Commands the schema declares that nothing is registered for."""
        return set(COMMAND_ARGS) - {Cmd.AUTH} - set(self._handlers)

    def map_errors(self, table: ErrorTable) -> None:
        """The one table every handler's exceptions are answered from."""
        self._errors = tuple(table)

    def register_snapshot(self, evt: str, provider: SnapshotProvider) -> None:
        """`provider` builds the current state behind `evt`. A client is sent
        it on connect, in registration order, and `publish(evt)` sends it to
        every client: one builder for both, so a client that reconnects is told
        what one that never left was told."""
        if evt in self._snapshots:
            raise ValueError(f"{evt!r} already has a snapshot")
        self._snapshots[evt] = provider

    async def snapshot(self, evt: str) -> list[dict[str, Any]]:
        """The events `evt`'s provider describes right now."""
        built = self._snapshots[evt]()
        if inspect.isawaitable(built):
            built = await built
        return [event(evt, payload) for payload in _payloads(built)]

    async def publish(self, evt: str) -> None:
        """Broadcast `evt`'s snapshot to every client."""
        for message in await self.snapshot(evt):
            await self.broadcast(message)

    # --- lifecycle --------------------------------------------------------

    async def run(self) -> None:
        async with serve(self._handle_connection, self.host, self.port) as server:
            bound_port = server.sockets[0].getsockname()[1]
            self.port = bound_port
            self._bound.set()
            # The one line stdout is for. Flushed explicitly because stdout is a
            # pipe here, not a tty, and would otherwise sit in the block buffer.
            print(
                f"EPHYMERIS_WS_PORT={bound_port} EPHYMERIS_WS_TOKEN={self._token}",
                flush=True,
            )
            log.info("sidecar listening on %s:%d", self.host, bound_port)
            await self._shutdown.wait()
            log.info("shutting down")

    async def bound_port(self) -> int:
        """The port `run` listens on, once it does: the one the OS picked when
        `port` was 0."""
        await self._bound.wait()
        return self.port

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def watch_parent_via_stdin(self) -> None:
        """Exit when the shell that spawned us goes away.

        Tauri holds our stdin open for the life of the app. If the shell dies or
        is force-quit, stdin hits EOF and we shut down instead of lingering — a
        stale sidecar would keep serial ports open and lock out the next launch.
        """
        loop = asyncio.get_running_loop()

        def _watch() -> None:
            try:
                while sys.stdin.buffer.read(1):
                    pass
            except Exception:  # pragma: no cover - stdin closed abruptly
                pass
            log.info("stdin closed; parent process is gone")
            loop.call_soon_threadsafe(self.request_shutdown)

        threading.Thread(target=_watch, name="parent-watch", daemon=True).start()

    # --- connection handling ---------------------------------------------

    async def _handle_connection(self, conn: ServerConnection) -> None:
        peer = conn.remote_address
        log.info("client connected: %s", peer)
        await self._send(conn, event(Evt.SERVER_HELLO, {
            "protocolVersion": PROTOCOL_VERSION,
            "sidecarVersion": __version__,
        }))

        if not await self._authenticate(conn):
            return

        self._clients.add(conn)
        try:
            await self._replay(conn)

            async for raw in conn:
                # Commands run concurrently: a flash takes tens of seconds and
                # must not block passthrough traffic on the other five boxes.
                # Replies are correlated, so out-of-order completion is fine.
                task = asyncio.create_task(self._on_message(conn, raw))
                self._inflight.add(task)
                task.add_done_callback(self._inflight.discard)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(conn)
            log.info("client disconnected: %s", peer)

    async def _authenticate(self, conn: ServerConnection) -> bool:
        """Require `auth` as the very first command.

        The token travels in a message body rather than the URL so it never
        lands in a query string.
        """
        try:
            raw = await asyncio.wait_for(conn.recv(), timeout=AUTH_TIMEOUT_S)
        except (TimeoutError, websockets.exceptions.ConnectionClosed):
            log.warning("client failed to authenticate in time")
            await conn.close(code=1008, reason="auth timeout")
            return False

        msg = self._parse(raw)
        if msg is None or msg.get("cmd") != Cmd.AUTH:
            await self._send(conn, reply_err(
                str(msg.get("id", "")) if msg else "",
                ErrCode.UNAUTHORIZED,
                "First message must be an auth command.",
            ))
            await conn.close(code=1008, reason="unauthorized")
            return False

        corr = str(msg.get("id", ""))
        supplied = (msg.get("args") or {}).get("token")
        if supplied != self._token:
            log.warning("client supplied a bad token")
            await self._send(conn, reply_err(corr, ErrCode.UNAUTHORIZED, "Invalid token."))
            await conn.close(code=1008, reason="unauthorized")
            return False

        await self._send(conn, reply_ok(corr, {"authenticated": True}))
        return True

    async def _replay(self, conn: ServerConnection) -> None:
        """Give a freshly-authenticated client the current picture: every
        registered snapshot, in registration order.

        Events are broadcast as things change, so a client that connects during
        a quiet period -- a webview reload, say -- would otherwise see nothing
        until the next change.
        """
        for evt in self._snapshots:
            try:
                messages = await self.snapshot(evt)
            except Exception:  # noqa: BLE001 - a bad snapshot must not drop the client
                log.exception("couldn't build the %s snapshot", evt)
                continue
            for message in messages:
                await self._send(conn, message)

    async def _on_message(self, conn: ServerConnection, raw: str | bytes) -> None:
        await self._send(conn, await self._reply(raw))

    async def _reply(self, raw: str | bytes) -> dict[str, Any]:
        """One frame in, its reply out. Never raises."""
        msg = self._parse(raw)
        if msg is None:
            return reply_err("", ErrCode.BAD_MESSAGE, "Malformed JSON.")

        corr = str(msg.get("id", ""))
        cmd = msg.get("cmd")
        if msg.get("v") != PROTOCOL_VERSION:
            return reply_err(
                corr,
                ErrCode.PROTOCOL_VERSION_MISMATCH,
                f"Sidecar speaks protocol v{PROTOCOL_VERSION}.",
                {"expected": PROTOCOL_VERSION, "received": msg.get("v")},
            )

        handler = self._handlers.get(cmd) if isinstance(cmd, str) else None
        if handler is None:
            return reply_err(corr, ErrCode.UNKNOWN_COMMAND, f"Unknown command: {cmd!r}")

        args = msg.get("args")
        if args is None:
            args = {}
        # Always on, unlike the reply check below: a handler reads its args as
        # the schema declares them, and checks only what the schema can't say.
        problems = validate_command_args(cmd, args)
        if problems:
            return reply_err(
                corr,
                ErrCode.BAD_MESSAGE,
                f"`{cmd}` arguments don't match the protocol: {problems[0]}",
                {"problems": problems},
            )

        try:
            result = await handler(args)
            # Opt-in (tests, dev): fail a reply whose shape drifted from
            # protocol/schema.py, instead of shipping the drift to the UI.
            if wire_validation_enabled():
                problems = validate_command_result(cmd, result)
                if problems:
                    raise WireShapeError(
                        f"`{cmd}` reply violates protocol/schema.py:\n  "
                        + "\n  ".join(problems)
                    )
        except Exception as exc:  # noqa: BLE001 - never let one command kill the loop
            mapped = (
                None if isinstance(exc, WireShapeError)
                else resolve_error(self._errors, exc, args)
            )
            if mapped is None:
                log.exception("handler for %s failed", cmd)
                cause = exc.__cause__
                message = str(exc) if cause is None else f"{exc}: {cause}"
                return reply_err(corr, ErrCode.INTERNAL, message)
            return reply_err(corr, mapped.code, mapped.message, mapped.detail)
        return reply_ok(corr, result)

    # --- outbound ---------------------------------------------------------

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Push an event to every authenticated client."""
        if not self._clients:
            return
        payload = json.dumps(message)
        await asyncio.gather(
            *(self._send_raw(c, payload) for c in tuple(self._clients)),
            return_exceptions=True,
        )

    async def _send(self, conn: ServerConnection, message: dict[str, Any]) -> None:
        await self._send_raw(conn, json.dumps(message))

    @staticmethod
    async def _send_raw(conn: ServerConnection, payload: str) -> None:
        try:
            await conn.send(payload)
        except websockets.exceptions.ConnectionClosed:
            pass

    @staticmethod
    def _parse(raw: str | bytes) -> dict[str, Any] | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return msg if isinstance(msg, dict) else None
