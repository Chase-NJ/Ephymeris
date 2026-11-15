"""The sidecar's dispatch path, in process: `dispatch(app, cmd, **args)`.

A command sent here is a JSON frame handed to the server's own message
handler, so it goes through everything a frame from the webview does after
authentication: the protocol version check, the command lookup, argument
validation, the handler, the error table and the reply's schema check
(`conftest.py` turns wire validation on). Nothing is mocked between the frame
and the handler, and no socket is opened: `tests/live_sidecar.py` is the same
path over a real WebSocket, for what needs one (a second client, a reconnect).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.boards.tool import BoardTool
from ephymeris_sidecar.protocol import PROTOCOL_VERSION
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.server import SidecarServer
from tests.live_sidecar import NoBoards, Refused


class Connection:
    """A client connection that keeps every frame the server sends it."""

    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send(self, payload: str) -> None:
        self.frames.append(json.loads(payload))

    def events(self, evt: str) -> list[Any]:
        return [f["data"] for f in self.frames if f.get("evt") == evt]


async def dispatch(app: Application, cmd: str, **args: Any) -> Any:
    """Send `cmd` as the webview would; return its result or raise `Refused`."""
    conn = Connection()
    frame = {"v": PROTOCOL_VERSION, "id": "d1", "cmd": cmd, "args": args}
    await app.server._on_message(conn, json.dumps(frame))  # noqa: SLF001 - the path under test
    [reply] = [f for f in conn.frames if f.get("corr") == "d1"]
    if not reply["ok"]:
        error = reply["error"]
        raise Refused(error["code"], error["message"], error["detail"])
    return reply["result"]


@asynccontextmanager
async def running_app(data_dir: Path, tool: BoardTool | None = None) -> AsyncIterator[Application]:
    """A started `Application` behind a `SidecarServer` that listens on nothing."""
    data_dir.mkdir(parents=True, exist_ok=True)
    app = Application(SidecarServer("127.0.0.1", 0, "unused"), data_dir, tool=tool or NoBoards())
    app.register()
    app.start()
    try:
        yield app
    finally:
        await app.stop()
        registry.set_rig_source(None)
        registry.set_vocabulary_source(None)
