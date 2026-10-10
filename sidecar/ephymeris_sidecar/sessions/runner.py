"""Live session runner — ties `IN_SESSION` serial I/O to file writing and
telemetry (`ARCHITECTURE.md#entering-in_session`, `DATA.md#crash-safety`).

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
from ..tasks.seed import new_trial_seed
from ..tasks.start_command import with_trial_seed
from .models import SessionAnimalRun
from .paths import AnimalFilePaths, resolve_animal_files
from .writer import AnimalWriter

log = logging.getLogger(__name__)

#: The clean-end reason string, matching the real sample file exactly (`ARCHITECTURE.md#stop-reasons`).
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
    files: AnimalFilePaths | None = None
    #: What the board echoed back on its `SEED` line — the seed the firmware
    #: actually ran on, whatever we asked for. `None` when it echoed nothing.
    seed: int | None = None
    #: What this app drew and put on the `START` line (`tasks/seed.py`). Always
    #: present, and recorded separately from `seed` so the two can be compared:
    #: firmware predating the `SEED=` convention seeds itself and echoes a
    #: different number, and that difference is the only signal a box is still
    #: carrying an old sketch.
    host_seed: int | None = None
    #: The scheduled auto-STOP when the session has a time limit (`ARCHITECTURE.md#configuration`);
    #: cancelled on finalize so a box stopped early never gets a ghost STOP.
    deadline: asyncio.TimerHandle | None = None
    #: Guards writer.record against finalize running concurrently.
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def file_json(self) -> str | None:
        """The finalized `.json` path recorded on `SessionAnimalRun` (`DATA.md#run-records`)."""
        return str(self.files.json) if self.files is not None else None


class SessionRunner:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ports: Any,
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        on_animal_ended: Callable[[ActiveRun, str], Awaitable[None]],
        backup: Any = None,
    ) -> None:
        self._loop = loop
        self._ports = ports
        self._broadcast = broadcast
        self._on_animal_ended = on_animal_ended
        # Optional so the runner stays testable without a mirror behind it.
        # Nothing here ever waits on it — see `backup/manager.py`.
        self._backup = backup
        # Per-session box configs, and the currently-running boxes.
        self._configs: dict[int, BoxConfig] = {}
        self._active: dict[int, ActiveRun] = {}
        # Boxes whose run in this group has finished and not been restarted —
        # the `ended` a reloaded client reads, since `session.animalEnded` is
        # never replayed (`ARCHITECTURE.md#replay-on-connect`).
        self._ended: set[int] = set()
        # In-flight fire-and-forget finalizations (end strobes, board drops).
        # `end_all` drains this so a caller that clears session state right
        # after it returns can't strand a finalization mid-write.
        self._finalizations: set[asyncio.Task] = set()
        self._session_folder: Path | None = None
        self._session_id_label: str = ""
        self._group_id: str = ""
        self._duration_s: float | None = None
        # The recording subsystem's three taps (`intan/service.py`), all
        # optional and all called ON THE SESSION THREAD, so whatever is hung
        # here must be thread-safe and must not block: it sits between a strobe
        # arriving and that strobe being fsync'd. None of them can fail a run
        # -- each call site swallows, because a behavior session never pays for
        # the recording's problems.
        #   recording_fields(box) -> flat `intan_*` fields for the document
        #   on_box_started(box, animal)
        #   on_strobe_tap(box, code, ms)
        self.recording_fields: Callable[[int], dict[str, Any]] | None = None
        self.on_box_started: Callable[[int, str], None] | None = None
        self.on_strobe_tap: Callable[[int, int, int], None] | None = None

    # --- configuration ----------------------------------------------------

    def configure(
        self,
        session_folder: Path,
        session_id_label: str,
        group_id: str,
        box_configs: list[BoxConfig],
        duration_s: float | None = None,
    ) -> None:
        """Store the confirmed mapping for the group about to run
        (`ARCHITECTURE.md#mapping-and-the-placement-walk`).

        `duration_s` is the optional per-box time limit: each box gets an
        auto-STOP scheduled from *its own* start, not from Start All — boxes
        are started individually, and each animal's run should be the same
        length.
        """
        self._session_folder = session_folder
        self._session_id_label = session_id_label
        self._group_id = group_id
        self._configs = {c.box: c for c in box_configs}
        self._ended = set()
        self._duration_s = duration_s

    def clear(self) -> None:
        """Forget a confirmed mapping that never ran (`sessions.abandon`)."""
        if self._active:
            raise RuntimeError("cannot clear a runner with active runs")
        self._configs = {}
        self._ended = set()
        self._session_folder = None
        self._session_id_label = ""
        self._group_id = ""
        self._duration_s = None

    @property
    def group_id(self) -> str:
        """The group whose mapping is currently loaded (`ARCHITECTURE.md#group-step`)."""
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
                # What lets a reloaded Mission Control resume its elapsed clocks.
                "startedAt": run.started_at if (run := self._active.get(box)) else None,
                "ended": box in self._ended,
            }
            for box, config in sorted(self._configs.items())
        ]

    def running_boxes(self) -> list[int]:
        return sorted(self._active)

    def configured_boxes(self) -> list[int]:
        return sorted(self._configs)

    def box_configs(self) -> list[BoxConfig]:
        return [self._configs[box] for box in sorted(self._configs)]

    # --- start ------------------------------------------------------------

    def start_box(self, box: int) -> None:
        """Begin one box's `IN_SESSION` run (`ARCHITECTURE.md#entering-in_session`). Idempotent per box."""
        if box in self._active:
            return
        config = self._configs.get(box)
        if config is None or self._session_folder is None:
            raise KeyError(f"box {box} has no confirmed mapping")

        address = self._ports.resolve_address(box)
        # Drawn *here*, on the click, and never at `configure` time: a seed
        # settled with the mapping would be shared by every box in the group and
        # would survive a Start → Stop → Start, which is exactly the
        # reproducibility this exists to prevent (`tasks/seed.py`).
        host_seed = new_trial_seed()
        run = ActiveRun(
            box=box,
            config=config,
            run_id=str(uuid.uuid4()),
            started_at=_now(),
            address=address,
            session_id_label=self._session_id_label,
            end_code=config.profile.end_code if config.profile else None,
            host_seed=host_seed,
        )
        self._active[box] = run
        self._ended.discard(box)
        # The time limit counts from this box's own start (`ARCHITECTURE.md#configuration`). STOP is
        # still only a request the firmware honours at a trial boundary, so
        # the deadline sends it and the board's end strobe does the ending.
        if self._duration_s is not None:
            run.deadline = self._loop.call_later(
                self._duration_s, self._on_deadline, box
            )

        self._ports.start_session(
            box,
            with_trial_seed(config.start_command, host_seed),
            on_ready=lambda seed, b=box: self._on_ready(b, seed),
            on_strobe=lambda code, ts, b=box: self._on_strobe(b, code, ts),
        )

    # --- session-thread callbacks (off the event loop) --------------------

    def _on_ready(self, box: int, seed: int | None) -> None:
        """Handshake resolved — open the file and write its header (`DATA.md#the-tsv-log`)."""
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
        run.files = files

        # Core fields (`DATA.md#the-json-document`), then flat task-profile config, then the seeds.
        core = {
            "rat": run.config.animal_name,
            "serial_port": run.address,
            "session_id": run.session_id_label,
            "sketch": run.config.sketch_name,
        }
        if self.recording_fields is not None:
            # Which recording this run is inside, and which digital input and
            # headstage port carry it (`RECORDING.md#what-is-written`). Core rather than
            # config: they describe the rig, not the task, and must stay out of
            # `params_hash` -- two runs of one tuning are comparable whether or
            # not one of them was recorded.
            try:
                core.update(self.recording_fields(box))
            except Exception:  # noqa: BLE001
                log.exception("box %d: couldn't describe its recording", box)
        config_meta = dict(run.config.config_metadata)
        if seed is not None:
            # `TASKS.md#seed`: what the firmware reports it is *running on*. Recorded
            # unchanged even when it disagrees with what we sent — the point of
            # this field is to describe the session that happened.
            config_meta["trial_seed"] = seed
        if run.host_seed is not None:
            config_meta["host_seed"] = run.host_seed
        if seed is not None and run.host_seed is not None and seed != run.host_seed:
            # Not an error — an old sketch seeding itself is exactly the case
            # `with_trial_seed` degrades toward. But it means this box's trial
            # sequence came from the board's own weak entropy, which is worth
            # saying out loud once rather than leaving to be inferred from two
            # numbers in a file nobody opens.
            log.warning(
                "box %d: firmware ignored the host trial seed (sent %d, board "
                "reported %d) — reflash %s to pick up the SEED= convention",
                box,
                run.host_seed,
                seed,
                run.config.sketch_name,
            )

        writer = AnimalWriter(
            files.tsv,
            files.json,
            files.mat,
            core,
            config_meta,
            # The declaration this run was configured from, travelling with the
            # data (`DATA.md#the-embedded-task-profile`). The database snapshot records the same
            # thing, but it stays on this machine — and cross-machine analysis
            # is the normal case here, not the exception.
            profile_snapshot=(
                run.config.profile.to_json() if run.config.profile is not None else None
            ),
        )
        try:
            writer.open_files()
        except Exception as exc:  # noqa: BLE001 - surface, don't crash the thread
            # Carry the real cause into both the operator-facing error and the
            # recorded stop reason. A bare "sidecar error" would leave someone
            # staring at a box that refused to start with nothing to act on —
            # and the most likely cause here (the exclusive open, `DATA.md#written-live`) names the
            # exact file standing in the way.
            log.error("box %d: couldn't open session files: %s", box, exc)
            self._schedule(self._emit_write_error(box, str(exc)))
            self._schedule_finalize(box, f"sidecar error: {exc}", clean=True)
            return
        run.writer = writer
        run.metrics = MetricSet(run.config.profile)
        # From here the `.tsv` grows on every strobe; the mirror picks it up on
        # its own cadence and never on this thread (`DATA.md#backup-mirroring`).
        if self._backup is not None:
            self._backup.track(files.tsv)
        if self.on_box_started is not None:
            try:
                self.on_box_started(box, run.config.animal_name)
            except Exception:  # noqa: BLE001
                log.exception("box %d: recording start hook failed", box)

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

        # After the fsync, never before: the strobe is on disk whatever this does.
        if self.on_strobe_tap is not None:
            try:
                self.on_strobe_tap(box, code, ts)
            except Exception:  # noqa: BLE001
                log.exception("box %d: recording strobe tap failed", box)

        if values:
            payload = {
                "box": box,
                "animalId": run.config.animal_id,
                "metrics": [v.to_json() for v in values],
            }
            self._schedule(self._push_telemetry(payload))

        if run.end_code is not None and code == run.end_code:
            # Clean firmware-reported end (`ARCHITECTURE.md#clean-exit`).
            self._schedule_finalize(box, CLEAN_STOP_REASON, clean=True)

    # --- stop / end -------------------------------------------------------

    def stop_box(self, box: int) -> None:
        """Send `STOP`; the board's own end strobe ends the run (`ARCHITECTURE.md#clean-exit`)."""
        if box in self._active:
            self._ports.stop_session(box)

    def _on_deadline(self, box: int) -> None:
        """The time limit elapsed for one box — runs on the loop.

        Sends the same STOP an operator would; the board finishes its current
        trial and emits its end strobe, which finalizes the run through the
        normal path. A box that already ended cancelled this timer, so getting
        here means the run is still live.
        """
        run = self._active.get(box)
        if run is None:
            return
        run.deadline = None
        log.info("box %d: session time limit reached; sending STOP", box)
        self.stop_box(box)

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
        if run.deadline is not None:
            run.deadline.cancel()
            run.deadline = None

        if run.writer is not None:
            await asyncio.to_thread(run.writer.finalize, reason)
        # Hand the finished trio to the mirror and stop tracking the .tsv. This
        # only *queues* the copy — ending a session must never wait on a slow
        # or dead backup target (`DATA.md#backup-mirroring`).
        if self._backup is not None and run.files is not None:
            self._backup.untrack(run.files.tsv)
            self._backup.enqueue(run.files.tsv, run.files.json, run.files.mat)
        if clean:
            try:
                await asyncio.to_thread(self._ports.end_session, box, reason)
            except Exception as exc:  # noqa: BLE001 - already torn down is fine
                log.debug("box %d: end_session during finalize: %s", box, exc)

        # Before the event goes out, so a client that re-asks on it sees the
        # box as ended — unless it was started again during the awaits above.
        if box not in self._active:
            self._ended.add(box)
        await self._on_animal_ended(run, reason)

    def board_dropped(self, box: int) -> None:
        """Called when a box drops to ERROR mid-session (hook from app, `ARCHITECTURE.md#board-drop`)."""
        if box in self._active:
            self._schedule_finalize(box, "board disconnected", clean=False)

    async def end_all(
        self,
        reason: str = "operator stop",
        *,
        graceful_timeout_s: float = 0.1,
        force: asyncio.Event | None = None,
        on_waiting: Callable[[list[int]], None] | None = None,
    ) -> None:
        """STOP every box, give them `graceful_timeout_s`, finalize the rest.

        STOP is a request the firmware honours at its next trial boundary, and
        the board then ends the run itself with `BF_END_SESSION`. The default
        100 ms is the behavior-only contract and is unchanged: the operator
        pressed End, and the trial in flight is cut.

        A RECORDING passes a real timeout (`RECORDING.md#graceful-end`). Cutting a trial
        there leaves electrophysiology with no behavioral outcome to align to,
        so the session waits for each box to finish the trial it is in. `force`
        lets the operator stop waiting; `on_waiting` reports who is still out.
        """
        for box in list(self._active):
            self.stop_box(box)
        deadline = self._loop.time() + graceful_timeout_s
        waiting: list[int] | None = None
        while self._active and self._loop.time() < deadline:
            if force is not None and force.is_set():
                break
            now_waiting = sorted(self._active)
            if on_waiting is not None and now_waiting != waiting:
                waiting = now_waiting
                on_waiting(now_waiting)
            await asyncio.sleep(min(0.05, max(0.0, deadline - self._loop.time())))
        if on_waiting is not None and waiting:
            on_waiting([])
        for box in list(self._active):
            await self.finalize_box(box, reason, clean=True)
        # Fire-and-forget finalizations (an end strobe that landed just before
        # or during the grace window, a board drop racing the stop) may still
        # be mid-write. Wait them out: `sessions.end` clears the running
        # session id as soon as this returns, and a finalization landing on
        # the wrong side of that clear would write its files with no
        # `session_animal_runs` row — the self-inflicted orphan (`DATA.md#orphan-adoption`).
        while self._finalizations:
            await asyncio.gather(*list(self._finalizations), return_exceptions=True)

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

    def _schedule(self, coro: Awaitable[None]) -> None:
        """Hand a coroutine to the event loop from a worker thread."""
        self._loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro))

    def _schedule_finalize(self, box: int, reason: str, clean: bool) -> None:
        """Schedule a finalization *and track it* until it completes.

        Every fire-and-forget path into `finalize_box` goes through here, so
        `end_all` can wait on the whole set. An untracked finalization is the
        race `end_all`'s drain exists to close; don't add one via `_schedule`.
        """

        def _create() -> None:
            task = asyncio.ensure_future(self.finalize_box(box, reason, clean))
            self._finalizations.add(task)
            task.add_done_callback(self._finalizations.discard)

        self._loop.call_soon_threadsafe(_create)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split_label(label: str) -> tuple[str, str]:
    """`"<prefix>_<sessionNumber>"` → (prefix, sessionNumber).

    Split on the last underscore, since a prefix may itself contain one.
    """
    prefix, _, number = label.rpartition("_")
    return (prefix, number) if prefix else (label, "")
