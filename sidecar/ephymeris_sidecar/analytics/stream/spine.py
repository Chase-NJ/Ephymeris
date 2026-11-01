"""A spine run's file, decoded for replay (`0003-phase-spine-task-model.md#replay-and-analytics`).

A phase-spine run records only what the board observed and what it did
(`TASKS.md#spine-tasks`). Its profile snapshot carries the state table, which
channel and which edge codes each bit is, and which wire key each parameter
slot is; the document carries the parameter values and the seed. So the file
alone is enough to say what the board must have done:

    record = decode(document)            # the table, params, seed, input edges
    expected_stream(record)              # every strobe the board must have sent

The input edges come from the strobes and drive the replay; everything else
the board strobed (the outputs, START_SESSION, TRIAL_START, END_SESSION) is
PREDICTED, and must equal what was recorded, strobe for strobe. That is the
ADR's "the outputs are the checksum". Scoring a run, its trial table and
flagging a diverged one are #99's; this is what they read.

A run cut off by a crash has no END_SESSION: it is predicted up to its last
recorded strobe, so a crashed file replays as far as it goes.

**Pure**, like the rest of `stream/`: a document in, numbers out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from . import replay as rp

#: The session end rule BoxSpine.h follows: ends at the start of trial NT+1,
#: or the first trial start after STOP. NT is parameter slot 0.
TRIALS_SLOT = 0

#: How many parameters each kind of driven output reads (BoxSpine.h, DRIVEN OUTPUTS).
_DRIVE_VALUES = {"pwm": 1, "tone": 1, "train": 3}


class SpineDecodeError(ValueError):
    """The document is not a spine run this replay can decode."""


@dataclass(frozen=True)
class SpineRecord:
    """What `decode` read out of one run's document."""

    table: rp.Table
    params: tuple[int, ...]
    seed: int
    interp: int
    #: (tick, edges) per tick with a recorded input edge; tick 0 is the session's start.
    events: tuple[tuple[int, rp.Edges], ...]
    #: The tick of END_SESSION, or None for a run cut off before it.
    end_tick: int | None
    #: The tick of the last recorded strobe.
    last_tick: int
    #: Code numbers, from the snapshot's own strobes map.
    rise: tuple[int, ...]
    fall: tuple[int, ...]
    on: tuple[int, ...]
    off: tuple[int, ...]
    session_start: int
    trial_start: int
    session_end: int
    #: Every strobe as recorded, (code, ts).
    recorded: tuple[tuple[int, int], ...]
    #: Each driven output bit (`TASKS.md#driven-outputs`): (bit, kind, its
    #: parameter values): a PWM duty, a tone's Hz, or a train's hz, width and ms.
    drives: tuple[tuple[int, str, tuple[int, ...]], ...] = ()


#: What a summary says of a spine run until replay scores it.
REPLAY_PENDING_DETAIL = (
    "a spine task's run: scoring it by replay is not available yet, so it has no "
    "numbers. Every strobe is recorded"
)


def is_spine_run(document: dict[str, Any]) -> bool:
    """Whether a state table ran this run, by what its own file says.

    Either mark is enough: the snapshot's `spine` key, or a header `interp` the
    replay runs. The header is what the board announced, so a run whose
    snapshot did not survive is still known for what it is. A task's name
    never decides it.
    """
    return _snapshot_spine(document) is not None or document.get("interp") in rp.INTERP_VERSIONS


def _snapshot_spine(document: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = document.get("task_profile")
    spine = snapshot.get("spine") if isinstance(snapshot, dict) else None
    return spine if isinstance(spine, dict) else None


def decode(document: dict[str, Any]) -> SpineRecord:
    """Read a spine run's table, parameters, seed and input edges out of its document.

    Raises `SpineDecodeError` for a document that is not a spine run, one
    whose table format (`interp`) this replay does not know, and every
    malformed one: never replayed under a guess, and never refused with
    whatever a damaged field happens to raise.
    """
    try:
        return _decode(document)
    except SpineDecodeError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise SpineDecodeError(f"the run's document is malformed: {exc!r}") from exc


def _decode(document: dict[str, Any]) -> SpineRecord:
    spine = _snapshot_spine(document)
    if spine is None:
        raise SpineDecodeError("its profile snapshot carries no spine, so there is no table to replay")
    snapshot = document["task_profile"]
    # The header's `interp` is what the board announced, and it alone says which
    # interpreter ran the run (TASKS.md#confirming-the-parameters). The snapshot
    # says which the table was lowered for. Both must agree, and be one replay knows.
    interp = document.get("interp")
    if interp not in rp.INTERP_VERSIONS:
        raise SpineDecodeError(f"the header says INTERP {interp!r}, not a version this replay knows "
                               f"({sorted(rp.INTERP_VERSIONS)})"
                               if interp is not None else
                               "the header names no interpreter: the board never said a table ran this run")
    if spine.get("interp") != interp:
        raise SpineDecodeError(f"the header says INTERP {interp} but the snapshot's table is for "
                               f"INTERP {spine.get('interp')!r}")
    table_doc = spine.get("table")
    if not isinstance(table_doc, dict):
        raise SpineDecodeError("the snapshot carries no state table: the task could not be lowered")
    try:
        table = rp.Table(
            states=[rp.StateRow(*row) for row in table_doc["states"]],
            edges=[rp.EdgeRow(*row) for row in table_doc["edges"]],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SpineDecodeError(f"the snapshot's state table is not one: {exc}") from exc
    try:
        rp.check_interp(table, interp)
    except ValueError as exc:  # a pick state in a table that claims INTERP 2
        raise SpineDecodeError(f"the snapshot's state table cannot have run: {exc}") from exc

    code_of = {str(name): int(code) for code, name in (snapshot.get("strobes") or {}).items()}

    def code(name: Any) -> int:
        if name not in code_of:
            raise SpineDecodeError(f"the snapshot's strobes map has no code {name!r}")
        return code_of[name]

    wire_to_metadata = {f.get("wireKey"): f.get("metadataKey") for f in snapshot.get("config", [])}
    params = []
    for key in spine.get("params", []):
        metadata = wire_to_metadata.get(key)
        if metadata not in document:
            raise SpineDecodeError(f"the run records no value for parameter {key}")
        params.append(int(document[metadata]))
    seed = document.get("trial_seed")
    if not isinstance(seed, int):
        raise SpineDecodeError("the run records no trial_seed: its random draws cannot be replayed")

    inputs, outputs = spine.get("inputs", []), spine.get("outputs", [])
    slot_of = {key: n for n, key in enumerate(spine.get("params", []))}
    drives = []
    for j, o in enumerate(outputs):
        kind = o.get("drive")
        if kind is None:
            continue
        if interp < rp.DRIVES_SINCE:
            raise SpineDecodeError(f"the snapshot drives {o.get('channel')!r} as {kind}, which INTERP {interp} "
                                   "never did: its table cannot have run")
        keys = o.get("params", [])
        if kind not in _DRIVE_VALUES or len(keys) != _DRIVE_VALUES[kind] or any(k not in slot_of for k in keys):
            raise SpineDecodeError(f"the snapshot's {kind} output {o.get('channel')!r} names no parameters "
                                   "replay can read")
        drives.append((j, kind, tuple(params[slot_of[k]] for k in keys)))
    rise = tuple(code(i["rise"]) for i in inputs)
    fall = tuple(code(i["fall"]) for i in inputs)
    structural = spine.get("structural", {})
    record = SpineRecord(
        table=table,
        params=tuple(params),
        seed=seed,
        interp=interp,
        events=(),
        end_tick=None,
        last_tick=0,
        rise=rise,
        fall=fall,
        on=tuple(code(o["on"]) for o in outputs),
        off=tuple(code(o["off"]) for o in outputs),
        session_start=code(structural.get("sessionStart")),
        trial_start=code(structural.get("trialStart")),
        session_end=code(structural.get("sessionEnd")),
        recorded=tuple((int(c), int(t)) for c, t in document.get("ts_data", [])),
        drives=tuple(drives),
    )

    by_tick: dict[int, list[int]] = {}
    end_tick = None
    for c, t in record.recorded:
        if c in rise:
            by_tick.setdefault(t, [0, 0])[0] |= 1 << rise.index(c)
        elif c in fall:
            by_tick.setdefault(t, [0, 0])[1] |= 1 << fall.index(c)
        elif c == record.session_end and end_tick is None:
            end_tick = t
    events = tuple((t, rp.Edges(r, f)) for t, (r, f) in sorted(by_tick.items()))
    last = max((t for _, t in record.recorded), default=0)
    return replace(record, events=events, end_tick=end_tick, last_tick=last)


def expected_stream(record: SpineRecord) -> list[tuple[int, int]]:
    """Every strobe the board must have sent, as (code, ts), from the inputs alone.

    The board's order within a tick (BoxSpine.h, THE STREAM): START_SESSION,
    inputs that rose, that fell, TRIAL_START, outputs off, outputs on; and its
    session end rule. A run cut off before END_SESSION is predicted up to its
    last recorded strobe: a power cut can fall between two strobes of one tick,
    so its last tick is held only to as many strobes as the file recorded there.
    """
    out = _predict(record)
    if record.end_tick is None:
        held = sum(1 for _, t in record.recorded if t == record.last_tick)
        before = [s for s in out if s[1] < record.last_tick]
        out = before + [s for s in out if s[1] == record.last_tick][:held]
    return out


def pulses(record: SpineRecord) -> list[tuple[int, int, int]]:
    """Every pulse every train fired, as (output bit, rise tick, fall tick), by rise.

    The stream carries only each train's start and end (`TRAIN_ON`, `TRAIN_OFF`);
    every pulse between is `replay.train_pulses` over that span, at the row's
    rate and width. The spans are replay's own, which `expected_stream` holds
    to the recorded stream. A train still running when a crashed file stops is
    cut at its last recorded strobe.
    """
    params = {bit: values for bit, kind, values in record.drives if kind == "train"}
    out = [(bit, start + rise, start + fall)
           for bit, start, end in _run(record)[1]
           for rise, fall in rp.train_pulses(params[bit][0], params[bit][1], end - start)]
    return sorted(out, key=lambda p: (p[1], p[0]))


def _predict(record: SpineRecord) -> list[tuple[int, int]]:
    """Every strobe of every tick through the end, or through the last recorded one."""
    return _run(record)[0]


def _run(record: SpineRecord) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]]]:
    """Every strobe through the end, or through the last recorded one, and each
    train's (bit, first tick, tick it stopped).

    The core's actions are replay's. On top of them, BoxSpine.h's DRIVEN
    OUTPUTS: a train whose ms runs out goes LOW on its own, at a tick the core
    may leave idle, so the outputs strobed are the LIVE ones.
    """
    ticks = record.end_tick if record.end_tick is not None else record.last_tick
    try:
        actions = rp.replay(record.table, record.params, record.seed, record.events, ticks,
                            start=0, interp=record.interp)
    except ValueError as exc:  # strobes out of order, an edge after the end, a bad parameter
        raise SpineDecodeError(f"the recorded strobes cannot be replayed: {exc}") from exc
    out: list[tuple[int, int]] = []
    spans: list[tuple[int, int, int]] = []
    trials, live = 0, 0
    max_trials = record.params[TRIALS_SLOT]
    train_ms = {bit: values[2] for bit, kind, values in record.drives if kind == "train"}
    since: dict[int, int] = {}

    def bits(mask: int) -> list[int]:
        return [i for i in range(32) if mask >> i & 1]

    def ran_out(now: int) -> int:
        """The live trains whose ms has run out by `now`."""
        return sum(1 << b for b, ms in train_ms.items() if live >> b & 1 and ms and now - since[b] >= ms)

    def next_run_out() -> int | None:
        due = [since[b] + ms for b, ms in train_ms.items() if live >> b & 1 and ms]
        return min(due) if due else None

    def stopped(mask: int, now: int) -> None:
        spans.extend((b, since[b], now) for b in bits(mask) if b in train_ms)

    def run_outs_before(now: int) -> None:
        """Ticks the core leaves idle where a train runs out: its TRAIN_OFF alone."""
        nonlocal live
        while (due := next_run_out()) is not None and due < now:
            mask = ran_out(due)
            out.extend((record.off[j], due) for j in bits(mask))
            stopped(mask, due)
            live &= ~mask

    for now, a in actions:
        run_outs_before(now)
        starts = bool(a.flags & rp.ACT_TRIAL_START)
        ends = starts and now > 0 and (trials >= max_trials or now == record.end_tick)
        if a.flags & rp.ACT_SESSION_START:
            out.append((record.session_start, now))
        out += [(record.rise[i], now) for i in bits(a.rose)]
        out += [(record.fall[i], now) for i in bits(a.fell)]
        if ends:
            out += [(record.off[j], now) for j in bits(live)]
            out.append((record.session_end, now))
            stopped(live, now)
            return out, spans
        if starts:
            trials += 1
            out.append((record.trial_start, now))
        off = (a.off | ran_out(now)) & live
        out += [(record.off[j], now) for j in bits(off)]
        out += [(record.on[j], now) for j in bits(a.on)]
        stopped(off, now)
        live = (live & ~off) | a.on
        since.update((b, now) for b in bits(a.on) if b in train_ms)
    run_outs_before(ticks + 1)
    stopped(live, ticks)  # still running where the file stops
    return out, spans
