"""One run, scored — `ANALYTICS.md#how-a-strobe-stream-is-scored`.

`summarize(document, profile)` is the whole job: every declared metric replayed
through the live accumulator, the pooled figure, the outcome tally, the
per-condition tally and the engagement ladder, as one `RunSummary`. A spine
run is scored by replay instead (`ANALYTICS.md#how-a-spine-run-is-scored`):
its trial table, and the metrics that are functions of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ...tasks.profile import LiveMetric, TaskProfile
from .document import _duration_ms, codes_of
from . import table_metrics
from .spine import Divergence, SpineDecodeError, is_spine_run, replayed
from .engagement import TrialEngagement, engagement_of
from .outcomes import ConditionOutcomes, TrialOutcomes, conditions_of, outcomes_of
from .metric_summary import OVERALL_ID, MetricSummary
from .stats import wilson_interval
from .trials import MetricAccumulator, boundaries_for


@dataclass(frozen=True)
class RunSummary:
    """Everything the cohort-scale panels need about one animal's run."""

    status: str  # 'ok' | 'no-metrics' | 'diverged' | 'unreplayable' | 'missing' | 'unreadable'
    metrics: list[MetricSummary] = field(default_factory=list)
    #: Accuracy pooled across every metric — see `_overall`. The honest single
    #: number for a run, and every per-run readout's default.
    overall: MetricSummary | None = None
    #: None when the profile doesn't declare the outcome vocabulary
    #: (`ANALYTICS.md#rewarded-and-response-accuracy`) —
    #: absent rather than zeroed, because "this task has no notion of a reward
    #: delivery" and "this animal earned nothing" are different claims.
    outcomes: TrialOutcomes | None = None
    #: The same tally split per declared condition
    #: (`ANALYTICS.md#per-condition-tally`). Empty — not None —
    #: when `outcomes` is None: there is no separate claim to make about a task
    #: whose vocabulary can't express an outcome at all.
    conditions: list[ConditionOutcomes] = field(default_factory=list)
    #: How many trials the box *offered*, and how far each got
    #: (`ANALYTICS.md#engagement-ladder`). None on
    #: a profile that declares no trial light — same rule as `outcomes`, and for
    #: the same reason: a zeroed ladder would read as an animal that never
    #: engaged rather than as a task that can't say.
    engagement: TrialEngagement | None = None
    total_events: int = 0
    duration_ms: int | None = None
    stop_reason: str | None = None
    clean: bool = False
    seed: int | None = None
    detail: str | None = None
    #: A `kind: "utility"` profile is scored if it declares metrics, but left
    #: out of cohort aggregates unless asked for (`ANALYTICS.md#edge-cases`).
    excluded_by_default: bool = False
    #: A spine run's tallies from its trial table, when replay scored it
    #: (`ANALYTICS.md#metrics-from-the-trial-table`). None for every other run.
    replay: table_metrics.ReplayScore | None = None
    #: Where a `diverged` run's strobes leave what replay predicts.
    divergence: Divergence | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metrics": [m.to_json() for m in self.metrics],
            "overall": self.overall.to_json() if self.overall else None,
            "outcomes": self.outcomes.to_json() if self.outcomes else None,
            "conditions": [c.to_json() for c in self.conditions],
            "engagement": self.engagement.to_json() if self.engagement else None,
            "totalEvents": self.total_events,
            "durationMs": self.duration_ms,
            "stopReason": self.stop_reason,
            "clean": self.clean,
            "seed": self.seed,
            "detail": self.detail,
            "excludedByDefault": self.excluded_by_default,
            "replay": self.replay.to_json() if self.replay else None,
            "divergence": self.divergence.to_json() if self.divergence else None,
        }


#: The clean-end reason, matching `sessions/runner.py`'s literal exactly.
CLEAN_STOP_REASON = "BF_END_SESSION received"


#: Below this many counted trials a value is flagged rather than trusted. The
#: sidecar never suppresses — it reports the number, the count, the interval
#: and this flag, and presentation decides what to do
#: (`ANALYTICS.md#uncertainty`).
DEFAULT_MIN_COUNTED = 10


def summarize(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    min_counted: int = DEFAULT_MIN_COUNTED,
) -> RunSummary:
    """Score one recorded run (`ANALYTICS.md#how-a-strobe-stream-is-scored`)."""
    codes = codes_of(document)
    stop_reason = document.get("stop_reason")
    stop_reason = stop_reason if isinstance(stop_reason, str) else None

    duration = _duration_ms(document)
    seed = document.get("trial_seed")
    seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None

    base = {
        "total_events": len(codes),
        "duration_ms": duration,
        "stop_reason": stop_reason,
        "clean": stop_reason == CLEAN_STOP_REASON,
        "seed": seed,
    }

    # A spine run is scored by replay and nothing else: never by the legacy
    # scorer, whose onset-shaped names its edge codes would only mimic
    # (`ANALYTICS.md#how-a-spine-run-is-scored`).
    if is_spine_run(document):
        return _replay_summary(document, base, min_counted)

    # A sketch with no Task Profile is fully supported (`ANALYTICS.md#edge-cases`)
    # and still worth listing — it has a real duration, event count and stop
    # reason. Inventing a default metric for it would be worse than saying so.
    if profile is None or not profile.live_metrics:
        return RunSummary(status="no-metrics", **base)

    boundaries = boundaries_for(profile)
    scored = [
        _summarize_metric(metric, codes, boundaries, min_counted, profile)
        for metric in profile.live_metrics
    ]
    metrics = [entry.summary for entry in scored]
    return RunSummary(
        status="ok",
        metrics=metrics,
        overall=_overall(scored, min_counted),
        outcomes=outcomes_of(codes, profile),
        conditions=conditions_of(codes, profile),
        engagement=engagement_of(codes, profile),
        excluded_by_default=profile.kind == "utility",
        **base,
    )


def _replay_summary(document: dict[str, Any], base: dict[str, Any], min_counted: int) -> RunSummary:
    """A spine run: `ok` with its trial-table metrics, `diverged`, or `unreplayable`."""
    try:
        result = replayed(document)
    except SpineDecodeError as exc:
        return RunSummary(status="unreplayable", detail=f"replay cannot run this spine run: {exc}", **base)
    if result.divergence is not None:
        return RunSummary(status="diverged", detail=result.divergence.detail,
                          divergence=result.divergence, **base)
    score = table_metrics.score(result.trials, rows=result.rows, interp=result.interp)
    return RunSummary(
        status="ok",
        metrics=table_metrics.correct_metrics(score, min_counted=min_counted),
        overall=table_metrics.overall_correct(score, min_counted=min_counted),
        replay=score,
        **base,
    )


def with_threshold(payload: dict[str, Any], min_counted: int) -> dict[str, Any]:
    """A summary payload judged against `min_counted`, as a copy.

    `lowConfidence` is the only part of a summary the threshold touches, and it
    is `counted < min_counted` for each metric and the pooled figure. The
    threshold is a per-request argument (`analytics.summary`'s
    `minCountedTrials`) while the payload is cached, so the flag is re-judged on
    every row served rather than kept from whichever request computed it
    (`DATA.md#caching`).
    """
    def judged(metric: Any) -> Any:
        if not isinstance(metric, dict) or not isinstance(metric.get("counted"), int):
            return metric
        return {**metric, "lowConfidence": metric["counted"] < min_counted}

    out = dict(payload)
    if isinstance(out.get("metrics"), list):
        out["metrics"] = [judged(metric) for metric in out["metrics"]]
    if out.get("overall") is not None:
        out["overall"] = judged(out["overall"])
    return out




@dataclass(frozen=True)
class _Scored:
    """One metric's summary plus the integer numerator behind it.

    `MetricSummary` carries P(hit) as a float because that is what the wire
    wants. Pooling needs the hit *count*, and recovering it as
    `round(p * counted)` means reconstructing an integer from a quotient of
    itself — correct at any n this app will ever see, and still a reconstruction
    of something that was already known exactly. Carrying it costs a field.
    """

    summary: MetricSummary
    hits: int


def _overall(scored: list[_Scored], min_counted: int) -> MetricSummary | None:
    """Accuracy pooled across every metric — correct trials over scored trials.

    Why this exists, and why it is every per-run readout's default: **a single
    metric cannot show a side bias.** An animal that pokes right on every trial
    scores ~1.0 on "P(R | Odor 1)" and ~0.0 on "P(L | Odor 3)", so a readout
    keyed on the first metric alone paints a completely bias-locked animal as one of the
    best in the cohort. Pooling puts it at chance, which is the truth.

    Pooled by summing hits and trials rather than averaging the two
    proportions, so a session that scored 90 odor-1 trials and 10 odor-3 trials
    is weighted the way it actually happened.

    **The rate pools only conditions that scored; the trial counts pool all of
    them.** A condition that fired twenty times and was never answered
    contributes nothing to P — there is no proportion to weight — but those
    twenty trials are exactly what `triggered` and `excluded` exist to report,
    and dropping them made the pooled row claim the animal was never offered
    them. Counting all of them also keeps the identity
    `triggered == counted + excluded` true of the pooled row, which is what
    makes it readable next to the per-condition rows above it.
    """
    with_trials = [
        entry for entry in scored
        if entry.summary.p_session is not None and entry.summary.counted > 0
    ]
    if not with_trials:
        return None
    counted = sum(entry.summary.counted for entry in with_trials)
    hits = sum(entry.hits for entry in with_trials)
    interval = wilson_interval(hits, counted)
    return MetricSummary(
        id=OVERALL_ID,
        label="Overall accuracy",
        p_session=hits / counted,
        p_window=None,
        hits=hits,
        counted=counted,
        triggered=sum(entry.summary.triggered for entry in scored),
        excluded=sum(entry.summary.excluded for entry in scored),
        window_size=0,
        wilson_low=interval[0] if interval else None,
        wilson_high=interval[1] if interval else None,
        low_confidence=counted < min_counted,
        # The pooled figure spans every condition, so it is not answered at any
        # one side and has no axis. Its own kind of null, not a missing one.
        answer_side=None,
    )


def _summarize_metric(
    metric: LiveMetric,
    codes: list[int],
    boundaries: frozenset[int],
    min_counted: int,
    profile: TaskProfile | None = None,
) -> _Scored:
    """One replay of the stream through the live accumulator, read two ways.

    The rolling value is the accumulator's window — literally what Mission
    Control displayed. The whole-session value is `hits / counted` over every
    trial the same accumulator scored, so the two differ *only* in the
    averaging window and cannot drift apart in how a trial is classified.

    This used to replay the stream a second time through a window widened past
    the session length to get the whole-session figure. Same number by
    construction (a window that can't fill is no window), one less pass, and no
    dependence on the widened window actually being wide enough.
    """
    accumulator = MetricAccumulator(metric, boundaries)
    for code in codes:
        accumulator.offer(code)

    counted = accumulator.counted_total
    hits = accumulator.hits_total
    triggered = codes.count(metric.trigger_code)
    p_session = hits / counted if counted else None
    p_window = accumulator.value().value

    interval = wilson_interval(hits, counted) if counted else None

    return _Scored(
        summary=MetricSummary(
            id=metric.id,
            label=metric.label,
            p_session=p_session,
            p_window=p_window,
            hits=hits,
            counted=counted,
            triggered=triggered,
            # Trials where neither response arrived before the next boundary —
            # lazy, invalid, or no-response. Meaningful in its own right: 200
            # triggers with 90 counted is a very different session from 200 with
            # 195, at identical P(correct).
            excluded=max(0, triggered - counted),
            window_size=metric.window_size,
            wilson_low=interval[0] if interval else None,
            wilson_high=interval[1] if interval else None,
            low_confidence=counted < min_counted,
            answer_side=answer_side_of(profile, metric),
        ),
        hits=hits,
    )


#: `WATER_POKE_L` → left. Mirrors `infer.py`'s `_side_label` and the frontend's
#: `correctWellOf`, all three reading the historical suffix rather than assuming
#: it: a rig whose response ports carry no side keeps its slot number.
_ANSWER_SIDE = re.compile(r"^WATER_POKE_(?:PORT_(?P<slot>\d+)|(?P<side>L|R))$")


def answer_side_of(profile: TaskProfile | None, metric: LiveMetric) -> str | None:
    """Which answer a condition rewards — `left`, `right`, `withhold`, `port`.

    > [!CAUTION]
    > **From `success_code` and nothing else.** The tempting fallback — try
    > `alternate_code` when the success code is not a well — is wrong in a way
    > that prints a confident lie: a no-go metric's alternates are *every
    > response port* (the generator's `_enter_codes`, `infer.no_go_alternates`), so
    > the fallback answers "left well" for a condition whose correct answer
    > is to poke nothing. `None` is the honest result whenever the profile
    > cannot prove one, and every consumer treats it as "this condition has no axis" rather than filling it in.
    """
    if profile is None:
        return None
    name = (profile.strobes.get(metric.success_code) or "").strip().upper()
    if not name:
        return None
    if name == "WATER_POKE_NONE":
        return "withhold"
    match = _ANSWER_SIDE.match(name)
    if match is None:
        return None
    if match.group("slot"):
        return "port"
    return "left" if match.group("side") == "L" else "right"


def live_equivalent(
    profile: TaskProfile | None, codes: list[int]
) -> list[tuple[str, float | None, int]]:
    """Replay `codes` through the *live* accumulators, for test comparison.

    Exists so a test can assert the offline path agrees with what Mission
    Control displayed, rather than trusting that it does.
    """
    if profile is None:
        return []
    boundaries = boundaries_for(profile)
    accumulators = [MetricAccumulator(m, boundaries) for m in profile.live_metrics]
    for code in codes:
        for accumulator in accumulators:
            accumulator.offer(code)
    return [(a.id, a.value().value, a.value().n) for a in accumulators]
