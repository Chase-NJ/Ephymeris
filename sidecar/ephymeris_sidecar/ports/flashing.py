"""The flash queue: every flash the app performs, one at a time, rig-wide
(`ARCHITECTURE.md#the-flash-queue`).

Three kinds of caller want a box flashed — the utility baseline's restores, the
session's placement walk, and Debug Mode — and all of them under the same rule:
one box at a time, rig-wide, once its port is free. This is the only caller of
`PortManager.flash`, so the rule holds across callers rather than within each.
It lives here and not in the frontend because a queue in a component dies
with the component, mid-walk, while the boxes it promised are still unflashed.

A job's origin fixes its policy:

* **session** — the sketch is read from the held mapping *when the job runs*,
  not when it was queued, so a re-confirmed mapping can never get the old
  one's sketch. Waits for its port; lands in `IDLE` for the runner.
* **debug** — a sketch the operator chose. Waits for its port; resumes a
  console it took, or opens one at the requested baud. Pinned against
  automatic restores (`utility.py`).
* **baseline** — never waits: its `prepare` decides, synchronously and with no
  `await` before the flash takes the port, whether the box is still IDLE and
  still wanted. That is what keeps "only an IDLE port" true even though the
  job sat in a queue.

What the queue is doing is published as `flash.queue` and replayed on connect,
so a component that unmounts, a window that reloads, or a second window loses
nothing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any, AsyncContextManager, Awaitable, Callable, Iterable, Literal

from ..settings import BOX_COUNT
from .manager import BoardNotDetected, PortManager, PortNotBound
from .states import PortState

log = logging.getLogger(__name__)

Origin = Literal["baseline", "session", "debug"]

#: How long a queued session or Debug flash waits for its port to come free
#: before it gives up. A baseline restore elsewhere on the rig takes about a
#: minute; three covers a cold start's queue ahead of it.
PORT_WAIT_S = 180.0
#: How often a waiting job re-checks its deadline when no port changes.
TICK_S = 1.0

#: Ports a session or Debug flash may take. Entering `FLASHING` force-releases a
#: console (`ARCHITECTURE.md#exclusivity`), which is right when a person asked.
_FREE = (PortState.IDLE, PortState.PASSTHROUGH)


@dataclass
class FlashJob:
    """One box to flash.

    `prepare` runs under the rig definition's read side, immediately before
    the flash, and returns the sketch folder to flash or None to drop the job.
    `finished` hears the outcome: None on success, else the exception.
    """

    box: int
    origin: Origin
    prepare: Callable[[], str | None]
    sketch_path: str | None = None
    finished: Callable[[BaseException | None], None] | None = None
    #: Debug only: open a console at this baud once the flash lands, if the
    #: flash did not resume one it took.
    baud: int | None = None
    #: Baseline only: a reflash the operator asked for.
    force: bool = False
    id: int = field(default_factory=lambda: next(_ids))
    #: When it first found its port busy: the wait is for the port, not for
    #: the jobs queued ahead of it.
    waiting_since: float | None = None


_ids = count(1)


@dataclass
class _Row:
    """What one box's last job is doing, as the client sees it."""

    origin: Origin
    sketch_path: str | None
    state: str  # queued | waiting | flashing | done | failed
    detail: str | None = None
    job_id: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "sketchPath": self.sketch_path,
            "sketchName": sketch_name(self.sketch_path),
            "state": self.state,
            "detail": self.detail,
        }


class FlashQueue:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ports: PortManager,
        discovery: Callable[[], Any],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        reading: Callable[[], AsyncContextManager[None]],
        on_flashed: Callable[[int, str, Origin], None] = lambda *_a: None,
        box_count: int = BOX_COUNT,
    ) -> None:
        self._loop = loop
        self._ports = ports
        self._discovery = discovery
        self._broadcast = broadcast
        #: The rig definition's read side (`TASKS.md#the-rig-definition`):
        #: held from choosing the sketch until what it carries is recorded.
        self._reading = reading
        #: Told of every successful flash before anything can yield, so the
        #: idle transition the flash just queued sees the result.
        self._on_flashed = on_flashed
        self._boxes = range(1, box_count + 1)
        self._jobs: list[FlashJob] = []
        self._rows: dict[int, _Row] = {}
        self._worker: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()

    # --- submitting -------------------------------------------------------

    def submit(self, jobs: Iterable[FlashJob]) -> None:
        """Queue jobs behind whatever is queued. Returns immediately.

        A box already queued by the same origin keeps its place and takes the
        newer job's terms: a second request is the same request, restated.
        """
        changed = False
        for job in jobs:
            queued = next(
                (j for j in self._jobs if j.box == job.box and j.origin == job.origin), None
            )
            if queued is not None:
                job.force = job.force or queued.force
                self._jobs[self._jobs.index(queued)] = job
            else:
                self._jobs.append(job)
            if job.origin != "baseline":
                # A baseline job shows only once it decides to flash; most
                # decide not to, and a row for each would bury the real ones.
                self._rows[job.box] = _Row(job.origin, job.sketch_path, "queued", job_id=job.id)
                changed = True
        if changed:
            self._publish_soon()
        self._kick()

    def cancel(
        self,
        origins: Iterable[Origin] = ("session", "debug"),
        boxes: Iterable[int] | None = None,
        *,
        clear: bool = False,
    ) -> None:
        """Drop queued jobs. A flash already under way always finishes:
        stopping an upload part-way leaves a board nobody can name.

        `clear` also forgets these origins' rows, finished or in flight, for a
        new mapping that starts clean: a flash of the old mapping that lands
        afterwards then reports nothing.
        """
        origins = set(origins)
        targets = set(boxes) if boxes is not None else set(self._boxes)
        dropped = [j for j in self._jobs if j.origin in origins and j.box in targets]
        if not dropped and not clear:
            return
        self._jobs = [j for j in self._jobs if j not in dropped]
        for job in dropped:
            row = self._rows.get(job.box)
            if row is not None and row.job_id == job.id:
                del self._rows[job.box]
        if clear:
            for box, row in list(self._rows.items()):
                if box in targets and row.origin in origins:
                    del self._rows[box]
        self._publish_soon()

    def port_changed(self, _box: int) -> None:
        """A port moved; a job waiting on it may be able to run."""
        self._wake.set()

    @property
    def idle(self) -> bool:
        """Nothing queued and nothing flashing."""
        return not self._jobs and self._worker is None

    async def stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._jobs.clear()

    # --- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        boxes = []
        for box in self._boxes:
            row = self._rows.get(box)
            carried = self._ports.carried(box)
            boxes.append(
                {
                    "box": box,
                    "job": row.to_json() if row is not None else None,
                    "carries": (
                        {"path": carried.path, "name": sketch_name(carried.path)}
                        if carried is not None
                        else None
                    ),
                }
            )
        return {"boxes": boxes}

    async def publish(self) -> None:
        from ..protocol import Evt, event

        await self._broadcast(event(Evt.FLASH_QUEUE, self.status()))

    def _publish_soon(self) -> None:
        # Never awaited inside the worker: between a baseline job's `prepare`
        # and the flash taking the port there must be no yield.
        self._loop.create_task(self.publish())

    # --- the worker -------------------------------------------------------

    def _kick(self) -> None:
        self._wake.set()
        if self._jobs and self._worker is None:
            self._worker = self._loop.create_task(self._run(), name="flash-queue")

    async def _run(self) -> None:
        try:
            while self._jobs:
                job = self._next_runnable()
                if job is None:
                    self._wake.clear()
                    try:
                        await asyncio.wait_for(self._wake.wait(), TICK_S)
                    except asyncio.TimeoutError:
                        pass
                    continue
                self._jobs.remove(job)
                try:
                    await self._execute(job)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - one box must not stop the rest
                    log.exception("flash queue: box %d's job failed unexpectedly", job.box)
        finally:
            self._worker = None

    def _next_runnable(self) -> FlashJob | None:
        """The first job, in queue order, that can run now. Jobs that can
        never run (no board, a faulted port, a wait that timed out) fail here."""
        for job in list(self._jobs):
            if job.origin == "baseline":
                return job  # `prepare` decides, at the last moment
            reason = self._blocked(job)
            if reason is None:
                return job
            if reason[0] == "fail":
                self._jobs.remove(job)
                self._fail_row(job, reason[1])
                continue
            if job.waiting_since is None:
                job.waiting_since = time.monotonic()
            if time.monotonic() - job.waiting_since > PORT_WAIT_S:
                self._jobs.remove(job)
                self._fail_row(
                    job, f"the port stayed {reason[1]} for three minutes — retry once it is free."
                )
            else:
                self._set_row(job, "waiting", f"waiting for the port ({reason[1]})")
        return None

    def _blocked(self, job: FlashJob) -> tuple[str, str] | None:
        try:
            self._ports.resolve_address(job.box)
        except (PortNotBound, BoardNotDetected) as exc:
            return ("fail", str(exc))
        state = self._ports.handler(job.box).state
        if state is PortState.ERROR:
            return ("fail", "the box is in an error state — acknowledge it, then retry the flash.")
        if state in _FREE:
            return None
        return ("wait", state.value.lower())

    async def _execute(self, job: FlashJob) -> None:
        async with self._reading():
            # From here to the flash taking the port: nothing that yields.
            path = job.prepare()
            if path is None:
                self._drop_row(job)
                return
            sketch = next(
                (s for s in getattr(self._discovery(), "sketches", []) if s.path == path),
                None,
            )
            if sketch is None:
                error = LookupError(f"{sketch_name(path)} isn't in the sketch library any more.")
                self._fail_row(job, str(error))
                if job.finished is not None:
                    job.finished(error)
                return
            self._rows[job.box] = _Row(job.origin, path, "flashing", job_id=job.id)
            self._publish_soon()
            try:
                # Takes the port before its first await (`PortManager.flash`).
                _state, resumed = await self._ports.flash(
                    job.box,
                    sketch.path,
                    sketch.name,
                    getattr(self._discovery(), "libraries_path", None),
                    self._progress(job),
                    suppress_passthrough_resume=job.origin != "debug",
                )
            except Exception as exc:  # noqa: BLE001 - compile, upload, port, missing cli
                log.warning("box %d: %s flash of %s failed: %s", job.box, job.origin, sketch.name, exc)
                self._fail_row(job, str(exc))
                if job.finished is not None:
                    job.finished(exc)
                return
            # Before anything yields: the idle transition this flash just
            # queued must find the result already recorded.
            self._on_flashed(job.box, sketch.path, job.origin)
            if job.finished is not None:
                job.finished(None)
        detail = None
        if job.origin == "debug" and job.baud is not None and not resumed:
            try:
                self._ports.open_passthrough(job.box, job.baud)
                detail = "console open"
            except Exception as exc:  # noqa: BLE001 - the flash itself landed
                detail = f"flashed, but the console didn't open: {exc}"
        self._set_row(job, "done", detail)

    def _progress(self, job: FlashJob) -> Callable[[str, str, str], None]:
        from ..protocol import Evt, event

        def on_progress(phase: str, stream: str, text: str) -> None:
            if job.origin == "baseline":
                # A restore nobody asked to watch; `utility.updated` says enough.
                log.debug("box %d baseline %s/%s: %s", job.box, phase, stream, text.rstrip())
                return
            self._loop.create_task(
                self._broadcast(
                    event(
                        Evt.FLASH_PROGRESS,
                        {"box": job.box, "phase": phase, "stream": stream, "text": text},
                    )
                )
            )

        return on_progress

    # --- rows -------------------------------------------------------------

    def _set_row(self, job: FlashJob, state: str, detail: str | None) -> None:
        """Update this job's row. Never creates one: a row that is gone was
        cleared or replaced, and a late outcome must not bring it back. A
        baseline job that never flashed has none, and reports through the
        utility instead."""
        row = self._rows.get(job.box)
        if row is None or row.job_id != job.id:
            return
        if (row.state, row.detail) == (state, detail):
            return
        row.state, row.detail = state, detail
        self._publish_soon()

    def _fail_row(self, job: FlashJob, detail: str) -> None:
        self._set_row(job, "failed", detail)

    def _drop_row(self, job: FlashJob) -> None:
        row = self._rows.get(job.box)
        if row is not None and row.job_id == job.id:
            del self._rows[job.box]
            self._publish_soon()


def sketch_name(path: str | None) -> str | None:
    """A sketch folder's name, from either separator: the sidecar runs on
    Windows and is tested on POSIX. The folder name is the sketch name."""
    if not path:
        return None
    return path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or None
