"""One box's live replay: a running spine run, replayed as its strobes arrive
(`ARCHITECTURE.md#live-session-views`, `ANALYTICS.md#live-scoring`).

`analytics/stream/live.py` is the replay; this is its place in a running
session. The runner makes one per spine run when the board's handshake resolves,
and hands it every strobe **after** the strobe is fsync'd (`DATA.md#crash-safety`),
on the port's session thread. What it owns:

- **the lock** between that thread, which feeds it, and the loop, which reads it;
- **the board's clock**, estimated from the last strobe's tick and the host's
  monotonic time when it arrived, so a state's timer is reported when it runs
  out on the board even though nothing is strobed then, marked `provisional`
  until a strobe confirms it. One loop timer per box, re-armed after every
  strobe; the board is never polled;
- **its requests to the live scorer** (`sessions/scorer.py`), the process that
  checks and scores the stream so far: one outstanding at a time, carrying only
  the strobes since the last. While the scorer is down the token carries on and
  the numbers say they are unavailable;
- **the payload** `session.replay` carries, broadcast whenever it changes and
  replayed to a client that connects (`ARCHITECTURE.md#replay-on-connect`).

Per strobe the session thread does `LiveReplay.feed` and `at`, after the fsync:
a median of 44–67 µs and at most 0.9 ms on a running sidecar. Nothing here can
raise into it. A feed that fails anyway
leaves the replay `unavailable` for the rest of the run: never a clean end with
numbers read from a stream it did not take.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from typing import Any, Awaitable, Callable

from ..analytics.stream import live
from ..analytics.stream.spine import SpineDecodeError
from .scorer import LiveScorer

log = logging.getLogger(__name__)

#: How long after a timer runs out on the board's estimated clock its state is
#: reported, so an edge that beat it on the board, still on its way here, wins.
GRACE_MS = 30

#: `LiveReplayStatus` values (`LiveReplay` on the wire).
REPLAYING, DIVERGED, UNREPLAYABLE, UNAVAILABLE, ENDED = (
    "replaying", "diverged", "unreplayable", "unavailable", "ended")


class BoxReplay:
    """One running spine run's live replay, and what `session.replay` says of it."""

    def __init__(
        self,
        box: int,
        animal_id: str,
        header: dict[str, Any],
        *,
        loop: asyncio.AbstractEventLoop,
        publish: Callable[[dict[str, Any]], Awaitable[None]],
        scorer: LiveScorer,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.box = box
        self.key = uuid.uuid4().hex
        self._animal_id = animal_id
        self._loop = loop
        self._publish = publish
        self._scorer = scorer
        self._clock = clock
        self._lock = threading.Lock()
        self._header = header
        self._status = REPLAYING
        self._detail: str | None = None
        self._replay: live.LiveReplay | None = None
        try:
            self._replay = live.LiveReplay(header)
        except SpineDecodeError as exc:
            self._status, self._detail = UNREPLAYABLE, f"replay cannot run this spine run: {exc}"
        self._view: live.View | None = self._replay.at(0) if self._replay is not None else None
        self._anchor = (0, clock())  # (board tick, host seconds) of the last strobe
        #: The scorer's latest answer (`live.fields`), and how many strobes it read.
        self._fields: dict[str, Any] | None = None
        self._scored = 0
        #: Strobes sent to the scorer so far.
        self._sent = 0
        #: Why the live numbers are unavailable: the scorer is down.
        self._unavailable: str | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._scoring = False
        self._again = False
        self._closed = False
        self._tasks: set[asyncio.Future] = set()
        #: What the strobes since the loop last looked asked of it, and whether
        #: a look is already scheduled: one hand-off per loop turn, however
        #: many strobes arrive in it.
        self._pending_moved = False
        self._pending_check = False
        self._handed = False
        self._payload = self._build()
        loop.call_soon_threadsafe(self._changed, True, False)

    # --- the session thread --------------------------------------------------

    def feed(self, code: int, ts: int) -> None:
        """One strobe, already on disk. Called on the port's session thread."""
        try:
            with self._lock:
                if self._replay is None or self._closed or self._status != REPLAYING:
                    return
                fed = self._replay.feed(code, ts)
                self._anchor = (ts, self._clock())
                self._pending_moved |= self._move(self._replay.at(ts))
                self._pending_check |= fed.check
                hand = not self._handed
                self._handed = True
            if hand:
                self._loop.call_soon_threadsafe(self._take_pending)
        except Exception as exc:  # noqa: BLE001 - the live view never costs the session
            log.exception("box %d: live replay could not take a strobe", self.box)
            self._failed(f"the live replay could not take a strobe: {exc!r}")

    def _failed(self, reason: str) -> None:
        """The replay missed a strobe, so nothing it says is the run's any more."""
        try:
            with self._lock:
                self._status, self._detail = UNAVAILABLE, reason
        except Exception:  # noqa: BLE001
            log.exception("box %d: couldn't mark its live replay failed", self.box)
        self._post(self._changed, True, False)

    def _post(self, fn: Callable[..., None], *args: Any) -> None:
        """Run `fn` on the loop, from any thread; nothing once the loop is gone."""
        try:
            self._loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:  # the loop closed: the sidecar is going
            pass

    # --- the loop ------------------------------------------------------------

    def close(self) -> None:
        """The run ended: check and score it once more, and stop the clock. On the loop."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._changed(True, True)

    def payload(self) -> dict[str, Any]:
        """What `session.replay` says now."""
        return self._payload

    def _move(self, view: live.View) -> bool:
        """Take a new view, under the lock; whether what is reported moved."""
        before = self._view
        self._view = view
        return before is None or (view.state, view.phase, view.row, view.provisional) != \
            (before.state, before.phase, before.row, before.provisional)

    def _take_pending(self) -> None:
        """What the strobes since the last look asked for, on the loop."""
        with self._lock:
            moved, check = self._pending_moved, self._pending_check
            self._pending_moved = self._pending_check = self._handed = False
        self._changed(moved, check)

    def _changed(self, moved: bool, check: bool) -> None:
        if moved:
            self._emit()
        if check:
            self._score_soon()
        self._arm()

    def _arm(self) -> None:
        """One timer, for when the resting state's timer runs out on the board."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        with self._lock:
            if self._status != REPLAYING or self._closed or self._view is None or self._view.due is None \
                    or (self._replay is not None and self._replay.ended):
                return
            tick, host = self._anchor
            delay = (self._view.due - tick + GRACE_MS) / 1000 - (self._clock() - host)
        self._timer = self._loop.call_later(max(0.0, delay), self._on_due)

    def _on_due(self) -> None:
        self._timer = None
        with self._lock:
            if self._replay is None or self._closed or self._replay.ended or self._status != REPLAYING:
                return
            tick, host = self._anchor
            board = tick + int((self._clock() - host) * 1000) - GRACE_MS
            moved = self._move(self._replay.at(max(board, tick)))
        self._changed(moved, False)

    # --- the scorer ------------------------------------------------------------

    def _score_soon(self) -> None:
        """Ask the scorer for the stream so far: at most one request out at a
        time, and only the strobes since the last."""
        if self._replay is None or self._status != REPLAYING or self._unavailable is not None:
            return
        if self._scoring:
            self._again = True
            return
        self._scoring = True
        with self._lock:
            count = self._replay.received
            strobes = self._replay.strobes_since(self._sent)
            header = self._header if self._sent == 0 else None
            self._sent = count
        self._scorer.submit(self.key, header, strobes, count,
                            on_result=self._from_scorer, on_down=self._scorer_down)

    def _from_scorer(self, count: int, fields: dict[str, Any]) -> None:
        """On the scorer's reader thread."""
        self._post(self._take, count, fields)

    def _scorer_down(self, reason: str) -> None:
        """On the scorer's threads, or the loop."""
        self._post(self._down, reason)

    def _take(self, count: int, fields: dict[str, Any]) -> None:
        self._scoring = False
        if self._status != REPLAYING:
            return
        self._scored = count
        status = fields.get("status")
        if status == "ok":
            self._fields = fields
        else:
            # Never left standing: a stream replay does not reproduce has no
            # numbers, and its token no phase (`ANALYTICS.md#diverged-and-unreplayable-runs`).
            with self._lock:
                self._status = status if status in (DIVERGED, UNREPLAYABLE) else UNAVAILABLE
                self._detail = fields.get("detail")
            self._fields = fields
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._emit()
        if self._again:
            self._again = False
            self._score_soon()

    def _down(self, reason: str) -> None:
        self._scoring = False
        self._again = False
        self._unavailable = reason
        self._fields = None
        self._emit()

    # --- the payload -------------------------------------------------------------

    def _emit(self) -> None:
        payload = self._build()
        if self._published and payload == self._payload:
            return
        self._payload = payload
        self._published = True
        task = asyncio.ensure_future(self._publish(payload))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    #: Whether `_payload` has been broadcast: the first is, even unchanged.
    _published = False

    def _build(self) -> dict[str, Any]:
        with self._lock:
            status, detail = self._status, self._detail
            over = self._closed or (self._replay is not None and self._replay.ended)
            # Ended once its numbers are the whole run's, or once no numbers
            # are coming: until then it is still replaying, with no token.
            if status == REPLAYING and over and self._replay is not None \
                    and (self._scored == self._replay.received or self._unavailable is not None):
                status = ENDED
            view = self._view if status == REPLAYING and not over else None
        numbers = self._fields if status in (REPLAYING, ENDED) and self._unavailable is None else None
        divergence = self._fields.get("divergence") if self._fields is not None and status == DIVERGED else None
        return {
            "box": self.box,
            "animalId": self._animal_id,
            "status": status,
            "detail": detail if status in (DIVERGED, UNREPLAYABLE, UNAVAILABLE) else None,
            "state": view.state if view is not None else None,
            "phase": view.phase if view is not None else None,
            "row": view.row if view is not None else None,
            "provisional": view.provisional if view is not None else False,
            "unavailable": self._unavailable if status in (REPLAYING, ENDED) else None,
            "trials": numbers["trials"] if numbers is not None else 0,
            "current": numbers["current"] if numbers is not None and status == REPLAYING else None,
            "last": numbers["last"] if numbers is not None else None,
            "metrics": numbers["metrics"] if numbers is not None else [],
            "overall": numbers["overall"] if numbers is not None else None,
            "replay": numbers["replay"] if numbers is not None else None,
            "divergence": divergence,
        }
