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
- **the check and the numbers** (`live.scored`), run in the loop's executor and
  coalesced: while one runs, another request only marks it due again;
- **the payload** `session.replay` carries, broadcast whenever it changes and
  replayed to a client that connects (`ARCHITECTURE.md#replay-on-connect`).

Per strobe the session thread does `LiveReplay.feed` and `at`, a few
microseconds, and nothing here can raise into it: a failure is logged.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable

from ..analytics.stream import live
from ..analytics.stream.spine import SpineDecodeError

log = logging.getLogger(__name__)

#: How long after a timer runs out on the board's estimated clock its state is
#: reported, so an edge that beat it on the board, still on its way here, wins.
GRACE_MS = 30

#: `LiveReplay.status` values (`LiveReplay` on the wire).
REPLAYING, DIVERGED, UNREPLAYABLE, ENDED = "replaying", "diverged", "unreplayable", "ended"


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
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.box = box
        self._animal_id = animal_id
        self._loop = loop
        self._publish = publish
        self._clock = clock
        self._lock = threading.Lock()
        self._status = REPLAYING
        self._detail: str | None = None
        self._replay: live.LiveReplay | None = None
        try:
            self._replay = live.LiveReplay(header)
        except SpineDecodeError as exc:
            self._status, self._detail = UNREPLAYABLE, f"replay cannot run this spine run: {exc}"
        self._view: live.View | None = self._replay.at(0) if self._replay is not None else None
        self._anchor = (0, clock())  # (board tick, host seconds) of the last strobe
        self._score: live.LiveScore | None = None
        #: How many strobes `_score` read: an ended run is `ended` only once it read them all.
        self._scored = 0
        self._timer: asyncio.TimerHandle | None = None
        self._scoring = False
        self._again = False
        self._closed = False
        self._tasks: set[asyncio.Future] = set()
        self._payload = self._build()
        loop.call_soon_threadsafe(self._changed, True, False)

    # --- the session thread --------------------------------------------------

    def feed(self, code: int, ts: int) -> None:
        """One strobe, already on disk. Called on the port's session thread."""
        try:
            with self._lock:
                if self._replay is None or self._closed:
                    return
                fed = self._replay.feed(code, ts)
                self._anchor = (ts, self._clock())
                moved = self._move(self._replay.at(ts))
            self._loop.call_soon_threadsafe(self._changed, moved, fed.check)
        except Exception:  # noqa: BLE001 - the live view never costs the session
            log.exception("box %d: live replay could not take a strobe", self.box)

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
            if self._replay is None or self._closed or self._replay.ended:
                return
            tick, host = self._anchor
            board = tick + int((self._clock() - host) * 1000) - GRACE_MS
            moved = self._move(self._replay.at(max(board, tick)))
        self._changed(moved, False)

    def _score_soon(self) -> None:
        if self._replay is None or self._status == DIVERGED:
            return
        if self._scoring:
            self._again = True
            return
        self._scoring = True
        task = asyncio.ensure_future(self._score_now())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _score_now(self) -> None:
        assert self._replay is not None
        try:
            while True:
                self._again = False
                with self._lock:
                    document = self._replay.document()
                score = await self._loop.run_in_executor(None, live.scored, document)
                self._take(score, len(document["ts_data"]))
                if not self._again:
                    return
        except Exception:  # noqa: BLE001
            log.exception("box %d: the live trial table could not be read", self.box)
        finally:
            self._scoring = False

    def _take(self, score: live.LiveScore, read: int) -> None:
        self._scored = read
        if score.status == "ok":
            self._score = score
        else:
            # Never left standing: a stream replay does not reproduce has no
            # numbers, and its token no phase (`ANALYTICS.md#diverged-and-unreplayable-runs`).
            self._status = DIVERGED if score.status == "diverged" else UNREPLAYABLE
            self._detail = score.detail
            self._score = score
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self._emit()

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
            status = self._status
            over = self._closed or (self._replay is not None and self._replay.ended)
            # Ended, with numbers that are the whole run's: until its last
            # score lands it is still replaying, with no token.
            if status == REPLAYING and over and self._replay is not None \
                    and self._scored == self._replay.received:
                status = ENDED
            view = self._view if status == REPLAYING and not over else None
        score = self._score if status in (REPLAYING, ENDED) else None
        trials = score.trials if score is not None else ()
        complete = [t for t in trials if t.complete]
        open_ = trials[-1] if trials and not trials[-1].complete and status == REPLAYING else None
        divergence = self._score.divergence if self._score is not None and status == DIVERGED else None
        return {
            "box": self.box,
            "animalId": self._animal_id,
            "status": status,
            "detail": self._detail if status in (DIVERGED, UNREPLAYABLE) else None,
            "state": view.state if view is not None else None,
            "phase": view.phase if view is not None else None,
            "row": view.row if view is not None else None,
            "provisional": view.provisional if view is not None else False,
            "trials": len(complete),
            "current": open_.to_json() if open_ is not None else None,
            "last": complete[-1].to_json() if complete else None,
            "metrics": [m.to_json() for m in score.metrics] if score is not None else [],
            "overall": score.overall.to_json() if score is not None and score.overall is not None else None,
            "replay": score.score.to_json() if score is not None and score.score is not None else None,
            "divergence": divergence.to_json() if divergence is not None else None,
        }
