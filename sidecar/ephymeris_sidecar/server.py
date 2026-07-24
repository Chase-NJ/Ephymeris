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
import threading
from typing import Any, Awaitable, Callable

import websockets
from websockets.asyncio.server import ServerConnection, serve

from . import __version__
from .protocol import PROTOCOL_VERSION, Cmd, ErrCode, Evt, event, reply_err, reply_ok

log = logging.getLogger(__name__)

#: How long a freshly-connected client has to authenticate before it is dropped.
AUTH_TIMEOUT_S = 5.0

#: Handlers receive the command's correlation id last, so long-running commands
#: (flashing) can attribute the progress events they emit to the request that
#: caused them.
CommandHandler = Callable[
    ["SidecarServer", ServerConnection, dict[str, Any], str], Awaitable[Any]
]


class CommandError(Exception):
    """Raised by a handler to produce a typed error reply."""

    def __init__(self, code: str, message: str, detail: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class SidecarServer:
    def __init__(self, host: str, port: int, token: str) -> None:
        self.host = host
        self.port = port
        self._token = token
        self._clients: set[ServerConnection] = set()
        self._handlers: dict[str, CommandHandler] = {}
        self._on_client_ready: list[Callable[[ServerConnection], Awaitable[None]]] = []
        self._inflight: set[asyncio.Task[None]] = set()
        self._shutdown = asyncio.Event()

    # --- lifecycle --------------------------------------------------------

    def register(self, name: str, handler: CommandHandler) -> None:
        self._handlers[name] = handler

    def on_client_ready(
        self, callback: Callable[[ServerConnection], Awaitable[None]]
    ) -> None:
        """Run after a client authenticates.

        Events are broadcast as things change, so a client that connects during
        a quiet period would otherwise see nothing until the next change. This
        is where current state gets replayed to it.
        """
        self._on_client_ready.append(callback)

    async def run(self) -> None:
        async with serve(self._handle_connection, self.host, self.port) as server:
            bound_port = server.sockets[0].getsockname()[1]
            # The one line stdout is for. Flushed explicitly because stdout is a
            # pipe here, not a tty, and would otherwise sit in the block buffer.
            print(
                f"EPHYMERIS_WS_PORT={bound_port} EPHYMERIS_WS_TOKEN={self._token}",
                flush=True,
            )
            log.info("sidecar listening on %s:%d", self.host, bound_port)
            await self._shutdown.wait()
            log.info("shutting down")

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
            for callback in self._on_client_ready:
                try:
                    await callback(conn)
                except Exception:  # noqa: BLE001 - a bad replay must not drop the client
                    log.exception("client-ready callback failed")

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

    async def _on_message(self, conn: ServerConnection, raw: str | bytes) -> None:
        msg = self._parse(raw)
        if msg is None:
            await self._send(conn, reply_err("", ErrCode.BAD_MESSAGE, "Malformed JSON."))
            return

        corr = str(msg.get("id", ""))
        cmd = msg.get("cmd")
        if msg.get("v") != PROTOCOL_VERSION:
            await self._send(conn, reply_err(
                corr,
                ErrCode.PROTOCOL_VERSION_MISMATCH,
                f"Sidecar speaks protocol v{PROTOCOL_VERSION}.",
                {"expected": PROTOCOL_VERSION, "received": msg.get("v")},
            ))
            return

        handler = self._handlers.get(cmd) if isinstance(cmd, str) else None
        if handler is None:
            await self._send(conn, reply_err(
                corr, ErrCode.UNKNOWN_COMMAND, f"Unknown command: {cmd!r}"
            ))
            return

        try:
            result = await handler(self, conn, msg.get("args") or {}, corr)
        except CommandError as exc:
            await self._send(conn, reply_err(corr, exc.code, exc.message, exc.detail))
        except Exception as exc:  # noqa: BLE001 - never let one command kill the loop
            log.exception("handler for %s failed", cmd)
            await self._send(conn, reply_err(corr, ErrCode.INTERNAL, str(exc)))
        else:
            await self._send(conn, reply_ok(corr, result))

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
