"""The hardware utility baseline — `settings.md` §8.

The baseline is one idea: **a box that isn't doing anything else is a box
Ephymeris can talk to.** The operator picks a utility sketch once
(`Settings.utilitySketchPath`), and from then on the app quietly returns every
idle, bound box to it — at startup, when a board appears, and whenever a run or
session ends. Nothing about that is announced; it is the resting state, not an
operation. What *is* announced is failure, because a box that can't be restored
is a box whose firmware nobody knows.

Two rules keep this from being hostile:

* **A restore only ever takes an `IDLE` port.** Never a console the user has
  open, never a flash, never a running session. Entering `FLASHING` would
  happily force-release `PASSTHROUGH` (`dashboard.md` §5.3) — that
  is exactly what must not happen here, so the check is on `IDLE` rather than
  on the transition being legal.
* **A confirmed session mapping holds the whole rig.** Between
  `sessions.confirmMapping` and the session ending, boxes carry task sketches
  and land in `IDLE` constantly; restoring then would erase the very sketch the
  runner is about to start. `hold()`/`release()` bracket that window.

The payoff is `identify()`: with a known sketch on the board, the app can ask
one box to point at itself (`dashboard.md` §7.3). The commands come
from the profile's `identify` pair, never from anything hardcoded here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable

from .ports.handler import PortBusy
from .ports.manager import BoardNotDetected, PortManager, PortNotBound
from .ports.states import IllegalTransition, PortState
from .settings import BOX_COUNT, SidecarSettings
from .tasks import profile as task_profile
from .tasks.profile import TaskProfile

log = logging.getLogger(__name__)

#: How long to wait for the board to say *anything* after opening its port. The
#: open toggles DTR, which reboots the Mega, so the first line marks the end of
#: `setup()` — waiting for it beats guessing a sleep long enough for every
#: sketch.
BOOT_TIMEOUT_S = 3.0
#: How long to wait for the sketch's own telemetry line confirming it acted on
#: the identify command. Short: a utility sketch reports on every state change.
CONFIRM_TIMEOUT_S = 2.5
#: Poll granularity while waiting on either of the above.
WAIT_TICK_S = 0.05


class UtilityUnavailable(Exception):
    """No usable utility sketch is configured — a whole-feature problem.

    Distinct from a *box* being unrestorable, which is reported as that box's
    state rather than raised: "box 4 has no board" is a fact about the rig, not
    a failure of the command.
    """


@dataclass
class BoxBaseline:
    """What the sidecar believes about one box."""

    box: int
    state: str = "unknown"
    detail: str | None = None
    identifying: bool = False
    #: The sketch path believed to be *on the board*. Set by our own restores
    #: and by `note_flashed` for every other flash the app performs, so a
    #: session flash immediately invalidates the baseline belief rather than
    #: leaving us convinced the utility sketch is still there.
    believed: str | None = None
    #: A restore that failed. Sticky, so the ERROR→IDLE acknowledgement we
    #: perform below can't bounce straight back into another doomed flash;
    #: cleared only by a new board, new settings, or an explicit `force`.
    failed: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "box": self.box,
            "state": self.state,
            "detail": self.detail,
            "identifying": self.identifying,
        }


class UtilityBaseline:
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        ports: PortManager,
        discovery: Callable[[], Any],
        broadcast: Callable[[dict[str, Any]], Awaitable[None]],
        load_profile: Callable[[str], TaskProfile | None] = task_profile.load_profile,
    ) -> None:
        self._loop = loop
        self._ports = ports
        self._discovery = discovery
        self._broadcast = broadcast
        self._load_profile = load_profile

        self._settings = SidecarSettings()
        self._boxes: dict[int, BoxBaseline] = {
            box: BoxBaseline(box=box) for box in range(1, BOX_COUNT + 1)
        }
        self._held = False
        self._queue: set[int] = set()
        self._forced: set[int] = set()
        self._worker: asyncio.Task[None] | None = None
        # Identify is a multi-step serial conversation; two overlapping ones on
        # the same box would interleave their opens and closes.
        self._identify_lock = asyncio.Lock()
        # Passthrough this module opened, and must therefore close again. A box
        # the *user* opened in Debug Mode keeps its console.
        self._opened: set[int] = set()
        self._profile_cache: tuple[str, TaskProfile | None] | None = None

    # --- configuration ----------------------------------------------------

    def update_settings(self, settings: SidecarSettings) -> None:
        """Take the shell's settings; a changed sketch invalidates every belief."""
        changed = settings.utility_sketch_path != self._settings.utility_sketch_path
        self._settings = settings
        if changed:
            self._profile_cache = None
            for state in self._boxes.values():
                state.believed = None
                state.failed = False

    def hold(self) -> None:
        """Suspend restores — a confirmed session mapping owns the boxes."""
        if self._held:
            return
        self._held = True
        self._queue.clear()
        log.info("utility baseline held: a session mapping owns the boxes")
        self._loop.create_task(self._on_hold())

    def release(self) -> None:
        """The session is over; the rig goes back to baseline."""
        if not self._held:
            return
        self._held = False
        log.info("utility baseline released")
        for state in self._boxes.values():
            if state.state == "held":
                state.state = "unknown"
                state.detail = None

    async def _on_hold(self) -> None:
        await self.identify_all_off()
        await self.publish()

    async def stop(self) -> None:
        """Leave no box lit and no port held open on the way out."""
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        await self.identify_all_off()

    # --- beliefs ----------------------------------------------------------

    def note_flashed(self, box: int, sketch_path: str) -> None:
        """Record what a flash — any flash, from anywhere — actually put on a board."""
        state = self._boxes.get(box)
        if state is None:
            return
        state.believed = sketch_path
        entry = self._sketch_entry()
        if entry is not None and sketch_path == entry.path:
            state.state, state.detail, state.failed = "ready", None, False
        elif state.state == "ready":
            # The board now carries something else; say so rather than keep
            # claiming a baseline that a session flash has just overwritten.
            state.state, state.detail = "unknown", None

    def note_presence(self, hardware_ids: Iterable[str]) -> None:
        """Boards appeared or vanished — re-examine every box they map to."""
        present = set(hardware_ids)
        for box, state in self._boxes.items():
            bound = self._settings.hardware_id_for(box)
            if bound is not None and bound not in present:
                # A board that leaves takes our belief with it: the next one to
                # answer to this box number may be a different board entirely.
                state.believed = None
                state.failed = False
                if state.state in ("ready", "failed", "busy"):
                    state.state, state.detail = "unavailable", f"no board detected for box {box}"
            elif bound is not None and state.failed:
                # Replugging a board is the operator's usual "try again".
                state.failed = False

    # --- restores ---------------------------------------------------------

    def ensure(self, boxes: Iterable[int] | None = None, force: bool = False) -> None:
        """Queue a baseline restore. Returns immediately; work runs in the background.

        Deliberately fire-and-forget: flashing six boxes takes minutes, which
        no reply timeout should ever be asked to cover. `utility.updated`
        carries the progress.
        """
        if self._held or not self._settings.utility_sketch_path:
            # No baseline configured is a supported way to run the app, not a
            # degraded one — so it costs nothing and reports nothing.
            return
        targets = list(boxes) if boxes is not None else list(self._boxes)
        for box in targets:
            if box in self._boxes:
                self._queue.add(box)
                if force:
                    self._forced.add(box)
        if self._queue and self._worker is None:
            self._worker = self._loop.create_task(self._drain(), name="utility-baseline")

    async def _drain(self) -> None:
        try:
            while self._queue:
                box = min(self._queue)
                self._queue.discard(box)
                force = box in self._forced
                self._forced.discard(box)
                try:
                    await self._restore(box, force)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - one box must not stop the rest
                    log.exception("utility baseline restore failed for box %d", box)
            await self.publish()
        finally:
            self._worker = None

    async def _restore(self, box: int, force: bool) -> None:
        state = self._boxes[box]
        entry = self._sketch_entry()
        if entry is None:
            state.state, state.detail = "unavailable", self._unavailable_reason()
            return
        if self._held:
            state.state, state.detail = "held", "a session mapping owns this box"
            return
        if state.failed and not force:
            return

        try:
            self._ports.resolve_address(box)
        except (PortNotBound, BoardNotDetected) as exc:
            state.state, state.detail = "unavailable", str(exc)
            return

        port_state = self._ports.handler(box).state
        if port_state is not PortState.IDLE:
            # Not a fault: a console, a flash, or a run legitimately owns this
            # port, and taking it back would be the bug.
            state.state, state.detail = "busy", f"port is {port_state.value}"
            return
        if state.believed == entry.path and not force:
            state.state, state.detail = "ready", None
            return

        state.state, state.detail = "restoring", f"flashing {entry.name}"
        await self.publish()
        log.info("box %d: restoring utility baseline (%s)", box, entry.name)

        try:
            await self._ports.flash(
                box,
                entry.path,
                entry.name,
                getattr(self._discovery(), "libraries_path", None),
                lambda phase, stream, text: log.debug(
                    "box %d baseline %s/%s: %s", box, phase, stream, text.rstrip()
                ),
                suppress_passthrough_resume=True,
            )
        except Exception as exc:  # noqa: BLE001 - compile, upload, missing cli
            state.state = "failed"
            state.detail = str(exc)
            state.believed = None
            state.failed = True
            log.warning("box %d: utility baseline restore failed: %s", box, exc)
            # A failed flash leaves the port in ERROR, which the operator would
            # then have to acknowledge by hand — for work they never asked for.
            # Clear it: the fault is reported here, where it belongs, and
            # leaving six boxes needing an acknowledgement would make a broken
            # arduino-cli lock the rig instead of merely degrading it.
            self._clear_error(box)
            return

        state.believed = entry.path
        state.state, state.detail, state.failed = "ready", None, False

    def _clear_error(self, box: int) -> None:
        try:
            if self._ports.handler(box).state is PortState.ERROR:
                self._ports.acknowledge_error(box)
        except (IllegalTransition, PortNotBound) as exc:
            log.debug("box %d: couldn't clear the baseline error state: %s", box, exc)

    # --- identify ---------------------------------------------------------

    async def identify(self, box: int, on: bool) -> tuple[bool, dict[str, Any]]:
        """Ask one box to point at itself, per its profile's `identify` pair.

        Returns `(delivered, box_state)`. `delivered` is false whenever the
        signal can't be trusted to have reached the board — an unavailable box,
        a port someone else owns, or a board that never answered. The caller is
        expected to carry on without it: a placement walk that refuses to
        continue because a bulb didn't light is worse than one that tells the
        operator the box number.
        """
        entry = self._sketch_entry()
        if entry is None:
            raise UtilityUnavailable(self._unavailable_reason() or "no utility sketch configured")
        state = self._boxes.get(box)
        if state is None:
            raise UtilityUnavailable(f"box {box} does not exist")

        profile = self._profile()
        if profile is None or profile.identify is None:
            raise UtilityUnavailable(
                f"{entry.name} doesn't declare an identify command, so a box "
                "can't be asked to point at itself."
            )

        async with self._identify_lock:
            delivered = await self._identify_locked(state, entry, profile, on)
        await self.publish()
        return delivered, state.to_json()

    async def _identify_locked(
        self, state: BoxBaseline, entry: Any, profile: TaskProfile, on: bool
    ) -> bool:
        box = state.box
        assert profile.identify is not None
        command = profile.identify.on if on else profile.identify.off

        if not on:
            # Turning off must be best-effort to the point of never raising:
            # it runs on unmount and on session start, and a box that already
            # went away is a signal that is already off.
            delivered = self._send_quietly(box, command)
            self._close_if_ours(box)
            state.identifying = False
            return delivered

        if state.believed != entry.path:
            state.detail = state.detail or "box isn't at the utility baseline yet"
            return False

        try:
            opened = self._open_if_idle(box)
        except Exception as exc:  # noqa: BLE001 - absent, busy, permissions
            state.state, state.detail = "failed", f"couldn't open the port: {exc}"
            return False
        if opened is None:
            state.detail = f"port is {self._ports.handler(box).state.value}"
            return False

        handler = self._ports.handler(box)
        token = profile.telemetry.match if profile.telemetry else None
        if opened:
            # The open rebooted the board; wait for it to say anything at all
            # rather than guessing how long `setup()` takes.
            await self._await_line(handler, time.time(), None)

        since = time.time()
        try:
            self._ports.send(box, command)
        except (PortBusy, OSError) as exc:
            state.detail = f"couldn't send the identify command: {exc}"
            self._close_if_ours(box)
            return False
        state.identifying = True

        if token is None:
            # Nothing to listen for — the sketch declares no telemetry, so the
            # send is the only evidence there is.
            return True

        if await self._await_line(handler, since, token):
            state.detail = None
            return True

        # Sent, but the board never answered. Overwhelmingly this is a baud
        # mismatch — the sketch's own `baudRate` against the configured
        # `defaultBaud` — so name that rather than shrug.
        state.state = "failed"
        state.detail = (
            f"box {box} didn't answer at {self._ports_baud()} baud — check the "
            "default baud rate in Config."
        )
        state.identifying = False
        self._close_if_ours(box)
        return False

    async def identify_all_off(self) -> None:
        """Extinguish every box we lit. Never raises."""
        profile = self._profile()
        command = profile.identify.off if profile and profile.identify else None
        async with self._identify_lock:
            for state in self._boxes.values():
                if not state.identifying and state.box not in self._opened:
                    continue
                if command is not None:
                    self._send_quietly(state.box, command)
                self._close_if_ours(state.box)
                state.identifying = False

    def _open_if_idle(self, box: int) -> bool | None:
        """Open passthrough if we may. True = we opened it, False = already
        open by someone else, None = the port has another owner entirely."""
        handler = self._ports.handler(box)
        if handler.state is PortState.PASSTHROUGH:
            return False
        if handler.state is not PortState.IDLE:
            return None
        self._ports.open_passthrough(box)
        self._opened.add(box)
        return True

    def _close_if_ours(self, box: int) -> None:
        if box not in self._opened:
            return
        self._opened.discard(box)
        try:
            self._ports.close_passthrough(box)
        except Exception as exc:  # noqa: BLE001 - already gone is fine
            log.debug("box %d: couldn't close the identify console: %s", box, exc)

    def _send_quietly(self, box: int, command: str) -> bool:
        try:
            self._ports.send(box, command)
            return True
        except Exception as exc:  # noqa: BLE001 - wrong state, board gone
            log.debug("box %d: identify send failed: %s", box, exc)
            return False

    async def _await_line(self, handler: Any, since: float, token: str | None) -> bool:
        """Wait for a received line newer than `since`, optionally matching `token`.

        Reads the handler's scrollback rather than the batched `port.output`
        stream: this needs an answer within a couple of seconds, and the
        broadcast path is for the UI, not for control flow.
        """
        deadline = time.monotonic() + (BOOT_TIMEOUT_S if token is None else CONFIRM_TIMEOUT_S)
        while time.monotonic() < deadline:
            for line in _scrollback(handler):
                if line.dir != "rx" or line.ts < since:
                    continue
                if token is None or line.text.strip().startswith(token):
                    return True
            await asyncio.sleep(WAIT_TICK_S)
        return False

    def _ports_baud(self) -> int:
        return self._settings.default_baud

    # --- resolution -------------------------------------------------------

    def _sketch_entry(self) -> Any | None:
        """The configured sketch, as the current discovery knows it.

        Resolved against discovery every time rather than cached: the whole
        reason `port.flash` refuses an unknown path is that the Arduino
        Directory can move or be edited between one command and the next.
        """
        path = self._settings.utility_sketch_path
        if not path:
            return None
        sketches = getattr(self._discovery(), "sketches", [])
        entry = next((s for s in sketches if s.path == path), None)
        if entry is None:
            return None
        profile = self._profile()
        if profile is None or profile.kind != "utility":
            return None
        return entry

    def _profile(self) -> TaskProfile | None:
        path = self._settings.utility_sketch_path
        if not path:
            return None
        if self._profile_cache is not None and self._profile_cache[0] == path:
            return self._profile_cache[1]
        try:
            profile = self._load_profile(path)
        except task_profile.TaskProfileError as exc:
            log.warning("utility sketch %s has an unreadable task.json: %s", path, exc)
            profile = None
        self._profile_cache = (path, profile)
        return profile

    def _unavailable_reason(self) -> str | None:
        """Why the baseline can't operate at all, in words worth showing."""
        path = self._settings.utility_sketch_path
        if not path:
            return None  # not configured is a state, not a complaint
        sketches = getattr(self._discovery(), "sketches", [])
        if not any(s.path == path for s in sketches):
            return (
                "The hardware utility sketch isn't in the configured Arduino "
                "Directory any more — pick it again in Config."
            )
        profile = self._profile()
        if profile is None:
            return (
                "The hardware utility sketch has no readable task.json, so the "
                "app can't tell what it can be asked to do."
            )
        if profile.kind != "utility":
            return (
                f"{profile.task_name} is a {profile.kind} sketch — the hardware "
                "utility sketch must declare `kind: \"utility\"`."
            )
        return None

    # --- status -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        entry = self._sketch_entry()
        profile = self._profile()
        return {
            "configured": bool(self._settings.utility_sketch_path),
            "sketchPath": self._settings.utility_sketch_path,
            "sketchName": entry.name if entry is not None else None,
            "canIdentify": entry is not None and profile is not None and profile.identify is not None,
            "held": self._held,
            "message": self._unavailable_reason(),
            "boxes": [state.to_json() for _, state in sorted(self._boxes.items())],
        }

    async def publish(self) -> None:
        from .protocol import Evt, event

        await self._broadcast(event(Evt.UTILITY_UPDATED, self.status()))


def _scrollback(handler: Any) -> list[Any]:
    """Snapshot a handler's ring buffer, tolerating the reader thread.

    The ring is a `deque` the port's reader thread appends to, and copying one
    mid-append can raise. Retrying costs a microsecond; the alternative is a
    rare crash inside a wait loop.
    """
    for _ in range(3):
        try:
            return handler.scrollback()
        except RuntimeError:
            continue
    return []
