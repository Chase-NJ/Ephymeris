"""TG3xx — template and topology agreement.

Checked BEFORE the template runs. A template asked for a topology it does not
support, or a spec declaring outcome classes the topology cannot produce, is a
disagreement about what the task even is -- and every later pass would be
analysing a graph built on that misunderstanding.
"""

from __future__ import annotations

from collections.abc import Iterator

from ephymeris_sidecar.taskgraph import templates
from ephymeris_sidecar.taskgraph.context import SpecContext
from ephymeris_sidecar.taskgraph.errors import Diagnostic, Severity
from ephymeris_sidecar.taskgraph.lint import Pass, rule


def _err(ctx: SpecContext, code: str, loc: str, msg: str, **kw) -> Diagnostic:
    return Diagnostic(
        code=code, severity=Severity.ERROR, spec_id=ctx.spec_id, location=loc, message=msg, **kw
    )


@rule(
    "TG301",
    name="unknown-template",
    severity=Severity.ERROR,
    pass_=Pass.TEMPLATE,
    help=(
        "topology.template + template_version must name a file under templates/. A template "
        "is versioned BY FILE and never edited once pinned."
    ),
    decision="D14",
)
def unknown_template(ctx: SpecContext) -> Iterator[Diagnostic]:
    t = ctx.spec.topology
    try:
        templates.load(t.template, t.template_version)
    except templates.TemplateNotFound as exc:
        yield _err(ctx, "TG301", "topology.template", str(exc))


@rule(
    "TG302",
    name="outcome-classes-disagree",
    severity=Severity.ERROR,
    pass_=Pass.TEMPLATE,
    help=(
        "Declare exactly the outcome classes this topology produces. A missing class is a "
        "missing edge; an extra one is a branch nothing routes to."
    ),
)
def outcome_classes_disagree(ctx: SpecContext) -> Iterator[Diagnostic]:
    """Checked in BOTH directions, because the two failures differ.

    A class the topology produces but the spec omits is a MISSING EDGE -- the
    template has nowhere to send that outcome, which is a hang. A class the spec
    declares but the topology cannot produce is a DEAD BRANCH: harmless at runtime,
    but it means the author believes the task does something it does not, and the
    listing will show a state no trial can ever enter.
    """
    t = ctx.spec.topology
    try:
        mod = templates.load(t.template, t.template_version)
    except templates.TemplateNotFound:
        return  # TG301 already reported it

    produced = mod.capabilities(t).outcome_classes
    declared = set(ctx.spec.contingency.outcome_map)

    for cls in sorted(produced - declared):
        yield _err(
            ctx, "TG302", "contingency.outcome_map",
            f"this topology produces the outcome class {cls!r}, which the spec does not declare",
            detail=(
                f"template {t.template} v{t.template_version} with "
                f"response_mode={t.response_mode}, commit_hold={t.commit_hold}, "
                f"n_sampling_stages={t.n_sampling_stages}\n"
                "Without it the template has nowhere to route that outcome."
            ),
        )
    for cls in sorted(declared - produced):
        yield _err(
            ctx, "TG302", f"contingency.outcome_map.{cls}",
            f"outcome class {cls!r} cannot occur with this topology",
            detail=(
                f"response_mode={t.response_mode} produces: {', '.join(sorted(produced))}\n"
                "Nothing would ever route here."
            ),
        )


@rule(
    "TG303",
    name="missing-required-timing",
    severity=Severity.ERROR,
    pass_=Pass.TEMPLATE,
    help="The template's required timing ids are a function of the topology knobs. Add the missing entries.",
)
def missing_required_timing(ctx: SpecContext) -> Iterator[Diagnostic]:
    """The required set is COMPUTED, not a fixed list.

    A one-stage task needs `t_sample_hold`; a chain needs `t_sample_hold_0`,
    `_1`, ... so each stage is independently rampable. Comparing against a static
    list would either reject valid chains or accept a chain missing half its
    durations.
    """
    t = ctx.spec.topology
    try:
        mod = templates.load(t.template, t.template_version)
    except templates.TemplateNotFound:
        return

    have = {e.id for e in ctx.spec.timing}
    for tid in mod.capabilities(t).required_timing:
        if tid not in have:
            yield _err(
                ctx, "TG303", "timing",
                f"template requires timing id {tid!r}, which this spec does not declare",
            )


@rule(
    "TG304",
    name="outcome-trigger-missing",
    severity=Severity.ERROR,
    pass_=Pass.TEMPLATE,
    help=(
        "Declare `trigger:` on every outcome. Which trigger routes to which outcome is the "
        "whole mechanism behind go/no-go's inversion."
    ),
    decision="D9",
)
def outcome_trigger_missing(ctx: SpecContext) -> Iterator[Diagnostic]:
    """`trigger` is optional in the schema but load-bearing in the model.

    "correct = TIMEOUT" on a withhold window is a DECLARATION, not a special case
    -- that is what lets the interpreter never branch on response_mode. If the
    field is absent the template would have to guess, which is precisely the class
    of implicit behaviour this project exists to remove.
    """
    for name, o in ctx.spec.contingency.outcome_map.items():
        if o.trigger is None:
            yield _err(
                ctx, "TG304", f"contingency.outcome_map.{name}",
                "no `trigger:` declared",
                detail="Scoring is an edge effect; the trigger says which edge carries it.",
            )
