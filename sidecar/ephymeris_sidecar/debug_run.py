"""Live metrics for a task started by hand from Debug Mode.

A session scores its strobes as they arrive (`sessions/runner.py` feeding a
`MetricSet`) and Mission Control draws the result. A task flashed and started
from Debug Mode produced the same strobes and showed none of that: the console
is `PASSTHROUGH`, which has no runner, so the only readout of a task being
bench-tested was a scrolling column of numbers.

This is the smallest thing that closes the gap, and what it deliberately is NOT
matters as much as what it is:

* **It scores with `MetricSet` and nothing else.** The rolling P(hit) definition
  is the lab's scientific output and has three documented traps (`tasks/
  metrics.py`, `analytics/derive.py`); a second implementation for the bench
  would drift from the one that scores real sessions, and the drift would read
  as one of the two being wrong without saying which. Same class, same
  boundary-code union, fed the same way.
* **It records nothing.** No writer, no `.tsv`, no run row, no `SEED`. A Debug
  run is not data (`ARCHITECTURE.md#invariants`: passthrough output is never persisted),
  and nothing here can make it look like data later.
* **It is armed only by `port.sendStart`**, because that is the one moment the
  sidecar knows which sketch — and so which Task Profile — is on the board. A
  `START` typed into the console by hand still starts the task; it just is not
  scored, since there would be nothing to score it against.

It ends the way a session does: on the profile's `END_SESSION` strobe, which
the board emits itself at the next trial boundary after a `STOP` line. The host
never sends that strobe — it cannot; a strobe is something only firmware emits
— so Debug Mode's **End** button sends `STOP`, exactly as Mission Control's
does, and the end is *observed* here rather than assumed. A port that leaves
`PASSTHROUGH` for any reason (console closed, reset, flash) also ends it, since
the board either rebooted or stopped being listened to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .ports.handler import STROBE_RE, OutputLine
from .tasks.metrics import MetricSet
from .tasks.profile import TaskProfile


@dataclass
class _DebugRun:
    metrics: MetricSet
    end_code: int | None


class DebugRuns:
    """At most one hand-started run per box, scored as its strobes arrive."""

    def __init__(self) -> None:
        self._runs: dict[int, _DebugRun] = {}

    def running(self, box: int) -> bool:
        return box in self._runs

    def arm(self, box: int, profile: TaskProfile | None) -> dict[str, Any]:
        """A `START` just went out for `profile`'s sketch. Returns the opening payload.

        Re-arming replaces the run rather than continuing it: a second `START`
        is a fresh count, the same rule a restarted box follows in a session.
        A profile-less sketch is armed too — it has no metrics, but the client
        still needs `running` to offer **End**.
        """
        run = _DebugRun(
            metrics=MetricSet(profile),
            end_code=profile.end_code if profile is not None else None,
        )
        self._runs[box] = run
        return _payload(box, True, run)

    def offer(self, box: int, lines: Iterable[OutputLine]) -> dict[str, Any] | None:
        """Feed one `port.output` batch. Returns a payload if anything changed.

        One payload per batch, not per strobe: the batch is already the ~20 Hz
        unit the console is delivered in, every payload carries the whole
        metric set, and a client can only draw the latest one anyway.
        """
        run = self._runs.get(box)
        if run is None:
            return None
        changed = False
        for line in lines:
            if line.dir != "rx":
                continue
            match = STROBE_RE.match(line.text.strip())
            if match is None:
                continue
            code = int(match.group(1))
            run.metrics.offer(code)
            changed = True
            if run.end_code is not None and code == run.end_code:
                del self._runs[box]
                return _payload(box, False, run)
        return _payload(box, True, run) if changed and not run.metrics.empty else None

    def drop(self, box: int) -> dict[str, Any] | None:
        """The port stopped being a console. Returns the closing payload, if any."""
        run = self._runs.pop(box, None)
        return _payload(box, False, run) if run is not None else None


def _payload(box: int, running: bool, run: _DebugRun) -> dict[str, Any]:
    return {
        "box": box,
        "running": running,
        "metrics": [value.to_json() for value in run.metrics.values()],
    }
