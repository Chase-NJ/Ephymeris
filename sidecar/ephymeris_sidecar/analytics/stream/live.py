"""A spine run replayed as it runs, strobe by strobe (`ANALYTICS.md#live-scoring`).

Mission Control shows where a running spine task's board is, and its numbers so
far, from the same replay Analytics scores the finished run with
(`0003-phase-spine-task-model.md#replay-and-analytics`):

    replay = LiveReplay(header)          # the run's document before its first strobe
    replay.feed(code, ts)                # each strobe as it arrives
    replay.at(tick)                      # the state, phase and row the board is in
    scored(replay.document())            # the trial table and metrics so far

**Where the board is** comes from `replay.begin` and `replay.step`, fed the
recorded input edges one tick at a time. Within a tick the board strobes its
inputs first (`TASKS.md#the-runner`), so an edge at tick t is held until t is
closed: by a strobe at a later tick, or by any strobe at t that is not an
input's. Then the timers due before t run, and t is stepped once with all its
edges, as the board stepped it. So what is committed is a function of the
strobes received, and equals offline replay at every tick it reaches.

Between strobes, `at(tick)` runs the core's own timers forward with no edge:
what the board does when the animal does nothing. That view is never committed.
An edge that arrives later for an earlier tick is simply in the next view.

**The numbers** are never read incrementally. `scored` runs `spine.replayed`
over the stream so far, which reads a stream cut mid-run as it reads a crashed
run, then the `table_metrics` calls `summary.summarize` makes. So the live
figures at the session's end are Analytics', by construction, and a divergence
is found by the same check.

Nothing here reads a code's name: every code is placed by the snapshot's own
map, as `spine.decode` reads it.

**Pure**, like the rest of `stream/`: no clock, thread or I/O. The session runner
supplies the board's time (`sessions/live_replay.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import replay as rp
from . import spine
from . import table_metrics
from .metric_summary import MetricSummary
from .summary import DEFAULT_MIN_COUNTED, replay_score
from .trial_table import ReplayTrial

_RISE, _FALL = 0, 1


@dataclass(frozen=True)
class View:
    """Where the board is at one tick."""

    #: The table state it rests in.
    state: int
    #: That state's phase, an index into the snapshot's spine, or None for a
    #: state in no phase or a snapshot that maps none.
    phase: int | None
    #: The row id the state belongs to, or None for one the rows share.
    row: str | None
    #: The tick its timer runs out at, or None for a state with no timer.
    due: int | None
    #: The state was entered after the latest strobe's tick, by a timer alone:
    #: what the board does if nothing happened since, which no strobe confirms yet.
    provisional: bool = False


@dataclass(frozen=True)
class Fed:
    """What one strobe did to the replay."""

    #: A trial started at a tick this strobe committed.
    trial_started: bool = False
    #: The stream so far should be checked and scored now: a trial started, a
    #: trial start or the session end was recorded, or the replay could not be fed.
    check: bool = False


@dataclass
class _Pending:
    tick: int
    rose: int = 0
    fell: int = 0


class LiveReplay:
    """One running spine run's replay. Not thread-safe: the caller serializes."""

    def __init__(self, header: dict[str, Any]) -> None:
        """`header` is the run's document without its strobes.

        Raises `spine.SpineDecodeError` for a run replay cannot start on, as
        Analytics would call it `unreplayable`."""
        self._header = {k: v for k, v in header.items() if k != "ts_data"}
        record = spine.decode({**self._header, "ts_data": []})
        self._record = record
        self._edge = {code: (bit, _RISE) for bit, code in enumerate(record.rise)}
        self._edge.update({code: (bit, _FALL) for bit, code in enumerate(record.fall)})
        self._core, _ = rp.begin(record.table, record.params, record.seed, 0, record.interp)
        self._tick = 0
        #: The latest tick whose inputs are all in: stepped, or past a strobe that is not an input's.
        self._closed = 0
        self._pending: _Pending | None = None
        self._strobes: list[list[int]] = []
        self.broken: str | None = None
        self.ended = False

    # --- fed ----------------------------------------------------------------

    def feed(self, code: int, ts: int) -> Fed:
        """Take one strobe, in the order the board sent it."""
        self._strobes.append([code, ts])
        if self.broken is not None:
            return Fed()
        if self.ended:  # nothing follows END_SESSION: the check will say so
            return Fed(check=True)
        pending = self._pending
        floor = pending.tick if pending is not None else self._tick
        edge = self._edge.get(code)
        # A closed tick takes no more input, and nothing moves back.
        if ts < floor or (edge is not None and ts <= self._closed):
            self.broken = f"strobe {len(self._strobes)} ({code}@{ts}) arrives after tick {floor}"
            return Fed(check=True)
        started = False
        if pending is not None and ts > pending.tick:
            started |= self._commit()
        if edge is not None:
            if self._pending is None:
                self._pending = _Pending(ts)
            bit, kind = edge
            if kind == _RISE:
                self._pending.rose |= 1 << bit
            else:
                self._pending.fell |= 1 << bit
        else:
            if self._pending is not None:  # its tick is closed: inputs come first
                started |= self._commit()
            self._core, self._tick, acts = _timers(self._core, self._tick, ts)
            started |= _starts(acts)
            self._closed = ts
        structural = code in (self._record.trial_start, self._record.session_end)
        if code == self._record.session_end:
            self.ended = True
        return Fed(trial_started=started, check=started or structural)

    def _commit(self) -> bool:
        assert self._pending is not None
        p, self._pending = self._pending, None
        self._core, self._tick, acts = _timers(self._core, self._tick, p.tick - 1)
        self._core, a = rp.step(self._core, rp.Edges(p.rose, p.fell), p.tick)
        self._tick = self._closed = p.tick
        return _starts(acts) or bool(a.flags & rp.ACT_TRIAL_START)

    # --- read -----------------------------------------------------------------

    def at(self, tick: int) -> View:
        """Where the board is at `tick`: what is committed, any edges still
        pending, and then only the core's timers, run to `tick`."""
        core, now = self._core, self._tick
        if self._pending is not None and tick >= self._pending.tick:
            p = self._pending
            core, now, _ = _timers(core, now, p.tick - 1)
            core, _ = rp.step(core, rp.Edges(p.rose, p.fell), p.tick)
            now = p.tick
        core, now, _ = _timers(core, now, tick)
        naming = self._record.naming
        state = core.state
        phase = naming.phase_of[state] if naming.phase_of is not None else None
        row = naming.row_of[state] if naming.row_of is not None else naming.row
        last = self._strobes[-1][1] if self._strobes else 0
        return View(state=state, phase=phase, row=row, due=_due(core, now),
                    provisional=core.entered_at > last)

    @property
    def received(self) -> int:
        """How many strobes have been fed."""
        return len(self._strobes)

    def strobes_since(self, k: int) -> list[list[int]]:
        """Every strobe fed after the first `k`, in order."""
        return [list(s) for s in self._strobes[k:]]

    def document(self) -> dict[str, Any]:
        """The run's document so far: the header and every strobe received."""
        return {**self._header, "ts_data": [list(s) for s in self._strobes]}


def _due(core: rp.Core, now: int) -> int | None:
    """The tick the resting state's timer runs out at, never before `now + 1`
    (a tick is stepped once)."""
    if core.table.states[core.state].timer_min == rp.NONE:
        return None
    return max(core.entered_at + core.duration, now + 1)


def _timers(core: rp.Core, now: int, until: int) -> tuple[rp.Core, int, list[rp.Actions]]:
    """Step every timer that runs out after tick `now` and by `until`, with no
    edge: offline replay steps exactly these ticks between two edges."""
    out = []
    while (due := _due(core, now)) is not None and due <= until:
        core, a = rp.step(core, rp.Edges(), due)
        now = due
        out.append(a)
    return core, now, out


def _starts(actions: list[rp.Actions]) -> bool:
    return any(a.flags & rp.ACT_TRIAL_START for a in actions)


# --- scored -----------------------------------------------------------------------


@dataclass(frozen=True)
class LiveScore:
    """The stream so far, checked and scored as Analytics scores a run."""

    #: `ok`, `diverged` or `unreplayable`, as `RunSummary.status` says them.
    status: str
    detail: str | None = None
    divergence: spine.Divergence | None = None
    #: The trial table so far; its last trial is open (incomplete) mid-run.
    trials: tuple[ReplayTrial, ...] = ()
    score: table_metrics.ReplayScore | None = None
    metrics: tuple[MetricSummary, ...] = field(default=())
    overall: MetricSummary | None = None


def scored(document: dict[str, Any], *, min_counted: int = DEFAULT_MIN_COUNTED) -> LiveScore:
    """The trial table and metrics of a spine run's stream so far.

    Replays the whole stream once (`spine.replayed`) and scores it with
    `summary.replay_score`, the call `summary.summarize` makes, so a stream that has ended
    scores exactly as Analytics scores its file. A stream cut mid-run is read as
    a crashed run is: its open trial is in the table, incomplete, and out of the
    metrics."""
    try:
        result = spine.replayed(document)
    except spine.SpineDecodeError as exc:
        return LiveScore(status="unreplayable", detail=f"replay cannot run this spine run: {exc}")
    if result.divergence is not None:
        return LiveScore(status="diverged", detail=result.divergence.detail, divergence=result.divergence)
    score = replay_score(result, min_counted)
    return LiveScore(
        status="ok",
        trials=result.trials,
        score=score,
        metrics=tuple(table_metrics.correct_metrics(score, min_counted=min_counted)),
        overall=table_metrics.overall_correct(score, min_counted=min_counted),
    )


def fields(score: LiveScore) -> dict[str, Any]:
    """`score` as plain values, the part of `session.replay` it fills: what the
    live scorer's process sends back (`sessions/scorer.py`)."""
    complete = [t for t in score.trials if t.complete]
    open_ = score.trials[-1] if score.trials and not score.trials[-1].complete else None
    return {
        "status": score.status,
        "detail": score.detail,
        "divergence": score.divergence.to_json() if score.divergence is not None else None,
        "trials": len(complete),
        "current": open_.to_json() if open_ is not None else None,
        "last": complete[-1].to_json() if complete else None,
        "metrics": [m.to_json() for m in score.metrics],
        "overall": score.overall.to_json() if score.overall is not None else None,
        "replay": score.score.to_json() if score.score is not None else None,
    }
