"""A spine run's file, decoded for replay (`0003-phase-spine-task-model.md#replay-and-analytics`).

A phase-spine run records only what the board observed and what it did
(`TASKS.md#spine-tasks`). Its profile snapshot carries the state table, which
channel and which edge codes each bit is, and which wire key each parameter
slot is; the document carries the parameter values and the seed. So the file
alone is enough to say what the board must have done:

    record = decode(document)            # the table, params, seed, input edges
    expected_stream(record)              # every strobe the board must have sent
    replayed(document)                   # its divergence, or its trial table

The input edges come from the strobes and drive the replay; everything else
the board strobed (the outputs, START_SESSION, TRIAL_START, END_SESSION) is
PREDICTED, and must equal what was recorded, strobe for strobe. That is the
ADR's "the outputs are the checksum": a run where it does not is **diverged**,
and is never scored (`ANALYTICS.md#how-a-spine-run-is-scored`). A run that
matches is read into its trial table (`trial_table.py`) from the same replay.

A run cut off by a crash has no END_SESSION: it is predicted up to its last
recorded strobe, so a crashed file replays as far as it goes.

**Pure**, like the rest of `stream/`: a document in, numbers out.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from ...taskdef.lowering import LoweringError, lower
from . import replay as rp
from . import trial_table as tt

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
    #: Code number -> name, from the snapshot's strobes map.
    names: dict[int, str] = field(default_factory=dict)
    #: What the snapshot says the table's bits, states and rows are.
    naming: tt.Naming = field(default_factory=tt.Naming)
    #: Each phase's label, for display only: nothing is scored by it.
    phase_labels: tuple[str, ...] = ()
    #: The task's rows, (id, name), in its order.
    rows: tuple[tuple[str, str], ...] = ()


#: The phase kind a response is read from (`ANALYTICS.md#the-trial-table`).
WINDOW_PHASE = "response"

#: The `INTERP` of BehaviorBox.h's trial runner, which every legacy (GRGL) run
#: names, and which no table describes (`replay.INTERP_VERSIONS`).
TRIAL_RUNNER_INTERP = 1


def is_spine_run(document: dict[str, Any]) -> bool:
    """Whether a state table ran this run, by what its own file says.

    Either mark is enough: the snapshot's `spine` key, or a header `interp`
    other than the trial runner's. The header is what the board announced, so a
    run whose snapshot did not survive is still known for what it is, and so is
    one from an interpreter this build does not know: reported, never inferred
    and never replayed. A task's name never decides it.
    """
    interp = document.get("interp")
    return _snapshot_spine(document) is not None or (
        interp is not None and interp != TRIAL_RUNNER_INTERP
    )


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
    naming, labels, rows = _naming(spine, table_doc, inputs, outputs)
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
        names={code: name for name, code in code_of.items()},
        naming=naming,
        phase_labels=labels,
        rows=rows,
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
    return _expected(record, *_session(record))


def _expected(record: SpineRecord, actions: list[tuple[int, rp.Actions]],
              end: int | None) -> list[tuple[int, int]]:
    """`expected_stream` from a replay already run."""
    out = _stream(record, actions, end)
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
           for bit, start, end in _run(record, *_session(record))[1]
           for rise, fall in rp.train_pulses(params[bit][0], params[bit][1], end - start)]
    return sorted(out, key=lambda p: (p[1], p[0]))


def _session(record: SpineRecord) -> tuple[list[tuple[int, rp.Actions]], int | None]:
    """The replay's actions through the session's end, and the tick it ended at.

    The end is BoxSpine.h's rule: the tick that would start trial NT+1, or the
    first trial start at or after the recorded END_SESSION. None for a run cut
    off before it ended, replayed through its last recorded strobe.
    """
    ticks = record.end_tick if record.end_tick is not None else record.last_tick
    try:
        actions = rp.replay(record.table, record.params, record.seed, record.events, ticks,
                            start=0, interp=record.interp)
    except ValueError as exc:  # strobes out of order, an edge after the end, a bad parameter
        raise SpineDecodeError(f"the recorded strobes cannot be replayed: {exc}") from exc
    trials = 0
    max_trials = record.params[TRIALS_SLOT]
    for k, (now, a) in enumerate(actions):
        starts = bool(a.flags & rp.ACT_TRIAL_START)
        if starts and now > 0 and (trials >= max_trials or now == record.end_tick):
            return actions[: k + 1], now
        if starts:
            trials += 1
    return actions, None


def _stream(record: SpineRecord, actions: list[tuple[int, rp.Actions]],
            end: int | None) -> list[tuple[int, int]]:
    """Every strobe of every tick through the end, or through the last recorded one."""
    return _run(record, actions, end)[0]


def _run(record: SpineRecord, actions: list[tuple[int, rp.Actions]],
         end: int | None) -> tuple[list[tuple[int, int]], list[tuple[int, int, int]]]:
    """Every strobe through the end, or through the last recorded one, and each
    train's (bit, first tick, tick it stopped).

    The core's actions are replay's. On top of them, BoxSpine.h's DRIVEN
    OUTPUTS: a train whose ms runs out goes LOW on its own, at a tick the core
    may leave idle, so the outputs strobed are the LIVE ones.
    """
    out: list[tuple[int, int]] = []
    spans: list[tuple[int, int, int]] = []
    live = 0
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
        if a.flags & rp.ACT_SESSION_START:
            out.append((record.session_start, now))
        out += [(record.rise[i], now) for i in bits(a.rose)]
        out += [(record.fall[i], now) for i in bits(a.fell)]
        if starts and now == end:
            out += [(record.off[j], now) for j in bits(live)]
            out.append((record.session_end, now))
            stopped(live, now)
            return out, spans
        if starts:
            out.append((record.trial_start, now))
        off = (a.off | ran_out(now)) & live
        out += [(record.off[j], now) for j in bits(off)]
        out += [(record.on[j], now) for j in bits(a.on)]
        stopped(off, now)
        live = (live & ~off) | a.on
        since.update((b, now) for b in bits(a.on) if b in train_ms)
    run_outs_before(record.last_tick + 1)
    stopped(live, record.last_tick)  # still running where the file stops
    return out, spans




# --- annotations ----------------------------------------------------------------


def _naming(
    spine: dict[str, Any], table_doc: dict[str, Any], inputs: list[Any], outputs: list[Any]
) -> tuple[tt.Naming, tuple[str, ...], tuple[tuple[str, str], ...]]:
    """What the snapshot says the table's bits, states and rows are.

    Read leniently: a damaged annotation costs its columns (null phase entries,
    no row), never the replay, which needs none of it.
    """
    phases = spine.get("spine") if isinstance(spine.get("spine"), list) else []
    labels = tuple(f"{p.get('phase')}" if isinstance(p, dict) else "?" for p in phases)
    n_states = len(table_doc.get("states") or [])
    rows_doc = [r for r in (spine.get("rows") or []) if isinstance(r, dict)]
    rows = tuple((str(r.get("id")), str(r.get("name") or r.get("id"))) for r in rows_doc)
    info = {str(r.get("id")): (str(r.get("name") or r.get("id")), _number(r.get("level"))) for r in rows_doc}
    blocks = [b for b in (spine.get("blocks") or []) if isinstance(b, dict)]

    # A state in no phase (#101's pick state) is null in `table.phases`.
    phase_of = _ints(table_doc.get("phases"), n_states, len(phases), nullable=True) \
        or _relowered(spine, table_doc, inputs, outputs)
    row_of = None
    row_index = _ints(table_doc.get("rows"), n_states, len(rows), nullable=True)
    if row_index is not None:
        row_of = tuple(rows[i][0] if i is not None else None for i in row_index)
    naming = tt.Naming(
        inputs=tuple(str(i.get("channel") or i.get("slot")) for i in inputs),
        outputs=tuple(str(o.get("channel") or o.get("slot")) for o in outputs),
        phase_of=phase_of,
        phases=len(phases) if phase_of is not None else 0,
        # Which phases are Response windows: the only kind a response is read
        # from when states map to phases (`ANALYTICS.md#the-trial-table`).
        windows=(frozenset(i for i, p in enumerate(phases)
                           if isinstance(p, dict) and p.get("phase") == WINDOW_PHASE)
                 if phase_of is not None else None),
        row_of=row_of,
        row=rows[0][0] if row_of is None and len(rows) == 1 else None,
        rows=info,
        block=str(blocks[0].get("id")) if len(blocks) == 1 else None,
    )
    return naming, labels, rows


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _ints(value: Any, length: int, bound: int, *, nullable: bool = False) -> tuple[Any, ...] | None:
    """`value` as one index per state, each below `bound`, or None if it is not one."""
    if not isinstance(value, list) or len(value) != length:
        return None
    for v in value:
        if v is None and nullable:
            continue
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < bound:
            return None
    return tuple(value)


def _relowered(
    spine: dict[str, Any], table_doc: dict[str, Any], inputs: list[Any], outputs: list[Any]
) -> tuple[int, ...] | None:
    """The phase map of a snapshot that does not carry one (`table.phases`).

    The snapshot's own definition, lowered again; used **only** when that gives
    back exactly the recorded table, so it is the map of the table that ran or
    nothing. A later lowering that writes the table differently gives nothing.
    """
    try:
        low = lower(spine["spine"], [i["slot"] for i in inputs], [o["slot"] for o in outputs])
    except (LoweringError, AttributeError, KeyError, TypeError, ValueError):
        return None
    same = [list(s) for s in low.states] == table_doc.get("states") and \
        [list(e) for e in low.edges] == table_doc.get("edges")
    return tuple(low.phases) if same else None


# --- divergence and the trial table ---------------------------------------------


@dataclass(frozen=True)
class Divergence:
    """Where a run's recorded strobes first leave what replay predicts."""

    detail: str
    #: The position in the recorded stream, or None when replay could not run.
    index: int | None = None
    at_ms: int | None = None
    expected: str | None = None
    recorded: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"detail": self.detail, "index": self.index, "atMs": self.at_ms,
                "expected": self.expected, "recorded": self.recorded}


@dataclass(frozen=True)
class Replayed:
    """A spine run replayed: its divergence, or its trial table, never both."""

    interp: int
    divergence: Divergence | None
    trials: tuple[tt.ReplayTrial, ...]
    phases: tuple[str, ...]
    rows: tuple[tuple[str, str], ...]


def replayed(document: dict[str, Any]) -> Replayed:
    """Replay a spine run once: where it diverges, or its trial table.

    Raises `SpineDecodeError` for a run replay cannot start on (an unknown
    `INTERP`, no table, a malformed snapshot): `unreplayable`. Recorded strobes
    the replay cannot be fed (out of order, an edge past the end) are a
    divergence: the file is not what this table, seed and inputs produce.
    """
    record = decode(document)
    try:
        actions, end = _session(record)  # the one replay: the check and the table read it
    except SpineDecodeError as exc:
        return Replayed(record.interp, Divergence(detail=str(exc)), (), record.phase_labels, record.rows)
    expected = _expected(record, actions, end)
    recorded = list(record.recorded)
    if expected != recorded:
        return Replayed(record.interp, _divergence(record, expected, recorded), (),
                        record.phase_labels, record.rows)
    trials = tt.trials_of(record.table, actions, end=end, phase_of=record.naming.phase_of,
                          windows=record.naming.windows)
    return Replayed(record.interp, None, tuple(tt.name(t, record.naming) for t in trials),
                    record.phase_labels, record.rows)


def _divergence(record: SpineRecord, expected: list[tuple[int, int]],
                recorded: list[tuple[int, int]]) -> Divergence:
    index = next((i for i, (e, r) in enumerate(zip(expected, recorded)) if e != r),
                 min(len(expected), len(recorded)))

    def strobe(stream: list[tuple[int, int]]) -> str | None:
        if index >= len(stream):
            return None
        code, ts = stream[index]
        return f"{record.names.get(code, code)}@{ts}"

    want, got = strobe(expected), strobe(recorded)
    at = (recorded[index] if index < len(recorded) else expected[index])[1]
    detail = (f"diverged at strobe {index + 1}: replay predicts {want or 'nothing more'}, "
              f"the file records {got or 'nothing more'}. Its outputs are not what this table, "
              "seed and inputs produce, so it is not scored")
    return Divergence(detail=detail, index=index, at_ms=at, expected=want, recorded=got)


def trial_table(document: dict[str, Any]) -> dict[str, Any] | None:
    """A run's trial table as the wire carries it (`RunSeries.trialTable`), or
    None for a run replay does not score: a legacy run, a diverged one, or one
    replay cannot run. Computed on each request and never cached
    (`DATA.md#caching`)."""
    if not is_spine_run(document):
        return None
    try:
        result = replayed(document)
    except SpineDecodeError:
        return None
    if result.divergence is not None:
        return None
    return {"phases": list(result.phases), "trials": [t.to_json() for t in result.trials]}
