"""`arduino-cli` subprocess backend.

Uses `board list --format json`. One call covers all six ports, so the 1–2s
presence poll costs roughly one process spawn per second rather than six —
which is what makes deferring the gRPC daemon tolerable
(`hardware-interaction.md` §2).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from .tool import BoardTool, DetectedBoard, FlashFailed, ProgressLine

log = logging.getLogger(__name__)

DEFAULT_BINARY = "arduino-cli"
#: Set by the packaged Tauri shell: the bundled arduino-cli binary, and the
#: read-only `arduino:avr` data seed shipped in the app's resources. Absent in
#: development, where PATH resolution keeps working exactly as before.
BUNDLED_CLI_ENV = "EPHYMERIS_BUNDLED_ARDUINO_CLI"
BUNDLED_SEED_ENV = "EPHYMERIS_BUNDLED_ARDUINO_DATA_SEED"
#: Written into the data-dir copy after a complete seed copy. A crash mid-copy
#: leaves the marker absent, so the next launch re-copies instead of running a
#: half-written toolchain.
SEED_MARKER = ".seed-complete"

LIST_TIMEOUT_S = 10.0
#: First compile on a machine also builds the core; generous on purpose.
COMPILE_TIMEOUT_S = 300.0
UPLOAD_TIMEOUT_S = 120.0


def _default_binary() -> str:
    """The bundled binary when the shell shipped one, else PATH resolution."""
    return os.environ.get(BUNDLED_CLI_ENV) or DEFAULT_BINARY


class ArduinoCliError(Exception):
    pass


class ArduinoCliTool(BoardTool):
    def __init__(self, binary: str | None = None, app_data_dir: Path | None = None) -> None:
        self._binary = binary or _default_binary()
        #: Where the writable copy of the bundled data seed lives (beside
        #: ephymeris.db). None in tests and bare construction — then no seed
        #: handling happens at all.
        self._app_data_dir = app_data_dir
        self._env: dict[str, str] | None = None
        self._env_lock = asyncio.Lock()

    def set_binary(self, binary: str | None) -> None:
        """Apply the `arduino-cli` path override from Settings.

        Settings wins over the bundled binary on purpose: the override exists
        precisely for "use this specific install instead of what shipped".
        """
        self._binary = binary or _default_binary()

    @property
    def binary(self) -> str:
        return self._binary

    def is_available(self) -> bool:
        return shutil.which(self._binary) is not None or "/" in self._binary

    async def invocation_env(self) -> dict[str, str] | None:
        """Environment for arduino-cli subprocesses, seeding data on first use.

        The bundled seed ships inside the install directory, which may be
        read-only and is replaced wholesale on update — but arduino-cli needs
        a writable data dir (it maintains an inventory there and unpacks tool
        downloads). So the seed is copied once into the app data dir and every
        invocation points ARDUINO_DIRECTORIES_* at the copy. Without a seed
        (development), returns None: the subprocess inherits our environment
        untouched and arduino-cli uses its own default directories.
        """
        seed = os.environ.get(BUNDLED_SEED_ENV)
        if not seed or self._app_data_dir is None:
            return None

        async with self._env_lock:
            if self._env is not None:
                return self._env

            target = self._app_data_dir / "arduino-data"
            marker = target / SEED_MARKER
            if not marker.exists():
                log.info("copying bundled arduino data seed to %s", target)
                # Worker thread: the copy is a few hundred MB on first launch,
                # and blocking the loop would stall the WebSocket with it.
                await asyncio.to_thread(
                    shutil.copytree, seed, target, dirs_exist_ok=True
                )
                marker.touch()
                log.info("arduino data seed ready")

            self._env = {
                **os.environ,
                "ARDUINO_DIRECTORIES_DATA": str(target),
                "ARDUINO_DIRECTORIES_DOWNLOADS": str(target / "staging"),
            }
            return self._env

    async def _run(self, *args: str, timeout: float) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            self._binary,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=await self.invocation_env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise ArduinoCliError(f"`{self._binary} {' '.join(args)}` timed out") from None

        if proc.returncode != 0:
            raise ArduinoCliError(
                stderr.decode(errors="replace").strip()
                or f"`{self._binary}` exited {proc.returncode}"
            )

        try:
            return json.loads(stdout.decode(errors="replace") or "{}")
        except ValueError as exc:
            raise ArduinoCliError(f"couldn't parse arduino-cli output: {exc}") from exc

    async def list_boards(self) -> list[DetectedBoard]:
        payload = await self._run("board", "list", "--format", "json", timeout=LIST_TIMEOUT_S)
        return _parse_board_list(payload)

    # --- flashing ---------------------------------------------------------

    async def compile(
        self,
        sketch_dir: str,
        fqbn: str,
        libraries_path: str | None,
        on_line: ProgressLine,
    ) -> None:
        args = ["compile", "--fqbn", fqbn, "--format", "json"]
        if libraries_path:
            # One shared libraries folder for every sketch (arduino-directory.md §4).
            args += ["--libraries", libraries_path]
        args.append(sketch_dir)

        rc, stdout = await self._run_streaming(args, COMPILE_TIMEOUT_S, "compile", on_line)
        payload = _try_json(stdout)

        # `--format json` buffers the compiler's output into the final object,
        # so replay it as progress lines once it lands. (True line-by-line
        # streaming is what the gRPC daemon migration buys later.)
        for line in str(payload.get("compiler_out", "")).splitlines():
            on_line("stdout", line)
        for line in str(payload.get("compiler_err", "")).splitlines():
            on_line("stderr", line)

        if rc != 0 or payload.get("success") is False:
            raise FlashFailed(
                "compile",
                _failure_message("compile", payload, rc),
                detail=str(payload.get("compiler_err", ""))[-4000:] or None,
            )

    async def upload(
        self,
        sketch_dir: str,
        fqbn: str,
        address: str,
        on_line: ProgressLine,
    ) -> None:
        args = ["upload", "-p", address, "--fqbn", fqbn, "--format", "json", sketch_dir]
        rc, stdout = await self._run_streaming(args, UPLOAD_TIMEOUT_S, "upload", on_line)
        payload = _try_json(stdout)

        for line in str(payload.get("stdout", "")).splitlines():
            on_line("stdout", line)
        for line in str(payload.get("stderr", "")).splitlines():
            on_line("stderr", line)

        if rc != 0:
            raise FlashFailed(
                "upload",
                _failure_message("upload", payload, rc),
                detail=str(payload.get("stderr", ""))[-4000:] or None,
            )

    async def _run_streaming(
        self,
        args: list[str],
        timeout: float,
        phase: str,
        on_line: ProgressLine,
    ) -> tuple[int, str]:
        """Run arduino-cli, streaming stderr lines live and collecting stdout.

        stdout carries the `--format json` result and is parsed at the end;
        stderr is whatever the tool says while working, forwarded as it
        arrives so the frontend shows progress, not a spinner-until-done
        (`hardware-interaction.md` §4).
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=await self.invocation_env(),
            )
        except OSError as exc:
            raise FlashFailed(phase, f"couldn't run `{self._binary}`: {exc}") from exc

        stdout_chunks: list[bytes] = []

        async def read_stdout() -> None:
            assert proc.stdout is not None
            while chunk := await proc.stdout.read(65536):
                stdout_chunks.append(chunk)

        async def read_stderr() -> None:
            assert proc.stderr is not None
            while line := await proc.stderr.readline():
                text = line.decode(errors="replace").rstrip()
                if text:
                    on_line("stderr", text)

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr(), proc.wait()),
                timeout=timeout,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise FlashFailed(phase, f"{phase} timed out after {timeout:.0f}s") from None

        return proc.returncode or 0, b"".join(stdout_chunks).decode(errors="replace")


def _try_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text or "{}")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _failure_message(phase: str, payload: dict[str, Any], rc: int) -> str:
    """Pull the line that actually explains the failure out of the tool output.

    A compile failure's useful text is the `error:` line in `compiler_err`;
    everything else ("exit status 1") is noise the user shouldn't have to
    read a log to get past.
    """
    blob = str(payload.get("compiler_err") or payload.get("stderr") or "")
    lines = [line.strip() for line in blob.splitlines() if line.strip()]
    for line in lines:
        if "error:" in line.lower():
            return line
    if lines:
        return lines[-1]
    if isinstance(payload.get("error"), str) and payload["error"]:
        return payload["error"]
    return f"{phase} failed (arduino-cli exited {rc})"


def _parse_board_list(payload: Any) -> list[DetectedBoard]:
    """Extract real boards from `board list` output.

    The raw list includes every serial port the OS knows about — Bluetooth
    endpoints, debug consoles — so entries are filtered on the presence of USB
    VID/PID properties and a hardware id. Anything without a stable hardware id
    is unbindable by definition, since box bindings key on exactly that.

    Deliberately *not* filtered against an allow-list of Arduino vendor IDs: a
    clone Mega with a CH340 or FTDI bridge is still a board the lab may be
    running, and silently hiding it would be worse than showing it with no FQBN.
    """
    boards: list[DetectedBoard] = []
    detected = payload.get("detected_ports") if isinstance(payload, dict) else None
    if not isinstance(detected, list):
        return boards

    for entry in detected:
        if not isinstance(entry, dict):
            continue
        port = entry.get("port")
        if not isinstance(port, dict) or port.get("protocol") != "serial":
            continue

        properties = port.get("properties")
        properties = properties if isinstance(properties, dict) else {}

        hardware_id = port.get("hardware_id") or properties.get("serialNumber")
        if not isinstance(hardware_id, str) or not hardware_id.strip():
            continue
        if not properties.get("vid"):
            continue

        address = port.get("address")
        if not isinstance(address, str) or not address:
            continue

        matching = entry.get("matching_boards")
        fqbn = None
        label = None
        if isinstance(matching, list) and matching and isinstance(matching[0], dict):
            fqbn = matching[0].get("fqbn")
            label = matching[0].get("name")

        boards.append(
            DetectedBoard(
                hardware_id=hardware_id,
                address=address,
                fqbn=fqbn if isinstance(fqbn, str) else None,
                label=label if isinstance(label, str) else None,
            )
        )

    return boards
