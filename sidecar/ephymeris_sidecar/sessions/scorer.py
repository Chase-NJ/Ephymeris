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
- **It yields the CPU.** The child lowers its own priority at start-up (`os.nice`
  on POSIX, `BELOW_NORMAL_PRIORITY_CLASS` on Windows), so on a machine with fewer
  free cores than busy threads the session threads run first. It scores a run at
  most once per `SCORE_INTERVAL_S`, and rests after each score as long as the score
  took, so it uses at most about half a core however many boxes ask.
- **Never waited on.** Requests are handed to a sender thread; results come back
  on a reader thread. Neither the session thread nor the loop blocks on the pipe,
  and `stop` kills the child without joining it. A child seen dead is reaped on
  the reader thread, so it is never left a zombie.
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
import multiprocessing.connection
import multiprocessing.util  # its atexit reaper first, so ours (below) runs before it
import os
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

Result = Callable[[int, dict[str, Any]], None]
Down = Callable[[str], None]

#: How often the child looks at its parent while its pipe is quiet.
_PARENT_POLL_S = 1.0

#: The least time between two scores of one run. A live number a quarter of a
#: second old is as good as a new one to an operator, and the replay it saves
#: is the CPU a session thread may need.
SCORE_INTERVAL_S = 0.25

#: How far below the sidecar the child runs on POSIX (`os.nice`).
NICENESS = 10
#: Windows' `BELOW_NORMAL_PRIORITY_CLASS`.
_BELOW_NORMAL = 0x4000

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
        #: The child has imported the scorer and lowered its priority.
        self._ready = threading.Event()
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
            threading.Thread(target=self._reap, name="live-scorer-reap", daemon=True).start()

    def warm(self) -> None:
        """Start the child now, from the sender thread, if it is not already up:
        when a mapping holds a spine run, so the interpreter it starts is paid
        for during set-up, never while a box is strobing. Never blocks."""
        with self._lock:
            if self._down is None and not self._stopped:
                self._ensure_sender()

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
        # Below us before it has imported anything: starting an interpreter is
        # the costliest thing it does unprompted. It lowers itself again (and on
        # Windows only then) once it runs.
        if hasattr(os, "setpriority") and process.pid is not None:
            try:
                _below(process.pid, 0)
            except OSError:
                pass
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
                self._reap()
                self._fail("the live scorer stopped")
                return
            if kind == "ready":
                self._ready.set()
                continue
            with self._lock:
                listener = self._listeners.get(key)
            if listener is not None and kind == "scored":
                _call(listener[0], count, fields)

    def _reap(self) -> None:
        """Collect a dead child's exit status, on the reader thread: it closed its
        pipe, so it is exiting, and this never holds anything the sidecar needs."""
        process = self._process
        if process is None:
            return
        for _ in range(50):
            process.join(0.1)
            if process.exitcode is not None:
                return

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

    def wait_ready_for_test(self, timeout: float = 30.0) -> None:
        assert self._ready.wait(timeout), "the scorer never said it was ready"

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

    def exitcode_for_test(self) -> int | None:
        """The child's exit status once reaped, without reaping it here."""
        assert self._process is not None
        return self._process._popen.returncode if self._process._popen is not None else None  # noqa: SLF001

    def process_exited_for_test(self, timeout: float) -> bool:
        """Whether the child exits within `timeout`, read from its sentinel, never
        by reaping it here: the scorer's own reaper may be collecting it at the
        same moment, and a second `waitpid` would find nothing and read a dead
        child as alive."""
        assert self._process is not None
        return bool(multiprocessing.connection.wait([self._process.sentinel], timeout))


def _call(fn: Callable[..., None], *args: Any) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        log.exception("a live scorer listener failed")


# --- the child ----------------------------------------------------------------------


def _below(pid: int, parent: int) -> None:
    """Put POSIX process `pid` `NICENESS` below `parent`. Absolute, so the
    parent's call and the child's own agree rather than add up."""
    want = min(os.getpriority(os.PRIO_PROCESS, parent) + NICENESS, 19)
    if os.getpriority(os.PRIO_PROCESS, pid) < want:
        os.setpriority(os.PRIO_PROCESS, pid, want)


def _lower_priority(parent: int) -> None:
    """Run below the sidecar, so its session threads get the CPU first."""
    try:
        if hasattr(os, "setpriority"):
            _below(0, parent)
        elif os.name == "nt":
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), _BELOW_NORMAL)
    except Exception:  # noqa: BLE001 - a scorer at normal priority still scores
        log.warning("the live scorer could not lower its priority", exc_info=True)


def serve(requests: Any, results: Any, parent: int) -> None:
    """The child's whole life: read requests, coalesce, score, answer; exit when
    the sidecar goes away. Imports only the pure scorer."""
    import time

    from ..analytics.stream import live

    _lower_priority(parent)
    try:
        results.send(("ready", None, 0, None))
    except (EOFError, OSError):
        return
    streams: dict[str, dict[str, Any]] = {}
    due: dict[str, int] = {}  # run -> the count its latest request asked for
    last: dict[str, float] = {}  # run -> when it was last scored
    while True:
        now = time.monotonic()
        ready = [k for k in due if now - last.get(k, 0.0) >= SCORE_INTERVAL_S]
        if ready:
            wait = 0.0
        elif due:
            wait = min(SCORE_INTERVAL_S - (now - last[k]) for k in due)
        else:
            wait = _PARENT_POLL_S
        try:
            batch = []
            if requests.poll(wait):
                batch.append(requests.recv())
                while requests.poll(0):
                    batch.append(requests.recv())
            elif not due and os.getppid() != parent:
                return
        except (EOFError, OSError):
            return
        for message in batch:
            if message[0] == "forget":
                streams.pop(message[1], None)
                due.pop(message[1], None)
                last.pop(message[1], None)
                continue
            _, key, header, strobes, count = message
            if header is not None:
                streams[key] = {**header, "ts_data": []}
            stream = streams.get(key)
            if stream is None:
                continue
            stream["ts_data"].extend(strobes)
            due[key] = count
        now = time.monotonic()
        for key in [k for k in due if now - last.get(k, 0.0) >= SCORE_INTERVAL_S]:
            count = due.pop(key)
            stream = streams[key]
            began = time.monotonic()
            try:
                fields = live.fields(live.scored({**stream, "ts_data": stream["ts_data"][:count]}))
            except Exception as exc:  # noqa: BLE001 - one run's failure is that run's
                fields = {"status": "unavailable", "detail": f"the live scorer failed: {exc!r}"}
            took = time.monotonic() - began
            last[key] = time.monotonic()
            try:
                results.send(("scored", key, count, fields))
            except (EOFError, OSError):
                return
            # Rest as long as the score took: at most about half a core, however
            # many boxes are asking.
            time.sleep(took)
