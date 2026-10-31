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
import copy
import functools
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from ..hardware import service as hardware_service
from ..hardware import store as hardware_store
from ..protocol import Evt, event
from ..strobes import store as strobe_store
from . import allocation, registry

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


class WiringNotLoaded(Exception):
    """The rig's stored wiring was not put in force when it was installed --
    it did not load, or it was held because nobody saved or confirmed it on
    this machine -- so the pins in force are the shipped ones, not the rig's
    (`TASKS.md#the-channel-set-and-the-pin-map`). Nothing was started, flashed
    or identified. The message says why."""


class WiringSaveBlocked(Exception):
    """A wiring save refused before anything is written: the rig's state does
    not allow one yet (`hardware_service.save_blocked`: stored wiring with
    nothing to repair, which only Reset replaces, or pins read from a stored
    file that were not confirmed, RIG108), or the draft breaks a wiring rule
    (RIG101-RIG107). The message says what to do."""


class RigInUse(Exception):
    """A rig definition write refused because a session is set up or a box is
    running. The message says what to do instead."""


class VocabularyInUse(RigInUse):
    """`RigInUse`, for a strobe vocabulary edit."""


class WiringWouldBreakTasks(Exception):
    """A wiring change that would stop saved task profiles generating, asked
    for without `confirm`. Nothing was written."""

    def __init__(self, breaks: list[dict[str, Any]]) -> None:
        super().__init__(
            f"This wiring would stop {len(breaks)} saved "
            f"task{'' if len(breaks) == 1 else 's'} compiling."
        )
        self.breaks = breaks


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
        #: The wiring in force and, when stored wiring was not put in force,
        #: why. Set only by `_install_wiring`, from the same read that chose
        #: the pins in force, so the refusal and the pins never disagree.
        self._installed = hardware_service.InForce(None, None)
        # The vocabulary first: installing the wiring checks its rules, and
        # RIG104/RIG106/RIG107 read codes from the vocabulary in force.
        registry.set_vocabulary_source(vocabulary.load)
        # The one moment unrecorded wiring may be recorded without a save:
        # this start, before anything reads it (`record_at_first_start`).
        hardware.record_at_first_start()
        self._install_wiring()

    # -- the lock ------------------------------------------------------------ #

    def reading(self):  # noqa: ANN201 - an async context manager
        """Hold while using a generated folder, through any belief recorded
        about it (what `PortManager.flash` records, and `note_flashed` after it).
        Waits for a write in progress; a write waits for it."""
        return self._lock.reading()

    def refuse_if_in_use(self, refusal: type[RigInUse], message: str) -> None:
        if self._in_use():
            raise refusal(message)

    @asynccontextmanager
    async def writing(
        self, message: str = TASKS_IN_USE, *, refusal: type[RigInUse] = RigInUse
    ) -> AsyncIterator[None]:
        """Exclusive. Refused with `refusal(message)` while in use -- once
        before waiting, cheaply, and again once the lock is held, which is the
        check that counts."""
        self.refuse_if_in_use(refusal, message)
        async with self._lock.writing():
            self.refuse_if_in_use(refusal, message)
            yield

    # -- the writes ---------------------------------------------------------- #

    async def save_wiring(
        self, document: dict[str, Any], *, confirm: bool, confirmed_pins: bool = False
    ) -> dict[str, Any]:
        """Raises `RigInUse`; `WiringSaveBlocked` when the rig's state refuses
        a save or the draft breaks a wiring rule; `hardware.store.RigInvalid`
        for a document that is not one; `WiringWouldBreakTasks` without
        `confirm`; or `StrobeRefused` when its edge codes cannot be issued.
        In that order, so a draft that is going to be refused never asks the
        operator to accept the tasks it would break first.

        Issuing the channel set's new edge codes (TASKS.md#edge-codes) is part
        of this one write: the vocabulary gains them, then the wiring names
        them, then one rebuild serves both.
        """
        async with self.writing(WIRING_IN_USE):
            # First, before any cost is computed or code issued: the rig's own
            # state, which the editor was told about in `status.canSave`.
            blocked = await asyncio.to_thread(self.save_blocked, confirmed_pins=confirmed_pins)
            if blocked:
                raise WiringSaveBlocked(blocked)
            problems = hardware_store.save_problems(document)
            if problems:
                # Before any code is issued: a refused wiring issues nothing.
                raise hardware_store.RigInvalid(problems)
            rules = await asyncio.to_thread(hardware_service.problems_for, document)
            if rules:
                # The editor holds Save on these too, but this is the guard: a
                # save that bypassed it would put two channels on one pin in
                # force and lift a refusal.
                raise WiringSaveBlocked(
                    "This wiring has problems a save does not take: "
                    + "; ".join(f"{p['code'] or 'shape'} {p['location']}: {p['message']}" for p in rules[:5])
                )
            breaks = await asyncio.to_thread(impact_of, self._tasks, wiring=document)
            if breaks and not confirm:
                # Not an error the operator cannot pass -- it is the "shown
                # loudly" half of "a pin change applies to everything". The app
                # does not veto a rewiring; it refuses to let one happen
                # unnoticed. Nothing is written on this path.
                raise WiringWouldBreakTasks(breaks)
            filled, issued = await asyncio.to_thread(self._issue_edge_codes, document)
            try:
                stored = await asyncio.to_thread(self._hardware.save, filled)
            except BaseException:
                if issued:
                    # The vocabulary changed and stays changed (append only;
                    # the next save reclaims these codes), so the rebuild every
                    # vocabulary edit owes the generated folders still runs.
                    await self._rebuild()
                    vocabulary = await asyncio.to_thread(self.vocabulary_payload)
                    await self._broadcast(event(Evt.STROBES_UPDATED, vocabulary))
                raise
            # Install before reporting, or the reply would describe the wiring
            # that was in force a moment ago.
            self._install_wiring()
            payload = await asyncio.to_thread(
                functools.partial(
                    hardware_service.saved_payload, self._hardware, stored, in_force=self.in_force()
                )
            )
            payload["breaks"] = breaks
            payload["allocations"] = [a.to_json() for a in issued]
            await self._rebuild()
            if issued:
                vocabulary = await asyncio.to_thread(self.vocabulary_payload)
                await self._broadcast(event(Evt.STROBES_UPDATED, vocabulary))
            await self._broadcast(event(Evt.HARDWARE_UPDATED, payload["status"]))
        return payload

    def _issue_edge_codes(
        self, document: dict[str, Any]
    ) -> tuple[dict[str, Any], list[allocation.Allocation]]:
        """Plan against the vocabulary in force; if anything is to be issued,
        plan again against this machine's own document, read strictly, and
        write it. A wiring save that issues nothing never reads it, so a
        damaged vocabulary refuses only a save that needs a code."""
        filled, planned = allocation.plan(document, registry.vocabulary())
        if not planned:
            return filled, []
        own = self.load_vocabulary_strict()
        filled, planned = allocation.plan(document, registry.Vocabulary(own))
        if planned:
            self._vocabulary.save(allocation.issue(own, planned))
            registry.set_vocabulary_source(self._vocabulary.load)
        return filled, planned

    async def reset_wiring(self) -> dict[str, Any]:
        async with self.writing(WIRING_IN_USE):
            await asyncio.to_thread(self._hardware.reset)
            self._install_wiring()
            payload = await asyncio.to_thread(
                hardware_service.document_payload, self._hardware, in_force=self.in_force()
            )
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
        last looked is still counted. Nothing is written on any refusal path:
        `VocabularyInUse`, or the `StrobeRefused` a rule or `check` raised.
        """
        async with self.writing(VOCABULARY_IN_USE, refusal=VocabularyInUse):
            doc = await asyncio.to_thread(self.load_vocabulary_strict)
            if check is not None:
                await asyncio.to_thread(check)
            updated = edit(doc)
            await asyncio.to_thread(self._vocabulary.save, updated)
            registry.set_vocabulary_source(self._vocabulary.load)
            payload = await asyncio.to_thread(self.vocabulary_payload)
            await self._rebuild()
            await self._broadcast(event(Evt.STROBES_UPDATED, payload))
        return payload

    # -- reads that need no lock --------------------------------------------- #

    def wiring_problem(self) -> str | None:
        """Why the rig's stored wiring was not put in force when it was
        installed -- it did not load, or nobody saved or confirmed it on this
        machine -- or None while the rig's own wiring (or none) is in force.

        THE WIRING IN FORCE, NEVER A FRESH READ. The registry composes from the
        document `_install_wiring` read, until the next install: a save, a
        reset or a restart. A file fixed or copied in by hand meanwhile changes
        no pin, so it must not lift the refusal either -- that is how a box
        once started on the shipped pins with every check passing. And a
        restart onto it holds it, since nobody saved it here. The session
        lifecycle and the utility baseline ask this before they drive a box.
        """
        return self._installed.problem

    def save_blocked(self, *, confirmed_pins: bool) -> str | None:
        """Why the rig's state refuses a wiring save now, or None."""
        return hardware_service.save_blocked(
            hardware_service.rig_state(self._hardware, self.in_force()), confirmed_pins=confirmed_pins
        )

    def _install_wiring(self) -> None:
        """Read the stored wiring ONCE and put exactly that in force.

        The registry gets a snapshot rather than a reader of the file, so what
        it composes, and when, cannot drift from what this read decided.
        """
        installed = hardware_service.installed(self._hardware.inspect())
        self._installed = installed
        document = installed.document
        registry.set_rig_source(lambda: copy.deepcopy(document))

    def in_force(self) -> hardware_service.InForce:
        """The wiring in force -- the stored document installed, or None for
        the shipped one -- and why stored wiring is not in force, if it is not.
        What `hardware.get` describes."""
        return self._installed._replace(document=copy.deepcopy(self._installed.document))

    def load_vocabulary_strict(self) -> dict[str, Any]:
        """Raises `StrobeRefused("unreadable")` for a document that won't read."""
        return self._vocabulary.load_strict()

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
