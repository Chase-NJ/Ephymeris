"""Start the packaged sidecar and have it do a piece of real work
(`DEVELOPING.md#building-the-installer`).

    python packaging/check_frozen.py <executable> [its arguments...]

The sidecar is launched as the shell launches it: stdin held open, so its
parent watch is parked on a read, and stdout read for the handshake line. Over
its WebSocket it is asked to recover a crashed run, a `.tsv` written here by
the real writer. The `.mat` it rebuilds is read back here and compared with
the strobes that went in, since recovery reports a run recovered whether or
not its `.mat` was written. Closing stdin must then end it cleanly.

That is what only a frozen build gets wrong and nothing else notices
(`LESSONS.md#freezing-the-sidecar-pyinstaller`): an import the freeze left
out, the scipy load that hangs the launch, a `.mat` quietly not written.

`tests/test_check_frozen.py` runs the same check against this interpreter's
own sidecar, so a change to the wire that breaks the check is caught by the
suite, not by the next release.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

#: A first launch of a fresh freeze is scanned file by file on Windows.
LAUNCH_SECONDS = 120.0
REPLY_SECONDS = 60.0
EXIT_SECONDS = 30.0

#: The crashed run's strobes, by name (`TASKS.md#strobe-vocabulary`), 500 ms apart.
STROBES = ("START_SESSION", "ODOR_1_ON", "FLUID_R", "END_SESSION")

LOG_TAIL_LINES = 40


class CheckFailed(Exception):
    """Why this sidecar must not ship."""


def crashed_run(data_folder: Path) -> tuple[Path, list[list[int]]]:
    """A run that lost power in `data_folder`: the `.tsv` alone, as the real
    writer leaves it. Returns where its `.mat` belongs and the strobes in it."""
    from ephymeris_sidecar.rig import registry
    from ephymeris_sidecar.sessions.paths import resolve_animal_files
    from ephymeris_sidecar.sessions.writer import AnimalWriter

    vocabulary = registry.vocabulary()
    strobes = [[vocabulary.code_of(name), 500 * at] for at, name in enumerate(STROBES)]
    files = resolve_animal_files(
        data_folder / "check_1_2026-01-01", "rat1", "check", "1", datetime(2026, 1, 1, 9, 0, 0)
    )
    writer = AnimalWriter(files.tsv, files.json, files.mat, {"rat": "rat1", "session_id": "check_1"}, {})
    writer.open_files()
    for code, at in strobes:
        writer.record(code, at)
    del writer
    return files.mat, strobes


def handshake(process: subprocess.Popen) -> tuple[int, str]:
    """The port and token from the sidecar's first line of stdout
    (`ARCHITECTURE.md#startup-handshake`). A sidecar that never prints it is
    killed when the wait runs out."""
    hung = threading.Event()

    def give_up() -> None:
        hung.set()
        process.kill()

    overdue = threading.Timer(LAUNCH_SECONDS, give_up)
    overdue.start()
    try:
        line = process.stdout.readline().decode("utf-8", "replace").strip()
    finally:
        overdue.cancel()
    fields = dict(part.split("=", 1) for part in line.split() if "=" in part)
    try:
        return int(fields["EPHYMERIS_WS_PORT"]), fields["EPHYMERIS_WS_TOKEN"]
    except (KeyError, ValueError):
        pass
    if hung.is_set():
        raise CheckFailed(f"it printed no handshake within {LAUNCH_SECONDS:.0f} s, with stdin held open")
    if line:
        raise CheckFailed(f"its first line of stdout was not the handshake: {line!r}")
    try:
        raise CheckFailed(f"it exited {process.wait(EXIT_SECONDS)} before printing its handshake")
    except subprocess.TimeoutExpired:
        raise CheckFailed("it closed stdout without printing its handshake") from None


async def asked(ws: Any, cmd: str, **args: Any) -> Any:
    """The result of one command, passing over the events sent meanwhile."""
    from ephymeris_sidecar.protocol import PROTOCOL_VERSION

    await ws.send(json.dumps({"v": PROTOCOL_VERSION, "id": cmd, "cmd": cmd, "args": args}))
    while True:
        message = json.loads(await ws.recv())
        if message.get("corr") != cmd:
            continue
        if not message["ok"]:
            error = message["error"]
            raise CheckFailed(f"{cmd} was refused: {error['code']}: {error['message']}")
        return message["result"]


async def recover(port: int, token: str, data_folder: Path) -> dict[str, Any]:
    """Have the sidecar recover every crashed run under `data_folder`."""
    from websockets.asyncio.client import connect
    from websockets.exceptions import WebSocketException

    async def conversation() -> dict[str, Any]:
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await asked(ws, "auth", token=token)
            created = await asked(ws, "cohorts.create", name="check", dataFolder=str(data_folder), animals=[])
            return await asked(ws, "sessions.recover", cohortId=created["cohort"]["id"])

    try:
        return await asyncio.wait_for(conversation(), REPLY_SECONDS)
    except TimeoutError:
        raise CheckFailed(f"it did not answer within {REPLY_SECONDS:.0f} s") from None
    except (OSError, WebSocketException) as error:
        raise CheckFailed(f"its WebSocket was not there to talk to: {error!r}") from error


def strobes_in(mat_path: Path) -> list[list[int]]:
    """The strobes a `.mat` holds (`DATA.md#the-mat-mirror`)."""
    import scipy.io

    if not mat_path.is_file():
        raise CheckFailed(f"it recovered the run and wrote no {mat_path.name}")
    try:
        return scipy.io.loadmat(str(mat_path))["ts_data"].astype(int).tolist()
    except Exception as error:  # noqa: BLE001 - whatever makes the file unreadable fails the check
        raise CheckFailed(f"the {mat_path.name} it wrote does not read back: {error!r}") from error


def check(command: list[str], work: Path) -> str:
    """Run the check on the sidecar `command` starts, in the empty folder
    `work`. Returns what it did, in a line; raises `CheckFailed`."""
    data_folder, log_path = work / "data", work / "sidecar.log"
    mat_path, strobes = crashed_run(data_folder)
    with log_path.open("wb") as log:
        try:
            process = subprocess.Popen(
                [*command, "--data-dir", str(work / "app")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            )
        except OSError as error:
            raise CheckFailed(f"it would not start: {error}") from error
        try:
            port, token = handshake(process)
            result = asyncio.run(recover(port, token, data_folder))
            if (result["recovered"], result["failed"]) != (1, 0):
                raise CheckFailed(f"it did not recover the crashed run: {json.dumps(result)}")
            written = strobes_in(mat_path)
            if written != strobes:
                raise CheckFailed(f"{mat_path.name} holds {written}, and the run's strobes were {strobes}")
            process.stdin.close()
            try:
                code = process.wait(EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                raise CheckFailed(f"it was still running {EXIT_SECONDS:.0f} s after stdin closed") from None
            if code != 0:
                raise CheckFailed(f"it exited {code} when stdin closed")
        except CheckFailed as failure:
            process.kill()
            process.wait()
            tail = log_path.read_text("utf-8", "replace").splitlines()[-LOG_TAIL_LINES:]
            raise CheckFailed("\n".join([str(failure), "--- the end of its log ---", *tail])) from None
        finally:
            process.kill()
            process.wait()
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
    return (
        f"{Path(command[0]).name} started, recovered a crashed run and wrote "
        f"{mat_path.name} ({len(strobes)} strobes, read back), then exited cleanly"
    )


def said(text: str, stream: Any) -> None:
    """Print `text` whatever the console's encoding: the sidecar's log is
    UTF-8, and a Windows console is not."""
    encoding = getattr(stream, "encoding", None) or "utf-8"
    print(text.encode(encoding, "backslashreplace").decode(encoding), file=stream)


def main(argv: list[str]) -> int:
    if not argv:
        said(__doc__, sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work:
        try:
            said(check(argv, Path(work)), sys.stdout)
        except CheckFailed as failure:
            said(f"the packaged sidecar failed its check: {failure}", sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
