"""Live session runner — ties `IN_SESSION` serial I/O to file writing and
telemetry (`starting-a-session.md` §7, `data-saving.md` §7).

Owns the per-box run state that the port handler doesn't: which animal is in
each box, its writer, its rolling metrics, and its `SessionAnimalRun` record.
The handler parses strobes and calls back here; here they become durable `.tsv`
lines and `session.telemetry` pushes.

Threading: `on_ready`/`on_strobe` run on the port's session thread, so writer
I/O (with its per-line `fsync`) stays off the event loop. Anything touching the
WebSocket or the state machine is scheduled back onto the loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..tasks.metrics import MetricSet
from ..tasks.profile import TaskProfile
from .models import SessionAnimalRun
from .paths import resolve_animal_files
from .writer import AnimalWriter

log = logging.getLogger(__name__)

#: The clean-end reason string, matching the real sample file exactly (§8).
CLEAN_STOP_REASON = "BF_END_SESSION received"


@dataclass
class BoxConfig:
    """Everything needed to start one box, set by `sessions.confirmMapping`."""

    box: int
    animal_id: str
    animal_name: str
    sketch_path: str
    sketch_name: str
    start_command: str
    config_metadata: dict[str, Any]
    profile: TaskProfile | None


@dataclass
class ActiveRun:
    box: int
    config: BoxConfig
    run_id: str
    started_at: str
    address: str
    session_id_label: str
    writer: AnimalWriter | None = None
    metrics: MetricSet | None = None
    end_code: int | None = None
    resolved: bool = False
    file_json: str | None = None
    seed: int | None = None
    #: Guards writer.record against finalize running concurrently.
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionRunner:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ports: Any,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        on_animal_ended: Callable[[ActiveRun, str], Awaitable[None]],
    ) -> None:
        self._loop = loop
        self._ports = ports
        self._broadcast = broadcast
        self._on_animal_ended = on_animal_ended
        # Per-session box configs, and the currently-running boxes.
        self._configs: dict[int, BoxConfig] = {}
        self._active: dict[int, ActiveRun] = {}
        self._session_folder: Path | None = None
        self._session_id_label: str = ""
        self._group_id: str = ""

    # --- configuration ----------------------------------------------------

    def configure(
        self,
        session_folder: Path,
        session_id_label: str,
        group_id: str,
        box_configs: list[BoxConfig],
    ) -> None:
        """Store the confirmed mapping for the group about to run (§3)."""
        self._session_folder = session_folder
        self._session_id_label = session_id_label
        self._group_id = group_id
        self._configs = {c.box: c for c in box_configs}

    @property
    def group_id(self) -> str:
        """The group whose mapping is currently loaded (§5.2)."""
        return self._group_id

    def snapshot(self) -> list[dict[str, Any]]:
        """What Mission Control renders: the confirmed boxes and their state.

        The runner is the authority here, not the client — reopening the
        window mid-session gets the truth rather than a stale copy.
        """
        return [
            {
                "box": box,
                "animalId": config.animal_id,
                "animalName": config.animal_name,
                "sketchName": config.sketch_name,
                "sketchPath": config.sketch_path,
                "running": box in self._active,
            }
            for box, config in sorted(self._configs.items())
        ]

    def running_boxes(self) -> list[int]:
        return sorted(self._active)

    def configured_boxes(self) -> list[int]:
        return sorted(self._configs)

    # --- start ------------------------------------------------------------

    def start_box(self, box: int) -> None:
        """Begin one box's `IN_SESSION` run (§7). Idempotent per box."""
        if box in self._active:
            return
        config = self._configs.get(box)
        if config is None or self._session_folder is None:
            raise KeyError(f"box {box} has no confirmed mapping")

        address = self._ports.resolve_address(box)
        run = ActiveRun(
            box=box,
            config=config,
            run_id=str(uuid.uuid4()),
            started_at=_now(),
            address=address,
            session_id_label=self._session_id_label,
            end_code=config.profile.end_code if config.profile else None,
        )
        self._active[box] = run

        self._ports.start_session(
            box,
            config.start_command,
            on_ready=lambda seed, b=box: self._on_ready(b, seed),
            on_strobe=lambda code, ts, b=box: self._on_strobe(b, code, ts),
        )

    # --- session-thread callbacks (off the event loop) --------------------

    def _on_ready(self, box: int, seed: int | None) -> None:
        """Handshake resolved — open the file and write its header (§7.1)."""
        run = self._active.get(box)
        if run is None or self._session_folder is None:
            return
        run.seed = seed

        when = datetime.now()
        files = resolve_animal_files(
            self._session_folder,
            run.config.animal_name,
            *_split_label(run.session_id_label),
            when,
        )
        run.file_json = str(files.json)

        # §5 core fields, then flat task-profile config, then optional trial_seed.
        core = {
            "rat": run.config.animal_name,
            "serial_port": run.address,
            "session_id": run.session_id_label,
            "sketch": run.config.sketch_name,
        }
        config_meta = dict(run.config.config_metadata)
        if seed is not None:
            config_meta["trial_seed"] = seed  # §6.4 recognized wire convention

        writer = AnimalWriter(files.tsv, files.json, files.mat, core, config_meta)
        try:
            writer.open_files()
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the thread
            log.error("box %d: couldn't open session files: %s", box, exc)
            self._schedule(self._fail_run(box, "sidecar error"))
            return
        run.writer = writer
        run.metrics = MetricSet(run.config.profile)

    def _on_strobe(self, box: int, code: int, ts: int) -> None:
        run = self._active.get(box)
        if run is None or run.writer is None or run.resolved:
            return
        with run.lock:
            if run.resolved:
                return
            try:
                run.writer.record(code, ts)
            except Exception as exc:  # noqa: BLE001 - disk full / permission
                log.error("box %d: session write failed: %s", box, exc)
                self._schedule(self._emit_write_error(box, str(exc)))
                return
            values = run.metrics.offer(code) if run.metrics else []

        if values:
            payload = {
                "box": box,
                "animalId": run.config.animal_id,
                "metrics": [v.to_json() for v in values],
            }
            self._schedule(self._push_telemetry(payload))

        if run.end_code is not None and code == run.end_code:
            # Clean firmware-reported end (§7 exit, §8).
            self._schedule(self.finalize_box(box, CLEAN_STOP_REASON, clean=True))

    # --- stop / end -------------------------------------------------------

    def stop_box(self, box: int) -> None:
        """Send `STOP`; the board's own end strobe ends the run (§5.3)."""
        if box in self._active:
            self._ports.stop_session(box)

    async def finalize_box(self, box: int, reason: str, clean: bool) -> None:
        """Finalize one animal's run and free the box.

        `clean` transitions `IN_SESSION → IDLE`; a board drop is already in
        `ERROR` (via the handler's `force_error`), so we only finalize the file.
        """
        run = self._active.get(box)
        if run is None or run.resolved:
            return
        run.resolved = True
        self._active.pop(box, None)

        if run.writer is not None:
            await asyncio.to_thread(run.writer.finalize, reason)
        if clean:
            try:
                await asyncio.to_thread(self._ports.end_session, box, reason)
            except Exception as exc:  # noqa: BLE001 - already torn down is fine
                log.debug("box %d: end_session during finalize: %s", box, exc)

        await self._on_animal_ended(run, reason)

    def board_dropped(self, box: int) -> None:
        """Called when a box drops to ERROR mid-session (hook from app §7/§10)."""
        if box in self._active:
            self._schedule(self.finalize_box(box, "board disconnected", clean=False))

    async def end_all(self, reason: str = "operator stop") -> None:
        for box in list(self._active):
            self.stop_box(box)
        # Give boards a moment to honour STOP at their next trial boundary; then
        # force-finalize any that didn't self-end.
        await asyncio.sleep(0.1)
        for box in list(self._active):
            await self.finalize_box(box, reason, clean=True)

    # --- internals --------------------------------------------------------

    async def _push_telemetry(self, payload: dict[str, Any]) -> None:
        from ..protocol import Evt, event

        await self._broadcast(event(Evt.SESSION_TELEMETRY, payload))

    async def _emit_write_error(self, box: int, message: str) -> None:
        from ..protocol import ErrCode, Evt, event

        await self._broadcast(
            event(
                Evt.SIDECAR_ERROR,
                {
                    "code": ErrCode.INTERNAL,
                    "message": f"Box {box}: session write failed — {message}",
                    "detail": {"box": box},
                },
            )
        )

    async def _fail_run(self, box: int, reason: str) -> None:
        await self.finalize_box(box, reason, clean=True)

    def _schedule(self, coro: Awaitable[None]) -> None:
        """Hand a coroutine to the event loop from a worker thread."""
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split_label(label: str) -> tuple[str, str]:
    """`"<prefix>_<sessionNumber>"` → (prefix, sessionNumber).

    Split on the last underscore, since a prefix may itself contain one.
    """
    prefix, _, number = label.rpartition("_")
    return (prefix, number) if prefix else (label, "")
