"""TG5xx — capacity and wire invariants, checked on the LOWERED table.

Measured on what will actually be uploaded, not on the draft. The number that
matters is the number that goes over the wire, and a rule that checked the draft
would be checking something the board never sees.
"""

from __future__ import annotations

from collections.abc import Iterator

from taskgraph.context import TableContext
from taskgraph.errors import Diagnostic, Severity
from taskgraph.graph import NodeType
from taskgraph.lint import Pass, rule
from taskgraph.table import DUR_FROM_TRIAL, NO_STROBE, is_bound, selector_of


def _d(ctx: TableContext, code: str, sev: Severity, msg: str, **kw) -> Diagnostic:
    return Diagnostic(code=code, severity=sev, spec_id=ctx.spec_id, message=msg, **kw)


@rule(
    "TG501",
    name="table-too-large",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "The table exceeds a limit measured on real hardware. Simplify the topology, or "
        "re-run the AVR RAM spike and raise the limit on evidence."
    ),
)
def table_too_large(ctx: TableContext) -> Iterator[Diagnostic]:
    """Capacity, against the limits in schema/limits.v1.json.

    Those are not arbitrary: they come from a measured sweep on an ATmega2560
    (docs/spikes/avr-ram.md). Exceeding them is not a performance question -- the
    firmware's arrays are statically sized, so an over-large table has nowhere to
    go.
    """
    t, lim = ctx.table, ctx.limits
    for what, actual, cap in (
        ("states", len(t.nodes), lim.TG_MAX_STATES),
        ("edges", len(t.edges), lim.TG_MAX_EDGES),
        ("timing entries", len(t.timing), lim.TG_MAX_TIMING),
        ("entry actions", len(t.actions), lim.TG_MAX_ACTIONS),
        ("trial types", len(t.trial_types), lim.TG_MAX_TRIAL_TYPES),
        ("stage rows", len(t.stage_rows), lim.TG_MAX_STAGE_ROWS),
        ("timing rewrites", len(t.timing_sets), lim.TG_MAX_TIMING_SETS),
    ):
        if actual > cap:
            yield _d(
                ctx, "TG501", Severity.ERROR,
                f"{actual} {what}, limit is {cap}",
                detail=f"table is {t.size_bytes()} bytes",
            )


@rule(
    "TG502",
    name="index-out-of-range",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "An index does not fit its field, or points past the end of its table. This would "
        "read arbitrary memory on the board."
    ),
)
def index_out_of_range(ctx: TableContext) -> Iterator[Diagnostic]:
    """Every index must fit a uint8 AND address something real.

    The firmware does no bounds checking in the trial loop -- it cannot afford to
    -- so an out-of-range index is a read of whatever happens to be next in SRAM.
    """
    t = ctx.table
    for i, n in enumerate(t.nodes):
        if n.dur_idx != DUR_FROM_TRIAL and not 0 <= n.dur_idx < max(len(t.timing), 1):
            yield _d(ctx, "TG502", Severity.ERROR,
                     f"S{i:02d} duration index {n.dur_idx} is outside 0..{len(t.timing) - 1}",
                     location=f"S{i:02d}")
        if is_bound(n.strobe):
            # A runtime binding, not a code. What it RESOLVES to is checked by
            # TG506, which walks the port and stimulus tables -- the wire-format
            # bound applies to those, not to the selector.
            pass
        elif n.strobe != NO_STROBE and not 0 <= n.strobe <= 999:
            yield _d(ctx, "TG502", Severity.ERROR,
                     f"S{i:02d} strobe {n.strobe} is outside the 3-digit wire format",
                     location=f"S{i:02d}",
                     detail="emitStrobe formats %03d and the host regex is ^\\d{1,3}\\t\\d+$")
        for field_name, value in (("edge_idx", n.edge_idx), ("action_idx", n.action_idx)):
            if not 0 <= value <= 255:
                yield _d(ctx, "TG502", Severity.ERROR,
                         f"S{i:02d} {field_name}={value} does not fit a uint8",
                         location=f"S{i:02d}")
    for i, e in enumerate(t.edges):
        if not 0 <= e.target < len(t.nodes):
            yield _d(ctx, "TG502", Severity.ERROR,
                     f"edge {i} targets S{e.target:02d}, which does not exist",
                     location=f"edge {i}")


@rule(
    "TG503",
    name="edge-offsets-not-monotonic",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "Edges must be grouped by owning node in node order. A node's edge count is implied "
        "by the NEXT node's offset."
    ),
)
def edge_offsets_not_monotonic(ctx: TableContext) -> Iterator[Diagnostic]:
    """The invariant that makes the implied edge counts correct.

    TgNode stores only `edgeIdx`; the count is the difference to the next node's
    offset (and to nEdges for the last). If offsets are not non-decreasing, a node
    reads a negative or overlapping span -- so every node past the break executes
    edges belonging to some other state. That is not a crash. It is a box quietly
    running a task nobody wrote.
    """
    t = ctx.table
    prev = 0
    for i, n in enumerate(t.nodes):
        if n.edge_idx < prev:
            yield _d(
                ctx, "TG503", Severity.ERROR,
                f"S{i:02d} edge offset {n.edge_idx} is below the previous node's {prev}",
                location=f"S{i:02d}",
                detail="Every node from here on would read another state's edges.",
            )
        prev = n.edge_idx
    if t.nodes and prev > len(t.edges):
        yield _d(ctx, "TG503", Severity.ERROR,
                 f"last edge offset {prev} is past the {len(t.edges)}-edge table")


@rule(
    "TG504",
    name="watch-mask-overflow",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "TgNode.watchMask is uint8, so at most 8 channels can be watched. With one engagement "
        "channel that leaves 7 response ports."
    ),
)
def watch_mask_overflow(ctx: TableContext) -> Iterator[Diagnostic]:
    """task_spec.v1.json permits 8 response ports; the hardware allows 7.

    8 response ports plus a distinct engagement channel is nine watchable
    channels and one bit too few. Caught here rather than silently dropping the
    ninth, which would leave a port live in the spec and dead on the board.
    """
    for i, n in enumerate(ctx.table.nodes):
        if n.watch_mask > 0xFF:
            yield _d(ctx, "TG504", Severity.ERROR,
                     f"S{i:02d} watches more channels than the 8-bit mask can hold",
                     location=f"S{i:02d}")


@rule(
    "TG505",
    name="degenerate-duration",
    severity=Severity.WARN,
    pass_=Pass.PACK,
    help="A zero duration on a state that is supposed to take time is legal but almost always a mistake.",
)
def degenerate_duration(ctx: TableContext) -> Iterator[Diagnostic]:
    """Semantically suspicious, syntactically fine.

    A HOLD with zero duration completes instantly, so nothing is ever held; a
    WAIT_ENTRY with zero closes before the animal can act and always times out; a
    PULSE with zero opens the valve for no time and delivers nothing. All three
    compile, all three run, and all three silently make the task something other
    than what was intended.

    Zero-duration DELAYs are exempt: those are the epsilon nodes that carry paired
    strobes, and they are supposed to be instant (D2).
    """
    t = ctx.table
    suspicious = {NodeType.HOLD, NodeType.WAIT_ENTRY, NodeType.PULSE}
    for i, n in enumerate(t.nodes):
        if n.type not in suspicious:
            continue
        if n.dur_idx == DUR_FROM_TRIAL:
            continue  # resolved per trial; its magnitude lives in the trial-type row
        if n.dur_idx < len(t.timing) and t.timing[n.dur_idx] == 0:
            tid = t.timing_ids[n.dur_idx] if n.dur_idx < len(t.timing_ids) else "?"
            what = {
                NodeType.HOLD: "completes instantly, so nothing is ever held",
                NodeType.WAIT_ENTRY: "closes before the subject can act, so it always times out",
                NodeType.PULSE: "opens the actuator for no time, so it delivers nothing",
            }[n.type]
            yield _d(ctx, "TG505", Severity.WARN,
                     f'S{i:02d} {n.type} "{n.label}" has duration {tid} = 0 ms — it {what}',
                     location=f"S{i:02d}")


@rule(
    "TG506",
    name="unresolvable-binding",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "A runtime-bound strobe must resolve to a wire-legal code for every port or "
        "stimulus it could select. Check the contingency table for a missing code."
    ),
)
def unresolvable_binding(ctx: TableContext) -> Iterator[Diagnostic]:
    """What a binding RESOLVES to, not the selector itself.

    TG502 checks literal codes. A bound strobe carries a selector instead, and the
    codes it can produce live in the port and stimulus tables -- so this is the
    rule that keeps "the board will emit something wire-legal" true. Without it a
    port missing an `error_code` would compile fine and emit nothing on every wrong
    answer, which reads as an animal that never makes mistakes.
    """
    from taskgraph.table import (
        BIND_PORT_BREAK,
        BIND_PORT_ENTER,
        BIND_PORT_ERROR,
        BIND_PORT_EXIT,
        BIND_STIM_ON_3,
        BIND_TARGET_EXIT,
        BIND_TARGET_REWARD,
        BIND_TARGET_REWARD_STOP,
    )

    t = ctx.table
    per_port = {
        BIND_PORT_ENTER: ("enter_code", "a poke"),
        BIND_PORT_ERROR: ("error_code", "a wrong-port answer"),
        BIND_PORT_BREAK: ("break_code", "a broken response hold"),
        BIND_PORT_EXIT: ("exit_code", "leaving the port"),
        BIND_TARGET_REWARD: ("reward_code", "reward delivery"),
        BIND_TARGET_REWARD_STOP: ("reward_stop_code", "the end of reward delivery"),
        BIND_TARGET_EXIT: ("exit_code", "leaving the reward port"),
    }

    for i, n in enumerate(t.nodes):
        if not is_bound(n.strobe):
            continue
        sel = selector_of(n.strobe)

        if sel <= BIND_STIM_ON_3:
            # Selectors 0..3 are stimulus-on for sampling stages 0..3.
            for s in t.stimuli:
                if s.on_code == NO_STROBE or not 0 <= s.on_code <= 999:
                    yield _d(ctx, "TG506", Severity.ERROR,
                             f"S{i:02d} binds a stimulus code, but stimulus "
                             f"{s.name!r} has none",
                             location=f"S{i:02d}")
            continue

        field_name, what = per_port.get(sel, (None, None))
        if field_name is None:
            yield _d(ctx, "TG506", Severity.ERROR,
                     f"S{i:02d} carries an unknown binding selector {sel}",
                     location=f"S{i:02d}")
            continue
        for port in t.ports:
            code = getattr(port, field_name)
            if code == NO_STROBE or not 0 <= code <= 999:
                yield _d(ctx, "TG506", Severity.ERROR,
                         f"S{i:02d} reports {what}, but port {port.name!r} declares "
                         f"no {field_name}",
                         location=f"S{i:02d}",
                         detail="The board would emit nothing on that path.")


@rule(
    "TG507",
    name="partial-stage-row",
    severity=Severity.ERROR,
    pass_=Pass.PACK,
    help=(
        "Every stage row must restate every timing entry the schedule touches. The board "
        "applies ONE row -- the latest whose trial count has been reached -- so an entry a "
        "row omits keeps whatever value it had, which is not necessarily the previous row's."
    ),
)
def partial_stage_row(ctx: TableContext) -> Iterator[Diagnostic]:
    """The invariant `tgApplyStage()` is built on.

    Firmware's `applyStage()` rewrites four hard-coded fields on every row, so
    completeness was structural and nobody had to think about it. Addressing
    entries by index makes a partial row expressible for the first time, and a
    partial row is silently wrong in a way that only shows up as an animal running
    the wrong timings for the rest of a session.

    Applying one row rather than replaying all of them is deliberate: replaying is
    O(rows) per trial and, worse, makes the live timings depend on how the session
    arrived at this trial count rather than on the count alone. Idempotence is
    what makes a resumed or restarted session land in the same place, so the
    completeness it requires is enforced here instead.
    """
    t = ctx.table
    if len(t.stage_rows) < 2:
        return  # one row cannot disagree with another

    touched = {s.idx for s in t.timing_sets}
    for r in t.stage_rows:
        present = {t.timing_sets[r.first_idx + k].idx for k in range(r.count)}
        missing = sorted(touched - present)
        if not missing:
            continue
        names = ", ".join(
            t.timing_ids[i] if i < len(t.timing_ids) else f"[{i}]" for i in missing
        )
        yield _d(ctx, "TG507", Severity.ERROR,
                 f"the stage row at trial {r.at_trial} does not set {names}, which "
                 f"another row does",
                 location=f"stage_schedule[at_trial={r.at_trial}]",
                 detail=(
                     "The board applies this row alone, so those entries would keep "
                     "whatever they held -- the compiled default if this is the first "
                     "row reached, otherwise an earlier row's value. Restate them here."
                 ))
