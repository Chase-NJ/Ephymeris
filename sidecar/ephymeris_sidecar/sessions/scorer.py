"""The live scorer: one child process that scores every box's spine run
(`ARCHITECTURE.md#the-live-scorer`).

A spine run's live numbers are a whole replay of its stream so far
(`analytics/stream/live.py`'s `scored`), tens of milliseconds at a thousand
trials. On a thread of the sidecar that work holds the GIL every session thread
needs to write and fsync its next strobe (`DATA.md#written-live`), so it runs
here, in a process of its own, where it can hold nothing the sidecar needs.

- **One process for every box.** Each run is a key. The sidecar sends a run's
  header once, then only the strobes since its last request, so a request costs
  what arrived since the last one, and the child keeps the stream.
- **Coalesced.** Requests wait in one slot per key on the sidecar's side, merged
  while the child is busy, and the child drains every request before it scores,
  then scores each key once, at its latest count. A slow score drops the stale
  requests behind it; nothing queues.
- **Fenced.** If the child cannot start or dies, every listener is told the
  scorer is down, once, and every later request is answered the same way. The
  live numbers show unavailable; the token, the strobes and the session never
  depend on it. It is never restarted.
- **Never waited on.** Requests are handed to a sender thread; results come back
  on a reader thread. Neither the session thread nor the loop blocks on the pipe,
  and `stop` kills the child without joining it.
- **It dies with the sidecar.** It exits when its request pipe closes, which a
  dead sidecar's does, and when its parent changes; the sidecar kills it on the
  way out (`ARCHITECTURE.md#process-lifecycle`). It is a `spawn` child, so the
  frozen build re-enters through `multiprocessing.freeze_support()`
  (`packaging/entry.py`).
"""

from __future__ import annotations

import atexit
import logging
import multiprocessing
import multiprocessing.util  # its atexit reaper first, so ours (below) runs before it
import os
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

Result = Callable[[int, dict[str, Any]], None]
Down = Callable[[str], None]

#: How often the child looks at its parent while its pipe is quiet.
_PARENT_POLL_S = 1.0

#: Set as the interpreter exits, before `multiprocessing` reaps its children
#: (atexit runs in reverse): a scorer killed then is not a scorer that failed.
_exiting = threading.Event()
atexit.register(_exiting.set)


def _start_process(target: Callable[..., None], *args: Any) -> multiprocessing.process.BaseProcess:
    """Start `target` in a fresh interpreter (`spawn` on every platform, so the
    frozen Windows build and a dev run behave alike)."""
    process = multiprocessing.get_context("spawn").Process(
        target=target, args=args, name="ephymeris-live-scorer", daemon=True)
    process.start()
    return process


class LiveScorer:
    """The sidecar's handle on the live scoring process. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        #: key -> (header or None, strobes since the last send, count)
        self._waiting: dict[str, tuple[dict[str, Any] | None, list[list[int]], int]] = {}
        self._forget: list[str] = []
        self._listeners: dict[str, tuple[Result, Down]] = {}
        self._down: str | None = None
        self._stopped = False
        self._process: multiprocessing.process.BaseProcess | None = None
        self._started = threading.Event()
        self._requests: Any = None  # the sidecar's end of the request pipe
        self._sender: threading.Thread | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    # --- the sidecar's side -------------------------------------------------------

    def submit(self, key: str, header: dict[str, Any] | None, strobes: list[list[int]], count: int,
               *, on_result: Result, on_down: Down) -> None:
        """Ask for run `key` scored at its first `count` strobes. `header` comes
        with a run's first request; `strobes` are those since its last. Never
        blocks: the answer comes to `on_result(count, fields)`, or `on_down(reason)`
        if the scorer is down, on a thread of the scorer's."""
        with self._lock:
            down = self._down
            if down is None and not self._stopped:
                self._listeners[key] = (on_result, on_down)
                had = self._waiting.get(key)
                if had is not None:
                    header = had[0] if had[0] is not None else header
                    strobes = had[1] + list(strobes)
                self._waiting[key] = (header, list(strobes), count)
                self._ensure_sender()
                self._wake.notify()
                return
        _call(on_down, down or "the live scorer has stopped")

    def forget(self, key: str) -> None:
        """Run `key` is over: drop its stream from the child."""
        with self._lock:
            self._listeners.pop(key, None)
            self._waiting.pop(key, None)
            if self._down is None and self._sender is not None:
                self._forget.append(key)
                self._wake.notify()

    def stop(self) -> None:
        """Kill the child, without waiting for it. On the sidecar's way out."""
        with self._lock:
            self._stopped = True
            self._wake.notify()
            process = self._process
        if process is not None and process.is_alive():
            try:
                process.kill()
            except Exception:  # noqa: BLE001 - it is gone either way
                pass

    def _ensure_sender(self) -> None:
        if self._sender is None:
            self._sender = threading.Thread(target=self._send_loop, name="live-scorer-send", daemon=True)
            self._sender.start()

    def _send_loop(self) -> None:
        try:
            requests, results, process = self._start()
        except Exception as exc:  # noqa: BLE001 - fenced: the numbers go, nothing else
            self._fail(f"the live scorer could not start: {exc}")
            return
        threading.Thread(target=self._read_loop, args=(results,), name="live-scorer-read",
                         daemon=True).start()
        while True:
            with self._lock:
                while not (self._waiting or self._forget or self._stopped):
                    self._wake.wait()
                if self._stopped or self._down is not None:
                    return
                waiting, self._waiting = self._waiting, {}
                forget, self._forget = self._forget, []
            try:
                for key in forget:
                    requests.send(("forget", key))
                for key, (header, strobes, count) in waiting.items():
                    requests.send(("score", key, header, strobes, count))
            except Exception as exc:  # noqa: BLE001
                self._fail(f"the live scorer went away: {exc}")
                return

    def _start(self) -> tuple[Any, Any, multiprocessing.process.BaseProcess]:
        context = multiprocessing.get_context("spawn")
        req_read, req_write = context.Pipe(duplex=False)
        res_read, res_write = context.Pipe(duplex=False)
        process = _start_process(serve, req_read, res_write, os.getpid())
        # Our copies of the child's ends: closed, so each side sees the other go.
        req_read.close()
        res_write.close()
        with self._lock:
            self._process, self._requests = process, req_write
        self._started.set()
        if self._stopped:
            self.stop()
        return req_write, res_read, process

    def _read_loop(self, results: Any) -> None:
        while True:
            try:
                kind, key, count, fields = results.recv()
            except Exception:  # noqa: BLE001 - EOF: the child is gone
                self._fail("the live scorer stopped, so live numbers are unavailable")
                return
            with self._lock:
                listener = self._listeners.get(key)
            if listener is not None and kind == "scored":
                _call(listener[0], count, fields)

    def _fail(self, reason: str) -> None:
        with self._lock:
            if self._down is not None or self._stopped or _exiting.is_set():
                return
            self._down = reason
            listeners = list(self._listeners.values())
            self._waiting.clear()
            self._wake.notify()
        log.warning("%s", reason)
        for _, on_down in listeners:
            _call(on_down, reason)

    # --- for the tests ------------------------------------------------------------

    def wait_started_for_test(self, timeout: float = 20.0) -> None:
        assert self._started.wait(timeout), "the scorer never started"

    def kill_for_test(self) -> None:
        self.wait_started_for_test()
        assert self._process is not None
        self._process.kill()

    def close_pipe_for_test(self) -> None:
        """What the sidecar's death does to the child's pipe."""
        with self._lock:
            self._stopped = True
            self._wake.notify()
            requests = self._requests
        requests.close()

    def process_exited_for_test(self, timeout: float) -> bool:
        assert self._process is not None
        self._process.join(timeout)
        return not self._process.is_alive()


def _call(fn: Callable[..., None], *args: Any) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("a live scorer listener failed")


# --- the child ----------------------------------------------------------------------


def serve(requests: Any, results: Any, parent: int) -> None:
    """The child's whole life: read requests, coalesce, score, answer; exit when
    the sidecar goes away. Imports only the pure scorer."""
    from ..analytics.stream import live

    streams: dict[str, dict[str, Any]] = {}
    while True:
        try:
            while not requests.poll(_PARENT_POLL_S):
                if os.getppid() != parent:
                    return
            batch = [requests.recv()]
            while requests.poll(0):
                batch.append(requests.recv())
        except (EOFError, OSError):
            return
        due: dict[str, int] = {}
        for message in batch:
            if message[0] == "forget":
                streams.pop(message[1], None)
                due.pop(message[1], None)
                continue
            _, key, header, strobes, count = message
            if header is not None:
                streams[key] = {**header, "ts_data": []}
            stream = streams.get(key)
            if stream is None:
                continue
            stream["ts_data"].extend(strobes)
            due[key] = count
        for key, count in due.items():
            stream = streams[key]
            try:
                fields = live.fields(live.scored({**stream, "ts_data": stream["ts_data"][:count]}))
            except Exception as exc:  # noqa: BLE001 - one run's failure is that run's
                fields = {"status": "unavailable", "detail": f"the live scorer failed: {exc!r}"}
            try:
                results.send(("scored", key, count, fields))
            except (EOFError, OSError):
                return
