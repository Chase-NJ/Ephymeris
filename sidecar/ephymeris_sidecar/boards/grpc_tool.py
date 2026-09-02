"""`arduino-cli` gRPC daemon backend — `README.md` §4.1.

One long-lived `arduino-cli daemon` child replaces the per-call subprocess:
board presence stops paying a process spawn per poll, and compile/upload
output arrives as a **live stream** (`out_stream`/`err_stream` chunks) rather
than buffered into the final `--format json` object and replayed after the
fact — the two things the migration was committed to buy.

The subprocess backend is not deleted; it is this backend's **fallback**.
That is what squares the migration with the dependency policy
(`README.md`): `grpcio`/`protobuf` are now runtime dependencies, but a lab
machine where they failed to install — or where the daemon won't start —
degrades to the proven `--format json` path instead of losing flashing.
Every fallback is logged loudly; it is a degradation, not a mode.

Client stubs are generated from vendored protos (`scripts/gen_grpc.py`) and
committed, so codegen never runs at install time. The vendored tag must match
the bundled/lab `arduino-cli` — the daemon and its client share a schema.

Lifecycle: the daemon is spawned lazily on first use, stopped by `close()`
(wired into `Application.stop()`), and respawned on the next call if it died
or the Settings binary override changed. Orphan protection comes free and is
load-bearing to keep: the daemon watches **its own stdin for EOF** — the very
mechanism our sidecar uses against the shell — and exits when it closes, so
the spawn *must* hold a stdin pipe open. `stdin=DEVNULL` is an instant EOF
and the daemon exits immediately, silently, with code 0; that is not a
hypothetical, it is how this backend failed on first contact. The pipe also
means a sidecar that dies hard takes the daemon with it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import grpc

from . import rpc  # noqa: F401  — puts the vendored stub tree on sys.path
from cc.arduino.cli.commands.v1 import board_pb2, commands_pb2, commands_pb2_grpc, compile_pb2, port_pb2, upload_pb2

from .cli_tool import COMPILE_TIMEOUT_S, LIST_TIMEOUT_S, UPLOAD_TIMEOUT_S, ArduinoCliTool
from .tool import BoardTool, DetectedBoard, FlashFailed, ProgressLine

log = logging.getLogger(__name__)

#: How long the daemon gets to print its listen address.
SPAWN_TIMEOUT_S = 20.0
#: First Init on a machine loads the platform index; generous on purpose.
INIT_TIMEOUT_S = 120.0
#: How long BoardList lets discovery settle, in ms (the request's own field —
#: the discovery runs inside the daemon, so this costs no process spawn).
DISCOVERY_SETTLE_MS = 1000

#: Text-format fallback for the daemon's banner, in case a config file forces
#: text output: "Daemon is now listening on 127.0.0.1:50051".
_TEXT_BANNER = re.compile(r"listening on\s+([\d.]+):(\d+)")


class DaemonUnavailable(Exception):
    """The daemon couldn't be spawned or handshaken — use the fallback."""


@dataclass
class _Daemon:
    """One running daemon: its process, channel, and initialized instance."""

    proc: asyncio.subprocess.Process
    channel: grpc.aio.Channel
    stub: commands_pb2_grpc.ArduinoCoreServiceStub
    instance: Any
    binary: str
    stderr_task: asyncio.Task


class GrpcBoardTool(BoardTool):
    """BoardTool over the arduino-cli gRPC daemon, subprocess fallback inside."""

    def __init__(self, binary: str | None = None, app_data_dir: Path | None = None) -> None:
        # The fallback also owns the pieces both backends need: binary
        # resolution (bundled vs PATH vs Settings override) and the packaged
        # data-seed environment. One owner, so the two paths can't drift.
        self._fallback = ArduinoCliTool(binary, app_data_dir=app_data_dir)
        self._daemon: _Daemon | None = None
        self._lock = asyncio.Lock()

    # --- plumbing shared with the subprocess tool -------------------------

    @property
    def binary(self) -> str:
        return self._fallback.binary

    def set_binary(self, binary: str | None) -> None:
        """Apply the Settings override. A running daemon for the old binary is
        left to be noticed on the next call — `_ensure` compares binaries and
        respawns, so the swap needs no async work here."""
        self._fallback.set_binary(binary)

    def is_available(self) -> bool:
        return self._fallback.is_available()

    async def close(self) -> None:
        async with self._lock:
            await self._shutdown_daemon()

    # --- BoardTool --------------------------------------------------------

    async def list_boards(self) -> list[DetectedBoard]:
        try:
            daemon = await self._acquire()
        except DaemonUnavailable as exc:
            log.warning("gRPC daemon unavailable (%s); polling via subprocess", exc)
            return await self._fallback.list_boards()
        try:
            response = await daemon.stub.BoardList(
                board_pb2.BoardListRequest(
                    instance=daemon.instance, timeout=DISCOVERY_SETTLE_MS
                ),
                timeout=LIST_TIMEOUT_S,
            )
        except grpc.RpcError as exc:
            # The poll reruns in 1.5 s anyway: drop the daemon so the next
            # tick respawns it, and serve this tick through the fallback.
            log.warning("BoardList failed (%s); dropping the daemon", _rpc_text(exc))
            await self._invalidate()
            return await self._fallback.list_boards()
        return _boards_from_response(response)

    async def compile(
        self,
        sketch_dir: str,
        fqbn: str,
        libraries_path: str | None,
        on_line: ProgressLine,
    ) -> None:
        try:
            daemon = await self._acquire()
        except DaemonUnavailable as exc:
            log.warning("gRPC daemon unavailable (%s); compiling via subprocess", exc)
            return await self._fallback.compile(sketch_dir, fqbn, libraries_path, on_line)

        request = compile_pb2.CompileRequest(
            instance=daemon.instance,
            fqbn=fqbn,
            sketch_path=sketch_dir,
            # One shared libraries folder for every sketch (tasks.md §2.3).
            libraries=[libraries_path] if libraries_path else [],
        )
        # Echoed from the request itself, and deliberately NOT dressed up as a
        # shell command: no `arduino-cli compile` process runs on this path, and
        # a console line implying one sent a real investigation down the wrong
        # road once already (see `cli_tool._command_echo`).
        on_line(
            "stdout",
            _daemon_echo(
                "Compile",
                fqbn=request.fqbn,
                sketch=request.sketch_path,
                libraries=list(request.libraries),
            ),
        )
        err_lines: list[str] = []
        splitter = _LineSplitter(_collecting(on_line, err_lines))
        try:
            async for response in daemon.stub.Compile(request, timeout=COMPILE_TIMEOUT_S):
                which = response.WhichOneof("message")
                if which == "out_stream":
                    splitter.feed("stdout", response.out_stream)
                elif which == "err_stream":
                    splitter.feed("stderr", response.err_stream)
                elif which == "progress":
                    _emit_progress(on_line, response.progress)
            splitter.flush()
        except grpc.RpcError as exc:
            splitter.flush()
            if exc.code() == grpc.StatusCode.UNAVAILABLE:
                # The daemon died under us. Compile is idempotent, so rerun it
                # whole on the proven path rather than failing the flash.
                log.warning("daemon lost mid-compile; retrying via subprocess")
                await self._invalidate()
                return await self._fallback.compile(sketch_dir, fqbn, libraries_path, on_line)
            if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise FlashFailed(
                    "compile", f"compile timed out after {COMPILE_TIMEOUT_S:.0f}s"
                ) from None
            raise FlashFailed(
                "compile",
                _failure_message("compile", err_lines, exc),
                detail=_tail(err_lines),
            ) from exc

    async def upload(
        self,
        sketch_dir: str,
        fqbn: str,
        address: str,
        on_line: ProgressLine,
    ) -> None:
        try:
            daemon = await self._acquire()
        except DaemonUnavailable as exc:
            log.warning("gRPC daemon unavailable (%s); uploading via subprocess", exc)
            return await self._fallback.upload(sketch_dir, fqbn, address, on_line)

        request = upload_pb2.UploadRequest(
            instance=daemon.instance,
            fqbn=fqbn,
            sketch_path=sketch_dir,
            port=port_pb2.Port(address=address, protocol="serial"),
        )
        on_line(
            "stdout",
            _daemon_echo(
                "Upload",
                fqbn=request.fqbn,
                sketch=request.sketch_path,
                port=request.port.address,
            ),
        )
        err_lines: list[str] = []
        splitter = _LineSplitter(_collecting(on_line, err_lines))
        try:
            async for response in daemon.stub.Upload(request, timeout=UPLOAD_TIMEOUT_S):
                which = response.WhichOneof("message")
                if which == "out_stream":
                    splitter.feed("stdout", response.out_stream)
                elif which == "err_stream":
                    splitter.feed("stderr", response.err_stream)
            splitter.flush()
        except grpc.RpcError as exc:
            splitter.flush()
            if exc.code() == grpc.StatusCode.UNAVAILABLE:
                # An interrupted upload leaves the board needing a reflash
                # either way, so rerunning whole on the fallback is safe.
                log.warning("daemon lost mid-upload; retrying via subprocess")
                await self._invalidate()
                return await self._fallback.upload(sketch_dir, fqbn, address, on_line)
            if exc.code() == grpc.StatusCode.DEADLINE_EXCEEDED:
                raise FlashFailed(
                    "upload", f"upload timed out after {UPLOAD_TIMEOUT_S:.0f}s"
                ) from None
            raise FlashFailed(
                "upload",
                _failure_message("upload", err_lines, exc),
                detail=_tail(err_lines),
            ) from exc

    # --- daemon lifecycle -------------------------------------------------

    async def _acquire(self) -> _Daemon:
        """The live daemon, (re)spawned as needed. Raises DaemonUnavailable."""
        async with self._lock:
            daemon = self._daemon
            if (
                daemon is not None
                and daemon.proc.returncode is None
                and daemon.binary == self._fallback.binary
            ):
                return daemon
            await self._shutdown_daemon()
            self._daemon = await self._spawn()
            return self._daemon

    async def _invalidate(self) -> None:
        async with self._lock:
            await self._shutdown_daemon()

    async def _spawn(self) -> _Daemon:
        binary = self._fallback.binary
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "daemon",
                "--port", "0",
                "--format", "json",
                # A held-open pipe, never DEVNULL: the daemon exits on stdin
                # EOF (its parent-death watch, same as our own). DEVNULL is an
                # instant EOF — the daemon dies silently with code 0 before
                # ever listening. Keeping the pipe is also what guarantees the
                # daemon cannot outlive a hard-killed sidecar.
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=await self._fallback.invocation_env(),
            )
        except OSError as exc:
            raise DaemonUnavailable(f"couldn't run `{binary} daemon`: {exc}") from exc

        try:
            assert proc.stdout is not None
            address = await _read_banner(proc.stdout, SPAWN_TIMEOUT_S)
            if address is None:
                raise DaemonUnavailable("daemon printed no listen address")

            channel = grpc.aio.insecure_channel(address)
            stub = commands_pb2_grpc.ArduinoCoreServiceStub(channel)
            created = await stub.Create(commands_pb2.CreateRequest(), timeout=LIST_TIMEOUT_S)
            instance = created.instance
            # Init loads platforms and libraries; its errors (a stale index,
            # an unreachable network) are warnings, not failures — board
            # enumeration and avr compiles work from what is installed.
            async for response in stub.Init(
                commands_pb2.InitRequest(instance=instance), timeout=INIT_TIMEOUT_S
            ):
                if response.WhichOneof("message") == "error":
                    log.warning("daemon init: %s", response.error.message)
        except DaemonUnavailable:
            await _kill(proc)
            raise
        except (TimeoutError, grpc.RpcError, OSError) as exc:
            await _kill(proc)
            raise DaemonUnavailable(_rpc_text(exc)) from exc

        stderr_task = asyncio.ensure_future(_drain_stderr(proc))
        log.info("arduino-cli daemon up at %s (binary %s)", address, binary)
        return _Daemon(
            proc=proc,
            channel=channel,
            stub=stub,
            instance=instance,
            binary=binary,
            stderr_task=stderr_task,
        )

    async def _shutdown_daemon(self) -> None:
        daemon, self._daemon = self._daemon, None
        if daemon is None:
            return
        daemon.stderr_task.cancel()
        try:
            await daemon.channel.close()
        except Exception:  # noqa: BLE001 - already-broken channel is fine
            pass
        await _kill(daemon.proc)
        log.info("arduino-cli daemon stopped")


# --- helpers ----------------------------------------------------------------


async def _read_banner(stdout: asyncio.StreamReader, timeout: float) -> str | None:
    """Accumulate stdout until the listen address appears, or EOF/timeout.

    The `--format json` banner is **pretty-printed across several lines**
    (`{\\n  "IP": ...`), so a single `readline` sees only `{` — lines are
    accumulated and re-parsed until the object completes.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    buffer = ""
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=remaining)
        except TimeoutError:
            return None
        if not line:
            return None  # EOF — the daemon exited before listening
        buffer += line.decode(errors="replace")
        address = parse_daemon_address(buffer)
        if address is not None:
            return address


def parse_daemon_address(text: str) -> str | None:
    """The daemon's banner → `host:port`, either output format.

    `--format json` prints `{"IP": "127.0.0.1", "Port": "50051"}` (pretty,
    multi-line); a config file forcing text prints
    `Daemon is now listening on 127.0.0.1:50051`. `None` means "not (yet) a
    complete banner" — the reader keeps accumulating.
    """
    text = text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        ip, port = payload.get("IP"), payload.get("Port")
        if isinstance(ip, str) and ip and str(port or "").isdigit():
            return f"{ip}:{port}"
        return None
    match = _TEXT_BANNER.search(text)
    return f"{match.group(1)}:{match.group(2)}" if match else None


def _boards_from_response(response: Any) -> list[DetectedBoard]:
    """`BoardListResponse` → boards, same filters as the subprocess parser.

    Serial protocol only, a non-blank hardware id (falling back to the
    `serialNumber` property), a truthy vendor id, a non-empty address — and
    deliberately no allow-list of Arduino vendor ids, so CH340/FTDI clones
    still appear (`settings.md` §7).
    """
    boards: list[DetectedBoard] = []
    for detected in response.ports:
        port = detected.port
        if port.protocol != "serial":
            continue
        properties = dict(port.properties)
        hardware_id = port.hardware_id or properties.get("serialNumber", "")
        if not hardware_id.strip():
            continue
        if not properties.get("vid"):
            continue
        if not port.address:
            continue
        fqbn = None
        label = None
        if detected.matching_boards:
            first = detected.matching_boards[0]
            fqbn = first.fqbn or None
            label = first.name or None
        boards.append(
            DetectedBoard(
                hardware_id=hardware_id,
                address=port.address,
                fqbn=fqbn,
                label=label,
            )
        )
    return boards


class _LineSplitter:
    """Byte chunks → whole text lines, per stream.

    The daemon streams `out_stream`/`err_stream` as arbitrary byte chunks —
    a line can arrive split across two chunks, or many lines in one — so each
    stream keeps a remainder buffer and only complete lines are emitted.
    `flush` releases a final unterminated line at end of stream.
    """

    def __init__(self, on_line: ProgressLine) -> None:
        self._on_line = on_line
        self._buffers: dict[str, bytes] = {"stdout": b"", "stderr": b""}

    def feed(self, stream: str, chunk: bytes) -> None:
        *lines, remainder = (self._buffers[stream] + chunk).split(b"\n")
        self._buffers[stream] = remainder
        for raw in lines:
            self._emit(stream, raw)

    def flush(self) -> None:
        for stream, remainder in self._buffers.items():
            if remainder:
                self._emit(stream, remainder)
        self._buffers = {"stdout": b"", "stderr": b""}

    def _emit(self, stream: str, raw: bytes) -> None:
        text = raw.decode(errors="replace").rstrip("\r")
        if text.strip():
            self._on_line(stream, text)


def _daemon_echo(call: str, **fields: object) -> str:
    """One line naming the RPC and the fields actually sent.

    Not a `$ arduino-cli …` line, on purpose: nothing is spawned here, and a
    console that claims otherwise is a lie that costs someone an afternoon —
    the manager's old hand-written echo did exactly that, printing a compile
    with no `--libraries` while the daemon was being handed one
    (`cli_tool._command_echo`). An empty list prints as `[]` rather than being
    dropped, because "no libraries were sent" is the interesting case.
    """
    def render(value: object) -> str:
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(render(item) for item in value) + "]"
        # Plainly, never `repr`: a Windows path through `repr` comes back with
        # every separator doubled, which is unreadable and unpasteable — and
        # this line exists to be pasted.
        return str(value)

    rendered = ", ".join(f"{key}={render(value)}" for key, value in fields.items())
    return f"arduino-cli daemon: {call}({rendered})"


def _collecting(on_line: ProgressLine, err_lines: list[str]) -> ProgressLine:
    """Wrap `on_line` so stderr lines are also kept for the failure message."""

    def wrapped(stream: str, text: str) -> None:
        if stream == "stderr":
            err_lines.append(text)
        on_line(stream, text)

    return wrapped


def _emit_progress(on_line: ProgressLine, progress: Any) -> None:
    """A TaskProgress phase line ("Compiling sketch...") as ordinary output."""
    text = (progress.message or progress.name).strip()
    if text:
        on_line("stdout", text)


def _failure_message(phase: str, err_lines: list[str], exc: grpc.RpcError) -> str:
    """The line that explains the failure — same rule as the subprocess path:
    the `error:` line if the compiler printed one, else the last thing it
    said, else whatever the RPC status carries."""
    for line in err_lines:
        if "error:" in line.lower():
            return line.strip()
    if err_lines:
        return err_lines[-1].strip()
    return _rpc_text(exc) or f"{phase} failed"


def _tail(err_lines: list[str]) -> str | None:
    blob = "\n".join(err_lines)
    return blob[-4000:] or None


def _rpc_text(exc: BaseException) -> str:
    details = getattr(exc, "details", None)
    text = details() if callable(details) else None
    return text or str(exc) or type(exc).__name__


async def _drain_stderr(proc: asyncio.subprocess.Process) -> None:
    """Keep the daemon's stderr pipe from filling; surface it at debug."""
    assert proc.stderr is not None
    try:
        while line := await proc.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            if text:
                log.debug("daemon: %s", text)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - a dying pipe ends the drain, that's all
        pass


async def _kill(proc: asyncio.subprocess.Process) -> None:
    """Stop the daemon: stdin EOF first (its own clean-exit path), then force."""
    if proc.returncode is not None:
        return
    if proc.stdin is not None:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001 - a broken pipe is already closed
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
            return
        except TimeoutError:
            pass
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()
