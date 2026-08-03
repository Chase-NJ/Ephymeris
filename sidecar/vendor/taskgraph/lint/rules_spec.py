"""TG2xx — resolution rules.

Everything decidable from the bound spec plus the three frozen registries, before
any graph exists. These were assertions in tests/test_specs_validate.py during
Phase 0; as rules they run on every compile rather than only under pytest, and
they report a location and a fix instead of an AssertionError.
"""

from __future__ import annotations

from collections.abc import Iterator

from taskgraph.context import SpecContext
from taskgraph.errors import Diagnostic, Severity
from taskgraph.lint import Pass, rule

D = Diagnostic


def _err(ctx: SpecContext, code: str, loc: str, msg: str, **kw) -> Diagnostic:
    return D(code=code, severity=Severity.ERROR, spec_id=ctx.spec_id, location=loc, message=msg, **kw)


def _warn(ctx: SpecContext, code: str, loc: str, msg: str, **kw) -> Diagnostic:
    return D(code=code, severity=Severity.WARN, spec_id=ctx.spec_id, location=loc, message=msg, **kw)


# --------------------------------------------------------------------------- #
# Timing
# --------------------------------------------------------------------------- #


@rule(
    "TG201",
    name="unresolved-timing-ref",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Every duration is an id declared in `timing:`. Add the entry, or fix the spelling.",
    decision="D6",
)
def unresolved_timing_ref(ctx: SpecContext) -> Iterator[Diagnostic]:
    """A duration naming a timing entry that does not exist.

    Durations are indices into the timing vector, never literals -- that is what
    makes a shaping ramp a table rewrite rather than a recompile. An unresolved id
    would compile to a garbage index into a live array.
    """
    known = {t.id for t in ctx.spec.timing}
    c = ctx.spec.contingency

    for name, outcome in c.outcome_map.items():
        if outcome.delay not in known:
            yield _err(ctx, "TG201", f"contingency.outcome_map.{name}.delay",
                       f"unknown timing id {outcome.delay!r}")

    for pname, port in c.ports.items():
        if port.reward_duration and port.reward_duration not in known:
            yield _err(ctx, "TG201", f"contingency.ports.{pname}.reward_duration",
                       f"unknown timing id {port.reward_duration!r}")

    for i, row in enumerate(ctx.spec.policy.stage_schedule):
        for tid in row.set:
            if tid not in known:
                yield _err(ctx, "TG201", f"policy.stage_schedule[{i}].set.{tid}",
                           f"stage ramp rewrites unknown timing id {tid!r}")


@rule(
    "TG202",
    name="duplicate-timing-id",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help=(
        "Timing ids must be unique -- an id resolves to a vector index, and a "
        "duplicate makes that ambiguous."
    ),
)
def duplicate_timing_id(ctx: SpecContext) -> Iterator[Diagnostic]:
    seen: dict[str, int] = {}
    for t in ctx.spec.timing:
        if t.id in seen:
            yield _err(ctx, "TG202", f"timing[{t.index}].id",
                       f"timing id {t.id!r} already declared at index {seen[t.id]}")
        seen[t.id] = t.index


@rule(
    "TG203",
    name="missing-t-zero",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Add `- {id: t_zero, ms: 0}` to the timing vector.",
    decision="D2",
)
def missing_t_zero(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Every spec needs a zero duration.

    Paired strobes are modelled as adjacent zero-duration nodes rather than a
    per-node strobe list, and the response branch is a zero-duration node carrying
    the guard. Both are emitted for every topology, so t_zero is structurally
    required -- and measured at 0 ms skew on hardware, so it costs nothing.
    """
    if not any(t.id == "t_zero" for t in ctx.spec.timing):
        yield _err(ctx, "TG203", "timing",
                   "t_zero is required: zero-duration nodes carry paired strobes and the response branch")


@rule(
    "TG204",
    name="duration-out-of-range",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Durations are uint16. Split a longer interval across two DELAY nodes if one is genuinely needed.",
    decision="D6",
)
def duration_out_of_range(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Reject rather than wrap.

    Firmware stores timings as signed int and uses 32767 as the StageStep "never"
    sentinel, so a legal duration sat one step from a magic one. uint16 removed the
    collision; silently wrapping would reintroduce it in a worse form.
    """
    cap = ctx.limits.TG_DURATION_MAX
    for t in ctx.spec.timing:
        if not 0 <= t.ms <= cap:
            yield _err(ctx, "TG204", f"timing[{t.index}].ms", f"{t.ms} ms is outside 0..{cap}")
    for i, row in enumerate(ctx.spec.policy.stage_schedule):
        for tid, ms in row.set.items():
            if not 0 <= ms <= cap:
                yield _err(ctx, "TG204", f"policy.stage_schedule[{i}].set.{tid}",
                           f"{ms} ms is outside 0..{cap}")


@rule(
    "TG205",
    name="stage-schedule-unordered",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="List stage rows in ascending at_trial order, with no duplicates.",
)
def stage_schedule_unordered(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Rows are scanned descending with >=, so the schedule is idempotent -- but a
    spec listing them out of order is readable-but-wrong, and a reader will believe
    the order they see."""
    counts = [r.at_trial for r in ctx.spec.policy.stage_schedule]
    if counts != sorted(counts):
        yield _err(ctx, "TG205", "policy.stage_schedule",
                   f"rows are not in ascending at_trial order: {counts}")
    seen: set[int] = set()
    for i, n in enumerate(counts):
        if n in seen:
            yield _err(ctx, "TG205", f"policy.stage_schedule[{i}].at_trial",
                       f"duplicate at_trial {n} -- the later row would be unreachable")
        seen.add(n)


# --------------------------------------------------------------------------- #
# Strobes
# --------------------------------------------------------------------------- #


def _strobe_sites(ctx: SpecContext):
    c = ctx.spec.contingency
    for s in c.stimuli:
        yield f"contingency.stimuli.{s.id}.on_code", s.on_code
    for pname, port in c.ports.items():
        for fld in ("enter_code", "error_code", "break_code", "exit_code",
                    "reward_code", "reward_stop_code"):
            val = getattr(port, fld)
            if val is not None:
                yield f"contingency.ports.{pname}.{fld}", val
    for name, o in c.outcome_map.items():
        if o.strobe_declared:
            yield f"contingency.outcome_map.{name}.strobe", o.strobe


@rule(
    "TG210",
    name="unknown-strobe",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help=(
        "Strobe names resolve against schema/strobe_vocab.v1.json. Add the code there -- append-only, next "
        "free number, with a rationale -- or fix the spelling."
    ),
)
def unknown_strobe(ctx: SpecContext) -> Iterator[Diagnostic]:
    """A strobe name not in the append-only vocabulary.

    Ephymeris records a real bug where a sketch emitted codes it had not declared:
    nothing errored, and every layer degraded silently. Resolution is by name and
    never by arithmetic, because the codes are non-contiguous and non-patterned.
    """
    for loc, value in _strobe_sites(ctx):
        if value is None or value.startswith("@"):
            continue
        if value not in ctx.vocab:
            yield _err(ctx, "TG210", loc, f"undeclared strobe {value!r}")


@rule(
    "TG231",
    name="null-strobe",
    severity=Severity.WARN,
    pass_=Pass.BIND,
    help=(
        "A silent transition is invisible in the record. Whether that is right depends on whether this "
        "spec has an equivalence target -- see the detail."
    ),
    decision="D4",
)
def null_strobe(ctx: SpecContext) -> Iterator[Diagnostic]:
    """`strobe: null` — legal, and sometimes exactly right.

    The message branches on meta.reproduces_sketch, because "matches runTrial()"
    and "is well designed" are different goals and that field says which one
    applies. A spec with an equivalence target MUST stay silent here; one without
    is probably leaving an event unrecorded.
    """
    reproducing = ctx.spec.meta.reproduces_sketch
    for name, o in ctx.spec.contingency.outcome_map.items():
        if not (o.strobe_declared and o.strobe is None):
            continue
        loc = f"contingency.outcome_map.{name}.strobe"
        if reproducing:
            yield _warn(
                ctx, "TG231", loc,
                "emits no strobe — deliberate, and required here",
                detail=(
                    f"{ctx.spec_id} reproduces {reproducing}.\n"
                    "Current firmware emits nothing when the response window expires\n"
                    "(BehaviorBox.h:1090-1091), so an omission is inferable only from the\n"
                    "absence of a poke before END_INCORRECT_ITI."
                ),
                help=("Do NOT add RESP_OMIT here — emitting it would break bit-identity with "
                      "runTrial() and fail the Phase 3 equivalence gate."),
                decision="D4",
            )
        else:
            yield _warn(
                ctx, "TG231", loc,
                "emits no strobe, and this spec has no equivalence target",
                help=("Consider RESP_OMIT (262), as seq2_retention does. Silence is only "
                      "required where bit-identity with runTrial() demands it."),
                decision="D4",
            )


# --------------------------------------------------------------------------- #
# References
# --------------------------------------------------------------------------- #


@rule(
    "TG220",
    name="unresolved-reference",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Ports, stimuli and trial types must be declared before they are referenced.",
)
def unresolved_reference(ctx: SpecContext) -> Iterator[Diagnostic]:
    c = ctx.spec.contingency
    ports, stimuli = set(c.ports), {s.id for s in c.stimuli}
    tts = {t.id for t in c.trial_types}

    for p in ctx.spec.topology.response_ports:
        if p not in ports:
            yield _err(ctx, "TG220", "topology.response_ports", f"undeclared port {p!r}")

    for t in c.trial_types:
        for stage in t.stages:
            if stage not in stimuli:
                yield _err(ctx, "TG220", f"contingency.trial_types.{t.id}.stages",
                           f"undeclared stimulus {stage!r}")
        if t.target is not None and t.target not in ports:
            yield _err(ctx, "TG220", f"contingency.trial_types.{t.id}.target",
                       f"undeclared port {t.target!r}")

    for i, row in enumerate(c.context_schedule):
        for tt_id, target in row.targets.items():
            if tt_id not in tts:
                yield _err(ctx, "TG220", f"contingency.context_schedule[{i}].targets.{tt_id}",
                           f"undeclared trial type {tt_id!r}")
            if target is not None and target not in ports:
                yield _err(ctx, "TG220", f"contingency.context_schedule[{i}].targets.{tt_id}",
                           f"undeclared port {target!r}")

    for name, o in c.outcome_map.items():
        if o.reward and not o.reward.startswith("@") and o.reward not in ports:
            yield _err(ctx, "TG220", f"contingency.outcome_map.{name}.reward",
                       f"undeclared port {o.reward!r}")


@rule(
    "TG221",
    name="stage-count-mismatch",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help=(
        "stages[] must hold exactly n_sampling_stages entries -- that is what makes "
        "@stim[$stage] resolvable for every trial type."
    ),
)
def stage_count_mismatch(ctx: SpecContext) -> Iterator[Diagnostic]:
    n = ctx.spec.topology.n_sampling_stages
    for t in ctx.spec.contingency.trial_types:
        if len(t.stages) != n:
            yield _err(ctx, "TG221", f"contingency.trial_types.{t.id}.stages",
                       f"{len(t.stages)} stimuli declared, topology.n_sampling_stages is {n}")


@rule(
    "TG223",
    name="unknown-channel",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Channel names resolve against schema/channels.v1.json, which transcribes the box pinout.",
    decision="D15",
)
def unknown_channel(ctx: SpecContext) -> Iterator[Diagnostic]:
    c = ctx.spec.contingency
    for s in c.stimuli:
        if s.emitter not in ctx.channels:
            yield _err(ctx, "TG223", f"contingency.stimuli.{s.id}.emitter",
                       f"unknown channel {s.emitter!r}")
    for pname, port in c.ports.items():
        if port.channel not in ctx.channels:
            yield _err(ctx, "TG223", f"contingency.ports.{pname}.channel",
                       f"unknown channel {port.channel!r}")
        if port.reward_line and port.reward_line not in ctx.channels:
            yield _err(ctx, "TG223", f"contingency.ports.{pname}.reward_line",
                       f"unknown channel {port.reward_line!r}")


@rule(
    "TG224",
    name="reward-line-wrong-well",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="A port's reward_line must serve that port. Check the `well` field in schema/channels.v1.json.",
)
def reward_line_wrong_well(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Reward delivered to the wrong side of the box.

    This mistake looks entirely correct in the listing -- the graph is well-formed,
    the pulse fires, the strobe is emitted -- and surfaces only as an animal that
    will not learn. The channel registry declares which port each fluid line serves
    precisely so it is catchable statically.
    """
    for pname, port in ctx.spec.contingency.ports.items():
        if not port.reward_line:
            continue
        line = ctx.channels.get(port.reward_line)
        if line is None or line.well is None:
            continue
        if line.well != port.channel:
            yield _err(ctx, "TG224", f"contingency.ports.{pname}.reward_line",
                       f"{port.reward_line!r} serves {line.well!r}, but this port is {port.channel!r}",
                       help="Water would be delivered to the opposite well.")


@rule(
    "TG225",
    name="engagement-channel-unresolvable",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="Exactly one channel in schema/channels.v1.json must carry kind `engagement`.",
    decision="D15",
)
def engagement_channel_unresolvable(ctx: SpecContext) -> Iterator[Diagnostic]:
    """No spec names the engagement port -- the template resolves it by kind. With
    zero or two, that resolution picks wrong or crashes, and every trial in every
    task routes through it."""
    if ctx.channels.unique_of_kind("engagement") is None:
        found = [c.name for c in ctx.channels.of_kind("engagement")]
        yield _err(ctx, "TG225", "schema/channels.v1.json",
                   f"expected exactly one channel of kind 'engagement', found {len(found)}: {found}")


# --------------------------------------------------------------------------- #
# Representability and policy
# --------------------------------------------------------------------------- #


@rule(
    "TG230",
    name="context-schedule-unsupported",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help=(
        "Remove the context_schedule, or add a block-boundary record to the table "
        "format and bump its version first."
    ),
    decision="D16",
)
def context_schedule_unsupported(ctx: SpecContext) -> Iterator[Diagnostic]:
    """A non-empty context_schedule has no on-board representation yet.

    TaskTable.h has TgStageRow and TgTimingSet for layer 3 and no record at all for
    layer-2 block boundaries. Compiling it away silently would be exactly the class
    of failure this project exists to close: a reversal the spec declares, the
    listing shows, and the board never performs.
    """
    n = len(ctx.spec.contingency.context_schedule)
    if n:
        yield _err(ctx, "TG230", "contingency.context_schedule",
                   f"{n} block boundary/-ies declared, but table v1 cannot represent them",
                   detail=("Reversals are the headline claim of layer 2 and will be supported --\n"
                           "but silently dropping them is worse than refusing to compile."))


@rule(
    "TG240",
    name="escalation-target-undeclared",
    severity=Severity.ERROR,
    pass_=Pass.BIND,
    help="penalty_escalation.applies_to must name an outcome class this spec declares.",
)
def escalation_target_undeclared(ctx: SpecContext) -> Iterator[Diagnostic]:
    esc = ctx.spec.policy.penalty_escalation
    if esc and esc.applies_to not in ctx.spec.contingency.outcome_map:
        yield _err(ctx, "TG240", "policy.penalty_escalation.applies_to",
                   f"{esc.applies_to!r} is not a declared outcome class",
                   detail=f"declared: {sorted(ctx.spec.contingency.outcome_map)}")


@rule(
    "TG241",
    name="escalation-clears-on-engagement",
    severity=Severity.WARN,
    pass_=Pass.BIND,
    help="Prefer clears_on: TRIAL_CORRECT. See the detail for why this particular value is dangerous.",
    decision="D4",
)
def escalation_clears_on_engagement(ctx: SpecContext) -> Iterator[Diagnostic]:
    """ANY_ENGAGEMENT *is* the poke-to-reset loophole.

    Closed once in C++ and reopened once already by a copy-paste into the EZ
    sketch. On a spec with an equivalence target it is an outright ERROR because it
    cannot match runTrial(); elsewhere a warning, because a future task might
    genuinely want it and should have to say so deliberately.
    """
    esc = ctx.spec.policy.penalty_escalation
    if not esc or esc.clears_on != "ANY_ENGAGEMENT":
        return
    detail = (
        "BehaviorBox.h:1171-1174: 'the abstention escalator is NOT reset here. A bare\n"
        "odor-poke (or a poke-and-bail) must not defuse the lazy penalty -- only a\n"
        "completed CORRECT trial clears it... This closes the poke-to-reset loophole,\n"
        "which the old EZ copy of this loop had reopened.'"
    )
    reproducing = ctx.spec.meta.reproduces_sketch
    loc = "policy.penalty_escalation.clears_on"
    if reproducing:
        yield _err(ctx, "TG241", loc, "ANY_ENGAGEMENT cannot reproduce runTrial()",
                   detail=detail,
                   help=f"{ctx.spec_id} reproduces {reproducing}; use TRIAL_CORRECT.",
                   decision="D4")
    else:
        yield _warn(ctx, "TG241", loc,
                    "ANY_ENGAGEMENT lets a bare poke defuse the abstention penalty",
                    detail=detail,
                    help="Use TRIAL_CORRECT unless this task genuinely wants the loophole.")


@rule(
    "TG232",
    name="wire-key-conflict",
    severity=Severity.WARN,
    pass_=Pass.BIND,
    help=(
        "Two timing ids share a START token but hold different values; the legacy path "
        "supplies one number for both."
    ),
    decision="D8",
)
def wire_key_conflict(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Many-to-one wire keys are deliberate -- odorPokeHold drives two states -- but
    only while the values agree. The moment they diverge, one silently wins."""
    by_key: dict[str, list] = {}
    for t in ctx.spec.timing:
        if t.wire_key:
            by_key.setdefault(t.wire_key, []).append(t)
    for key, entries in by_key.items():
        if len({t.ms for t in entries}) > 1:
            ids = ", ".join(f"{t.id}={t.ms}" for t in entries)
            yield _warn(ctx, "TG232", "timing",
                        f"wire_key {key!r} maps to differing values: {ids}",
                        help=("One START token supplies all of them, so one value silently wins. "
                              "Give them distinct wire keys, or align the values."))
