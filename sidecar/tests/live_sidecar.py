"""The sidecar as the frontend meets it: a real `Application` behind a real
`SidecarServer`, driven over a WebSocket (`ARCHITECTURE.md#wire-protocol`).

A command sent here goes through authentication, dispatch, the handler's own
error mapping and the reply's schema check (`conftest.py` turns wire validation
on), so wiring that lives in `app.py` is tested where it runs. Only the
hardware is fake: the board tool, and serial wherever a test patches pyserial.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from websockets.asyncio.client import ClientConnection, connect

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard, FlashFailed
from ephymeris_sidecar.protocol import PROTOCOL_VERSION
from ephymeris_sidecar.rig import registry
from ephymeris_sidecar.server import SidecarServer

TOKEN = "test-token"


class Refused(Exception):
    """An error reply: the command was refused with `code`."""

    def __init__(self, code: str, message: str, detail: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.detail = detail


class NoBoards(BoardTool):
    """A rig with nothing plugged in."""

    async def list_boards(self) -> list[DetectedBoard]:
        return []

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:  # noqa: ANN001
        raise FlashFailed("no boards in this test")

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:  # noqa: ANN001
        raise FlashFailed("no boards in this test")


class LiveSidecar:
    """One authenticated client. Replies are matched by correlation id, so a
    test can leave a slow command in flight and send another meanwhile."""

    def __init__(self, ws: ClientConnection, app: Application) -> None:
        self.app = app
        #: Every event received, in order.
        self.events: list[dict[str, Any]] = []
        self._ws = ws
        self._replies: dict[str, dict[str, Any]] = {}
        self._arrived = asyncio.Condition()
        self._sent = 0
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        async for raw in self._ws:
            message = json.loads(raw)
            async with self._arrived:
                if "evt" in message:
                    self.events.append(message)
                else:
                    self._replies[message["corr"]] = message
                self._arrived.notify_all()

    async def send(self, cmd: str, **args: Any) -> str:
        """Send a command without waiting; returns its correlation id for `reply`."""
        self._sent += 1
        corr = f"t{self._sent}"
        await self._ws.send(json.dumps({"v": PROTOCOL_VERSION, "id": corr, "cmd": cmd, "args": args}))
        return corr

    async def reply(self, corr: str, timeout: float = 10.0) -> Any:
        """The result of the command sent as `corr`, or `Refused`."""
        async with self._arrived:
            await asyncio.wait_for(self._arrived.wait_for(lambda: corr in self._replies), timeout)
            message = self._replies.pop(corr)
        if not message["ok"]:
            error = message["error"]
            raise Refused(error["code"], error["message"], error["detail"])
        return message["result"]

    async def call(self, cmd: str, **args: Any) -> Any:
        return await self.reply(await self.send(cmd, **args))

    def latest(self, evt: str) -> Any:
        """The newest payload of `evt`, or None if it never arrived."""
        return next((e["data"] for e in reversed(self.events) if e["evt"] == evt), None)

    async def until(self, predicate: Callable[[], bool], timeout: float = 10.0) -> None:
        """Wait for `predicate`, which reads events or the fakes; fail after `timeout`."""
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("timed out waiting on the sidecar")
            await asyncio.sleep(0.01)

    async def close(self) -> None:
        self._reader.cancel()
        try:
            await self._reader
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


async def create_cohort(sidecar: LiveSidecar, folder: Path) -> dict[str, Any]:
    """A cohort at `folder` with one animal on box 1, so a session can run."""
    created = await sidecar.call(
        "cohorts.create", name=folder.name, dataFolder=str(folder),
        groups=[{"id": "g1", "name": "Morning", "order": 0}],
        animals=[{"name": "rat1", "groupId": "g1", "boxNumber": 1}],
    )
    return created["cohort"]


async def sketch_path(sidecar: LiveSidecar, name: str) -> Path:
    sketches = (await sidecar.call("sketches.refresh"))["sketches"]
    return Path(next(s["path"] for s in sketches if s["name"] == name))


async def hold_the_rig(sidecar: LiveSidecar, cohort: dict[str, Any]) -> str:
    """Set up a session of `cohort` and confirm GRGL on box 1, so the session
    holds the rig (`SessionLifecycle.in_use`). Returns the session id."""
    prefix = (await sidecar.call("prefixes.create", name="2O-Bdisc"))["prefix"]["id"]
    session = (await sidecar.call(
        "sessions.create", cohortId=cohort["id"], prefixId=prefix, sessionNumber="1"
    ))["session"]
    [animal] = cohort["animals"]
    grgl = await sketch_path(sidecar, "GRGL")
    await sidecar.call(
        "sessions.confirmMapping", sessionId=session["id"], groupId="g1",
        boxes=[{"box": 1, "animalId": animal["id"], "sketchPath": str(grgl), "config": {}}],
    )
    return session["id"]


@asynccontextmanager
async def live_sidecar(data_dir: Path, tool: BoardTool | None = None) -> AsyncIterator[LiveSidecar]:
    """Start the sidecar on a free loopback port, connect and authenticate."""
    data_dir.mkdir(parents=True, exist_ok=True)
    server = SidecarServer("127.0.0.1", 0, TOKEN)
    app = Application(server, data_dir, tool=tool or NoBoards())
    app.register()
    app.start()
    serving = asyncio.create_task(server.run())
    try:
        port = await asyncio.wait_for(server.bound_port(), timeout=5)
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            client = LiveSidecar(ws, app)
            await client.call("auth", token=TOKEN)
            try:
                yield client
            finally:
                await client.close()
    finally:
        server.request_shutdown()
        await serving
        await app.stop()
        # The rig definition pointed the process-wide registry at this
        # machine's wiring and vocabulary; the next test gets the defaults.
        registry.set_rig_source(None)
        registry.set_vocabulary_source(None)
