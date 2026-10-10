"""The rig definition: the rig wiring plus the strobe vocabulary in force.

Both halves feed every generated `TaskPins.h`, so they are owned together
(TASKS.md#the-rig-definition, GLOSSARY.md#rig-definition). Three rules live
here and nowhere else:

* A hypothetical is seen only by its asker (`impact_of`, ADR 0001).
* A write runs end to end -- refuse if in use, judge, store, install, rebuild,
  rescan, announce -- with no other write and no reader of a generated folder
  in between (`RigDefinition.writing`).
* A write is refused while a session is set up or a box is running, checked
  again once the write holds the lock: a session confirmed while it waited
  read its profiles from the folders this write is about to replace.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ..hardware import service as hardware_service
from ..hardware import store as hardware_store
from ..protocol import ErrCode, Evt, event
from ..server import CommandError
from ..strobes import store as strobe_store
from . import registry

log = logging.getLogger(__name__)

WIRING_IN_USE = (
    "A session is set up or a box is running. Change the wiring between sessions: "
    "every wiring change regenerates the sketches the boxes are flashed from."
)
VOCABULARY_IN_USE = (
    "A session is set up or a box is running. Edit the vocabulary between sessions: "
    "every edit regenerates the sketches the boxes are flashed from."
)
TASKS_IN_USE = (
    "A session is set up or a box is running. Save or delete tasks between sessions: "
    "a task's sketch folder is what its box is flashed from."
)


def impact_of(
    tasks: Any, *, wiring: dict | None = None, vocabulary: dict | None = None
) -> list[dict[str, Any]]:
    """Which stored task profiles a hypothetical rig definition would newly break.

    COMPUTED BEFORE THE WRITE, which is the whole point. Full channel authoring
    means an operator can delete a channel a saved task binds, and retiring a
    code can strand a task that emits it; catching either at generation time
    would be too late -- the document is written by then and the task already
    broken.

    NEWLY is load-bearing. A task already failing for its own reasons is not
    this change's fault, and listing it would bury the ones that are -- so each
    profile is validated under BOTH definitions and only the difference is
    reported.

    The hypothetical is context-local (`registry.hypothetical`), so nothing else
    reading the rig definition meanwhile can see it.

    `tasks` is the task-profile store: `list_entries()` and `failures(id)`, the
    latter reading the rig definition in force. It is None until one exists, and
    an empty answer on a rig with no profiles is the honest answer either way.
    """
    if tasks is None:
        return []
    entries = list(tasks.list_entries())
    if not entries:
        return []

    before = {e["id"]: tasks.failures(e["id"]) for e in entries}
    with registry.hypothetical(rig=wiring, vocabulary=vocabulary):
        after = {e["id"]: tasks.failures(e["id"]) for e in entries}

    out: list[dict[str, Any]] = []
    for entry in entries:
        gained = sorted(after[entry["id"]] - before[entry["id"]])
        if gained:
            out.append({"specId": entry["id"], "label": entry.get("label"), "codes": gained})
    return out


def strobe_error(exc: strobe_store.StrobeRefused) -> CommandError:
    """A vocabulary rule's refusal, as the wire reports it."""
    code = {
        "invalid": ErrCode.STROBE_INVALID,
        "required": ErrCode.STROBE_REQUIRED,
        "in_recorded_session": ErrCode.STROBE_IN_RECORDED_SESSION,
        "would_break_tasks": ErrCode.STROBE_WOULD_BREAK_TASKS,
        "import_conflict": ErrCode.STROBE_IMPORT_CONFLICT,
        "unreadable": ErrCode.STROBE_VOCABULARY_UNREADABLE,
    }.get(exc.reason, ErrCode.STROBE_INVALID)
    return CommandError(code, str(exc), exc.detail or None)


class _ReadWriteLock:
    """Many readers or one writer, and a waiting writer goes first.

    Writer-preferring because readers arrive in streams -- every idle box's
    utility restore after a rebuild is one -- and a save must not wait behind
    all of them. Every state change is synchronous on the event loop, so a task
    cancelled while waiting (`UtilityBaseline.stop` cancels its restore worker)
    can never leave a count behind or a reader blocked by a writer that gave up.

    Not re-entrant, and says so: a task that already holds either side and asks
    again would otherwise wait on itself forever.
    """

    def __init__(self) -> None:
        self._readers: dict[asyncio.Task[Any] | None, int] = {}
        self._writing = False
        self._writer: asyncio.Task[Any] | None = None
        self._writers_waiting = 0
        self._waiters: set[asyncio.Future[None]] = set()

    def _wake(self) -> None:
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()

    async def _wait_until(self, ready: Callable[[], bool]) -> None:
        while not ready():
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.add(waiter)
            try:
                await waiter
            finally:
                self._waiters.discard(waiter)

    def _refuse_reentry(self, task: asyncio.Task[Any] | None) -> None:
        if task is not None and (task is self._writer or task in self._readers):
            raise RuntimeError("the rig definition lock is not re-entrant")

    @asynccontextmanager
    async def reading(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        self._refuse_reentry(task)
        await self._wait_until(lambda: not self._writing and not self._writers_waiting)
        self._readers[task] = self._readers.get(task, 0) + 1
        try:
            yield
        finally:
            self._readers[task] -= 1
            if not self._readers[task]:
                del self._readers[task]
            self._wake()

    @asynccontextmanager
    async def writing(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        self._refuse_reentry(task)
        self._writers_waiting += 1
        try:
            await self._wait_until(lambda: not self._writing and not self._readers)
        finally:
            self._writers_waiting -= 1
            # A writer that gave up must not leave readers queued behind it.
            self._wake()
        self._writing, self._writer = True, task
        try:
            yield
        finally:
            self._writing, self._writer = False, None
            self._wake()


class RigDefinition:
    """Owns the rig definition's writes, and the lock everything that reads a
    generated sketch folder takes (TASKS.md#the-rig-definition).

    What it does not own is passed in, because each belongs elsewhere:
    `in_use` (the session lifecycle's "is a session set up or a box running?"),
    `repin` (rebuild the bundled sketches), `rescan` (discovery), `after_rebuild`
    (what the app announces and resets once folders changed) and `broadcast`.
    """

    def __init__(
        self,
        *,
        hardware: hardware_store.HardwareStore,
        vocabulary: strobe_store.VocabularyStore,
        tasks: Any,
        repin: Callable[[], int],
        in_use: Callable[[], bool],
        rescan: Callable[[], Awaitable[None]],
        after_rebuild: Callable[[int, int], Awaitable[None]],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._hardware = hardware
        self._vocabulary = vocabulary
        self._tasks = tasks
        self._repin = repin
        self._in_use = in_use
        self._rescan = rescan
        self._after_rebuild = after_rebuild
        self._broadcast = broadcast
        self._lock = _ReadWriteLock()
        registry.set_rig_source(hardware.load)
        registry.set_vocabulary_source(vocabulary.load)

    # -- the lock ------------------------------------------------------------ #

    def reading(self):  # noqa: ANN201 - an async context manager
        """Hold while using a generated folder, through any belief recorded
        about it (a flash through `note_flashed`, a restore through `believed`).
        Waits for a write in progress; a write waits for it."""
        return self._lock.reading()

    def refuse_if_in_use(self, code: str, message: str) -> None:
        if self._in_use():
            raise CommandError(code, message)

    @asynccontextmanager
    async def writing(
        self, code: str = ErrCode.RIG_IN_USE, message: str = TASKS_IN_USE
    ) -> AsyncIterator[None]:
        """Exclusive. Refused while in use -- once before waiting, cheaply, and
        again once the lock is held, which is the check that counts."""
        self.refuse_if_in_use(code, message)
        async with self._lock.writing():
            self.refuse_if_in_use(code, message)
            yield

    # -- the writes ---------------------------------------------------------- #

    async def save_wiring(self, document: dict[str, Any], *, confirm: bool) -> dict[str, Any]:
        async with self.writing(ErrCode.RIG_IN_USE, WIRING_IN_USE):
            breaks = await asyncio.to_thread(impact_of, self._tasks, wiring=document)
            if breaks and not confirm:
                # Not an error the operator cannot pass -- it is the "shown
                # loudly" half of "a pin change applies to everything". The app
                # does not veto a rewiring; it refuses to let one happen
                # unnoticed. Nothing is written on this path.
                raise CommandError(
                    ErrCode.RIG_WOULD_BREAK_TASKS,
                    f"This wiring would stop {len(breaks)} saved "
                    f"task{'' if len(breaks) == 1 else 's'} compiling.",
                    {"breaks": breaks},
                )
            try:
                stored = await asyncio.to_thread(self._hardware.save, document)
            except hardware_store.RigInvalid as exc:
                raise CommandError(
                    ErrCode.RIG_INVALID,
                    "This wiring document could not be saved.",
                    {"problems": [{"location": loc, "message": msg} for loc, msg in exc.problems]},
                ) from exc
            # Install before reporting, or the reply would describe the wiring
            # that was in force a moment ago.
            registry.set_rig_source(self._hardware.load)
            payload = await asyncio.to_thread(hardware_service.saved_payload, self._hardware, stored)
            payload["breaks"] = breaks
            await self._rebuild()
            await self._broadcast(event(Evt.HARDWARE_UPDATED, payload["status"]))
        return payload

    async def reset_wiring(self) -> dict[str, Any]:
        async with self.writing(ErrCode.RIG_IN_USE, WIRING_IN_USE):
            await asyncio.to_thread(self._hardware.reset)
            registry.set_rig_source(self._hardware.load)
            payload = await asyncio.to_thread(hardware_service.document_payload, self._hardware)
            await self._rebuild()
            await self._broadcast(event(Evt.HARDWARE_UPDATED, payload["status"]))
        return payload

    async def edit_vocabulary(
        self,
        edit: Callable[[dict[str, Any]], dict[str, Any]],
        *,
        check: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """Load, judge, edit, write, install, rebuild, announce -- in that order.

        `check` runs inside the write, so a task saved a moment after the page
        last looked is still counted. Nothing is written on any refusal path.
        """
        async with self.writing(ErrCode.STROBE_SESSION_RUNNING, VOCABULARY_IN_USE):
            doc = await asyncio.to_thread(self.load_vocabulary_strict)
            if check is not None:
                await asyncio.to_thread(check)
            try:
                updated = edit(doc)
                await asyncio.to_thread(self._vocabulary.save, updated)
            except strobe_store.StrobeRefused as exc:
                raise strobe_error(exc) from exc
            registry.set_vocabulary_source(self._vocabulary.load)
            payload = await asyncio.to_thread(self.vocabulary_payload)
            await self._rebuild()
            await self._broadcast(event(Evt.STROBES_UPDATED, payload))
        return payload

    # -- reads that need no lock --------------------------------------------- #

    def load_vocabulary_strict(self) -> dict[str, Any]:
        try:
            return self._vocabulary.load_strict()
        except strobe_store.StrobeRefused as exc:
            raise strobe_error(exc) from exc

    def vocabulary_payload(self) -> dict[str, Any]:
        payload = registry.vocabulary().to_json()
        try:
            self._vocabulary.load_strict()
            payload["editable"], payload["problem"] = True, None
        except strobe_store.StrobeRefused as exc:
            payload["editable"], payload["problem"] = False, str(exc)
        return payload

    # -- rebuilding ---------------------------------------------------------- #

    def rebuild_at_startup(self) -> tuple[int, int]:
        """The same two rebuilds, synchronously, before anything can flash.

        At start because a folder written by an older generator either stops
        compiling (loud) or sends keys the firmware no longer parses (silent),
        and because the first flash after a launch must not serve the shipped
        pins while every later one serves the rig's. Returns (bundled, tasks).
        """
        return self._repin(), self._tasks.regenerate_all()

    async def _rebuild(self) -> None:
        """Everything that carries a pin number or a strobe code, rebuilt -- THE
        one place, for a wiring change and a vocabulary edit alike.

        Two outputs, deliberately. Pins and codes are compiled into every
        generated `TaskPins.h`, a task profile's and a bundled sketch's alike, so
        a change that rebuilt only one would leave the other flashing the old
        pins or codes. It would still compile and run; the only symptom would be
        a valve that never fires or an event decoded under the wrong name.

        Rebuild, then rescan, so discovery sees the new folders rather than the
        ones about to be replaced.
        """
        tasks = await asyncio.to_thread(self._tasks.regenerate_all)
        pinned = await asyncio.to_thread(self._repin)
        if tasks or pinned:
            log.info(
                "rig definition changed: rebuilt %d task profile(s) and %d bundled sketch(es)",
                tasks,
                pinned,
            )
        await self._rescan()
        await self._after_rebuild(tasks, pinned)
