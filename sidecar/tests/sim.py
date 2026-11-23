"""The real sidecar on a simulated rig, for running the app with no hardware.

    python -m tests.sim --data-dir DIR [--port 8770] [--token sim] [--speed 20] [--trials 60]

Six boards are always plugged in, every flash succeeds at once, and a board
that is sent START plays a stream-grammar-2 session of the reference trial
sequences (`test_grammar2.py`) in real time divided by `--speed`, honouring
STOP at the next trial boundary. Everything else is the shipped code. App
state and session files go under DIR, never the real app data or the archive.

Point a browser preview at it by running the two `localStorage` lines it
prints in the page, then reloading (`src/lib/ws/client.ts`, `src/lib/shell/none.ts`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import threading
import time
from pathlib import Path

from websockets.asyncio.client import connect

from ephymeris_sidecar.app import Application
from ephymeris_sidecar.boards.tool import BoardTool, DetectedBoard
from ephymeris_sidecar.server import SidecarServer

from . import test_grammar2 as grammar
from .live_sidecar import LiveSidecar, animal, settings
from .scripted_board import ScriptedBoard

BOXES = range(1, 7)
ANNOUNCE = "INTERP=1\r\nSTREAM=2\r\nREADY\r\n"
TRIALS = (
    [grammar.CORRECT_R, grammar.CORRECT_L] * 6
    + [grammar.WITHHELD] * 3
    + [grammar.WRONG_WELL, grammar.HOLD_FAILED, grammar.NO_RESPONSE, grammar.FALSE_ALARM,
       grammar.LAZY, grammar.EARLY_BEFORE_ODOR, grammar.EARLY_SAMPLING]
)
STROBE_GAP_MS = 400
TRIAL_GAP_MS = 3000


class SimTool(BoardTool):
    async def list_boards(self) -> list[DetectedBoard]:
        return [DetectedBoard(hardware_id=f"SIM{box}", address=f"sim://box{box}") for box in BOXES]

    async def compile(self, sketch_dir, fqbn, libraries_path, on_line) -> None:  # noqa: ANN001
        on_line("stdout", "simulated compile")

    async def upload(self, sketch_dir, fqbn, address, on_line) -> None:  # noqa: ANN001
        on_line("stdout", "simulated upload")


class SimBoard(ScriptedBoard):
    speed = 20.0
    trials = 60

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        super().__init__(*args, **kwargs)
        self._stop = threading.Event()
        self._random = random.Random(str(self.port))
        self.say(ANNOUNCE)

    def write(self, data: bytes) -> int:
        written = super().write(data)
        for line in data.decode().splitlines():
            if line.startswith("START"):
                seed = line.partition("SEED=")[2].split()[0] if "SEED=" in line else "0"
                self.say(f"SEED\t{seed}\r\n")
                threading.Thread(target=self._session, daemon=True).start()
            elif line.strip() == "STOP":
                self._stop.set()
        return written

    def close(self) -> None:
        self._stop.set()
        super().close()

    def _session(self) -> None:
        clock = 0

        def strobe(name: str, gap_ms: int) -> None:
            nonlocal clock
            clock += gap_ms
            time.sleep(gap_ms / 1000 / self.speed)
            if not self.closed:
                self.say(f"{grammar.code(name)}\t{clock}\r\n")

        strobe("START_SESSION", STROBE_GAP_MS)
        for _ in range(self.trials):
            if self._stop.is_set() or self.closed:
                break
            names = self._random.choice(TRIALS).split()
            strobe(names[0], TRIAL_GAP_MS)
            for name in names[1:]:
                strobe(name, self._random.randint(STROBE_GAP_MS // 2, STROBE_GAP_MS * 2))
        strobe("END_SESSION", STROBE_GAP_MS)


async def seed(port: int, token: str, app: Application, data_dir: Path) -> None:
    """Bind the six boxes, and on a fresh DIR make one cohort to run."""
    async with connect(f"ws://127.0.0.1:{port}") as ws:
        client = LiveSidecar(ws, app)
        try:
            await client.call("auth", token=token)
            await client.call("settings.push", settings=settings(
                bound={box: f"SIM{box}" for box in BOXES}, dataDirectory=str(data_dir / "data"),
            ))
            if not (await client.call("cohorts.list"))["cohorts"]:
                await client.call(
                    "cohorts.create", name="Sim rats", dataFolder=str(data_dir / "data" / "Sim rats"),
                    animals=[animal(f"sim{box}", box=box) for box in BOXES],
                )
        finally:
            await client.close()


async def run(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir).resolve()
    for folder in ("app", "data"):
        (data_dir / folder).mkdir(parents=True, exist_ok=True)
    SimBoard.speed, SimBoard.trials = args.speed, args.trials
    server = SidecarServer("127.0.0.1", args.port, args.token)
    app = Application(server, data_dir / "app", tool=SimTool(), open_serial=SimBoard)
    app.register()
    app.start()
    serving = asyncio.create_task(server.run())
    try:
        port = await asyncio.wait_for(server.bound_port(), timeout=10)
        await seed(port, args.token, app, data_dir)
        endpoint = json.dumps({"port": port, "token": args.token})
        preview = json.dumps(settings(bound={box: f"SIM{box}" for box in BOXES}, dataDirectory=str(data_dir / "data")))
        print(f"simulated rig ready on port {port}; in the preview page run, then reload:", flush=True)
        print(f"localStorage.setItem('ephymeris:endpoint', {json.dumps(endpoint)})", flush=True)
        print(f"localStorage.setItem('ephymeris:settings', {json.dumps(preview)})", flush=True)
        await serving
    finally:
        server.request_shutdown()
        await app.stop()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.sim", description=__doc__.split("\n")[0])
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--token", default="sim")
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--trials", type=int, default=60)
    try:
        asyncio.run(run(parser.parse_args(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
