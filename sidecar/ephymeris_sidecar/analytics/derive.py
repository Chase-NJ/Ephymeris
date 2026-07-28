"""Metrics derived from a recorded session — `analytics.md` §3.

**Pure.** No I/O, no database, no clock. `(document, profile)` in, summary or
series out — which is what makes it assertable against the live path over a
recorded stream, and is the whole reason it is a separate module.

Nothing here reimplements scoring. `tasks/metrics.py` already replays a stream
and is the definition of a trial; this module loads a document, picks a
profile, and calls that machinery. The three things it must get right are the
three that would be silently wrong rather than loudly broken, and each has a
comment saying so where it happens.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Iterator

from ..tasks.metrics import MetricAccumulator, compute_series
from ..tasks.profile import LiveMetric, TaskProfile

#: Bumped whenever the maths below changes. Cached summaries carry the version
#: they were computed under and are recomputed when it moves — without this, a
#: fixed bug would keep serving numbers from the old definition forever, with
#: no symptom anywhere (`analytics.md` §8.3).
#: v3 added the trial-outcome tally (§3.8) — rewarded vs side accuracy.
#: v4 split that tally per declared condition (§3.9), so "how many go-right
#: trials were administered, and how many of those paid out" is answerable
#: without re-reading the file.
CODEC_VERSION = 4

#: z for a 95% interval. Wilson rather than the normal approximation because
#: this data lives at small n *and* at p near 1 — a trained animal sits around
#: 0.95 — which is exactly where the normal approximation runs past 1.0 (§3.5).
Z_95 = 1.959964


def boundaries_for(profile: TaskProfile | None) -> frozenset[int]:
    """Every trigger code in the profile — the trial-boundary set.

    **Use this everywhere.** `MetricSet` builds this union for the live run
    (`tasks/metrics.py:109`), but `compute_series` defaults to *only* the
    metric's own trigger (`:139`). For a profile with more than one metric
    those differ, and the difference is not cosmetic: a trial where the first
    odor fires, the animal does not respond, and the second odor fires next is
    **excluded** live and **mis-scored** offline under the default, because the
    later response gets attributed to the abandoned trial.
    """
    if profile is None:
        return frozenset()
    return frozenset(m.trigger_code for m in profile.live_metrics)


def wilson_interval(hits: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """95% Wilson score interval for `hits` of `n`, or `None` when n is 0."""
    if n <= 0:
        return None
    p = hits / n
    z2 = z * z
    denominator = 1 + z2 / n
    centre = p + z2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


@dataclass(frozen=True)
class MetricSummary:
    """One metric's whole-session result (§3.2, §3.3, §3.5)."""

    id: str
    label: str
    #: Whole-session P(hit) — the summary statistic used by every panel.
    p_session: float | None
    #: Rolling P(hit) at the profile's authored window, for continuity with
    #: what the operator watched live. **Not** interchangeable with the above:
    #: they diverge sharply over the first `windowSize` trials.
    p_window: float | None
    counted: int
    triggered: int
    excluded: int
    window_size: int
    wilson_low: float | None
    wilson_high: float | None
    low_confidence: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "pSession": _round(self.p_session),
            "pWindow": _round(self.p_window),
            "counted": self.counted,
            "triggered": self.triggered,
            "excluded": self.excluded,
            "windowSize": self.window_size,
            "wilsonLow": _round(self.wilson_low),
            "wilsonHigh": _round(self.wilson_high),
            "lowConfidence": self.low_confidence,
        }


@dataclass(frozen=True)
class TrialOutcomes:
    """What actually happened on each trial (§3.8).

    The declared metrics are **reward-unconditional**: `tasks/metrics.py` scores
    a `WATER_POKE_L/R` the instant the poke is detected, so an animal that
    reaches the correct well and releases before the fluid hold still scores a
    hit. That is the right definition for a live discrimination readout — it
    measures the choice, not the consummatory hold — but it is not the same
    question as "how often did this animal actually earn water", and averaging
    the two together would quietly answer neither.

    So this tally separates them:

    * **rewarded accuracy** = `rewarded / administered` — fluid actually
      delivered. Conservative: a hold failure counts against it.
    * **side accuracy** = `(rewarded + hold_failed) / administered` — the
      correct *side* was chosen, whether or not the hold earned the drop. This
      is the discrimination figure, and is always ≥ rewarded accuracy.

    The gap between the two is the consummatory hold failure rate, which is a
    real and separately interesting behaviour rather than noise.
    """

    #: Every trial boundary seen — one per odor onset.
    trials: int = 0
    #: Odor sampled to completion; the denominator for both accuracies. A trial
    #: the animal never engaged is not evidence about discrimination.
    administered: int = 0
    rewarded: int = 0
    #: Correct well reached, released before the hold cleared — no fluid.
    hold_failed: int = 0
    wrong_well: int = 0
    #: Administered, but no well was ever answered before the next trial.
    no_response: int = 0
    #: Never administered: the odor port was left early, or never poked at all.
    aborted: int = 0

    @property
    def p_rewarded(self) -> float | None:
        return self.rewarded / self.administered if self.administered else None

    @property
    def p_side(self) -> float | None:
        if not self.administered:
            return None
        return (self.rewarded + self.hold_failed) / self.administered

    def to_json(self) -> dict[str, Any]:
        rewarded_interval = wilson_interval(self.rewarded, self.administered)
        side_interval = wilson_interval(self.rewarded + self.hold_failed, self.administered)
        return {
            "trials": self.trials,
            "administered": self.administered,
            "rewarded": self.rewarded,
            "holdFailed": self.hold_failed,
            "wrongWell": self.wrong_well,
            "noResponse": self.no_response,
            "aborted": self.aborted,
            "pRewarded": _round(self.p_rewarded),
            "pSide": _round(self.p_side),
            "rewardedLow": _round(rewarded_interval[0] if rewarded_interval else None),
            "rewardedHigh": _round(rewarded_interval[1] if rewarded_interval else None),
            "sideLow": _round(side_interval[0] if side_interval else None),
            "sideHigh": _round(side_interval[1] if side_interval else None),
        }


@dataclass(frozen=True)
class ConditionOutcomes:
    """The same tally as `TrialOutcomes`, restricted to one declared condition
    (§3.9).

    A condition is a declared `liveMetrics` entry, identified by the trigger
    code that opens its trials — for GRGL that is odor 1 (answer right) and
    odor 3 (answer left), so this is what makes "how many go-right trials were
    administered, and how many of those paid out" answerable. Driven off the
    profile's authored metrics rather than any particular task's vocabulary: a
    profile declaring five conditions gets five of these.

    Two metrics sharing a trigger code would legitimately produce two entries
    over the same trials — the trigger is what delimits a condition, and a
    profile that declares the same trials twice is asking for exactly that.
    """

    metric_id: str
    label: str
    trigger_code: int
    outcomes: TrialOutcomes

    def to_json(self) -> dict[str, Any]:
        return {
            "metricId": self.metric_id,
            "label": self.label,
            "triggerCode": self.trigger_code,
            "outcomes": self.outcomes.to_json(),
        }


@dataclass(frozen=True)
class RunSummary:
    """Everything the cohort-scale panels need about one animal's run."""

    status: str  # 'ok' | 'no-metrics' | 'missing' | 'unreadable'
    metrics: list[MetricSummary] = field(default_factory=list)
    #: Accuracy pooled across every metric — see `_overall`. The honest single
    #: number for a run, and the heatmap's default.
    overall: MetricSummary | None = None
    #: None when the profile doesn't declare the outcome vocabulary (§3.8) —
    #: absent rather than zeroed, because "this task has no notion of a reward
    #: delivery" and "this animal earned nothing" are different claims.
    outcomes: TrialOutcomes | None = None
    #: The same tally split per declared condition (§3.9). Empty — not None —
    #: when `outcomes` is None: there is no separate claim to make about a task
    #: whose vocabulary can't express an outcome at all.
    conditions: list[ConditionOutcomes] = field(default_factory=list)
    total_events: int = 0
    duration_ms: int | None = None
    stop_reason: str | None = None
    clean: bool = False
    seed: int | None = None
    detail: str | None = None
    #: A `kind: "utility"` profile is scored if it declares metrics, but left
    #: out of cohort aggregates unless asked for (§3.6).
    excluded_by_default: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "metrics": [m.to_json() for m in self.metrics],
            "overall": self.overall.to_json() if self.overall else None,
            "outcomes": self.outcomes.to_json() if self.outcomes else None,
            "conditions": [c.to_json() for c in self.conditions],
            "totalEvents": self.total_events,
            "durationMs": self.duration_ms,
            "stopReason": self.stop_reason,
            "clean": self.clean,
            "seed": self.seed,
            "detail": self.detail,
            "excludedByDefault": self.excluded_by_default,
        }


@dataclass(frozen=True)
class MetricSeries:
    id: str
    label: str
    values: list[float]
    #: Sample size behind each point, so a confidence band can be drawn. This
    #: is the *window* length at that trial, capped at `windowSize` — not the
    #: cumulative trial count.
    counts: list[int]
    window_size: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "values": [_round(v) for v in self.values],
            "n": self.counts,
            "windowSize": self.window_size,
        }


@dataclass(frozen=True)
class StrategyPoint:
    """One sample of the within-session strategy walk (§4.4)."""

    #: Counted trials resolved across **both** conditions at this sample — the
    #: only shared clock the two metrics have. Not a wall time, and not either
    #: metric's own index.
    trial: int
    x: float
    y: float
    #: The smaller of the two rolling window lengths behind this point.
    n: int

    def to_json(self) -> dict[str, Any]:
        return {"trial": self.trial, "x": _round(self.x), "y": _round(self.y), "n": self.n}


#: The clean-end reason, matching `sessions/runner.py`'s literal exactly.
CLEAN_STOP_REASON = "BF_END_SESSION received"

#: Below this many counted trials a value is flagged rather than trusted. The
#: sidecar never suppresses — it reports the number, the count, the interval
#: and this flag, and presentation decides what to do (§3.5).
DEFAULT_MIN_COUNTED = 10


def codes_of(document: dict[str, Any]) -> list[int]:
    """The strobe codes out of `ts_data`, skipping malformed rows.

    `ts_data` is `[[code, timestamp], …]` (`data-saving.md` §5), but a
    hand-edited or recovery-produced file can hold anything, and an
    `IndexError` escaping from a worker thread would take out an indexing pass
    over an entire cohort.
    """
    raw = document.get("ts_data")
    if not isinstance(raw, list):
        return []
    codes: list[int] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 1:
            code = pair[0]
            if isinstance(code, int) and not isinstance(code, bool):
                codes.append(code)
    return codes


def _timestamps(document: dict[str, Any]) -> list[int]:
    raw = document.get("ts_data")
    if not isinstance(raw, list):
        return []
    out: list[int] = []
    for pair in raw:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
            ts = pair[1]
            if isinstance(ts, int) and not isinstance(ts, bool):
                out.append(ts)
    return out


# --- trial outcomes (§3.8) --------------------------------------------------
#
# Recognised by **name** out of the profile's `strobes` map, not by hard-coded
# codes: `data-saving.md` §6 makes that map the sketch's own declaration of its
# vocabulary, and a code number means nothing without it. A task that doesn't
# declare these names simply reports no outcomes — which is why every pattern
# below is anchored rather than a loose substring.

#: `^FLUID` and not `STOP_FLUID_G_R`, which also contains the word and marks the
#: *end* of delivery. Anchoring is the whole defence here.
_REWARD = re.compile(r"^FLUID(_|$)", re.IGNORECASE)
#: Correct well, released before the hold cleared.
_HOLD_FAIL = re.compile(r"^WATER_UNPOKE_EARLY(_|$)", re.IGNORECASE)
_WRONG_WELL = re.compile(r"^WATER_POKE_ERROR(_|$)", re.IGNORECASE)
#: The odor was sampled to completion. Exact — `ODOR_UNPOKE_EARLY` is the
#: opposite event and must never match here.
_SAMPLED = re.compile(r"^ODOR_UNPOKE$", re.IGNORECASE)


@dataclass(frozen=True)
class _Vocabulary:
    """The outcome codes a profile actually declares."""

    reward: frozenset[int]
    hold_fail: frozenset[int]
    wrong_well: frozenset[int]
    sampled: frozenset[int]

    @property
    def usable(self) -> bool:
        """Both halves are needed: a reward marker with no completed-sampling
        marker gives a numerator with no honest denominator."""
        return bool(self.reward) and bool(self.sampled)


def _vocabulary(profile: TaskProfile) -> _Vocabulary:
    def matching(pattern: re.Pattern[str]) -> frozenset[int]:
        return frozenset(
            code for code, name in profile.strobes.items() if pattern.match(name.strip())
        )

    return _Vocabulary(
        reward=matching(_REWARD),
        hold_fail=matching(_HOLD_FAIL),
        wrong_well=matching(_WRONG_WELL),
        sampled=matching(_SAMPLED),
    )


def _classify_trials(
    codes: list[int], boundaries: frozenset[int], vocab: _Vocabulary
) -> Iterator[tuple[int, str]]:
    """`(opening code, classification)` per trial, delimited as the metrics are.

    Uses `boundaries_for`'s union rather than a single trigger for the same
    reason the metrics do: a trial abandoned when the next odor fires must
    close there, or its outcome is stolen by whichever trial answers next.

    The opening code rides along so a caller can split the tally per condition
    (§3.9) without a second, separately-drifting pass over the stream.
    """
    open_trial = False
    trigger = 0
    sampled = False
    outcome: str | None = None

    def settle() -> str:
        if outcome is not None:
            return outcome
        # A trial the animal engaged with but never answered is a real
        # behavioural category; one it never engaged with is not the same thing.
        return "no_response" if sampled else "aborted"

    for code in codes:
        if code in boundaries:
            if open_trial:
                yield trigger, settle()
            open_trial, trigger, sampled, outcome = True, code, False, None
            continue
        if not open_trial:
            continue
        if code in vocab.sampled:
            sampled = True
        elif outcome is None:
            if code in vocab.reward:
                outcome = "rewarded"
            elif code in vocab.hold_fail:
                outcome = "hold_failed"
            elif code in vocab.wrong_well:
                outcome = "wrong_well"

    if open_trial:
        yield trigger, settle()


def _tally(classifications: Iterable[str]) -> TrialOutcomes:
    counts = Counter(classifications)
    rewarded = counts["rewarded"]
    hold_failed = counts["hold_failed"]
    wrong_well = counts["wrong_well"]
    no_response = counts["no_response"]
    aborted = counts["aborted"]
    return TrialOutcomes(
        trials=sum(counts.values()),
        # Everything that reached a well was necessarily administered, whether
        # or not the sampling marker was seen — deriving it from the resolved
        # outcomes keeps the denominator consistent with its own numerators.
        administered=rewarded + hold_failed + wrong_well + no_response,
        rewarded=rewarded,
        hold_failed=hold_failed,
        wrong_well=wrong_well,
        no_response=no_response,
        aborted=aborted,
    )


def outcomes_of(codes: list[int], profile: TaskProfile | None) -> TrialOutcomes | None:
    """Tally trial outcomes, or `None` when the profile can't express them."""
    classified = _classified_trials(codes, profile)
    if classified is None:
        return None
    return _tally(outcome for _, outcome in classified)


def conditions_of(
    codes: list[int], profile: TaskProfile | None
) -> list[ConditionOutcomes]:
    """The same tally, split per declared condition (§3.9).

    Empty whenever `outcomes_of` is None, and in the same authored order as
    `liveMetrics` — the order the strategy space already treats as load-bearing
    (§4.2), so a reader comparing the two panels is looking at the same axes in
    the same order.
    """
    classified = _classified_trials(codes, profile)
    if classified is None or profile is None:
        return []
    by_trigger: dict[int, list[str]] = {}
    for trigger, outcome in classified:
        by_trigger.setdefault(trigger, []).append(outcome)
    return [
        ConditionOutcomes(
            metric_id=metric.id,
            label=metric.label,
            trigger_code=metric.trigger_code,
            outcomes=_tally(by_trigger.get(metric.trigger_code, [])),
        )
        for metric in profile.live_metrics
    ]


def _classified_trials(
    codes: list[int], profile: TaskProfile | None
) -> list[tuple[int, str]] | None:
    """One classification pass, or `None` when the profile can't express one."""
    if profile is None:
        return None
    boundaries = boundaries_for(profile)
    if not boundaries:
        return None
    vocab = _vocabulary(profile)
    if not vocab.usable:
        return None
    return list(_classify_trials(codes, boundaries, vocab))


def summarize(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    min_counted: int = DEFAULT_MIN_COUNTED,
) -> RunSummary:
    """Score one recorded run (§3)."""
    codes = codes_of(document)
    stamps = _timestamps(document)
    stop_reason = document.get("stop_reason")
    stop_reason = stop_reason if isinstance(stop_reason, str) else None

    duration = (stamps[-1] - stamps[0]) if len(stamps) >= 2 else None
    seed = document.get("trial_seed")
    seed = seed if isinstance(seed, int) and not isinstance(seed, bool) else None

    base = {
        "total_events": len(codes),
        "duration_ms": duration,
        "stop_reason": stop_reason,
        "clean": stop_reason == CLEAN_STOP_REASON,
        "seed": seed,
    }

    # A sketch with no Task Profile is fully supported (`data-saving.md` §6.1)
    # and still worth listing — it has a real duration, event count and stop
    # reason. Inventing a default metric for it would be worse than saying so.
    if profile is None or not profile.live_metrics:
        return RunSummary(status="no-metrics", **base)

    boundaries = boundaries_for(profile)
    metrics = [
        _summarize_metric(metric, codes, boundaries, min_counted)
        for metric in profile.live_metrics
    ]
    return RunSummary(
        status="ok",
        metrics=metrics,
        overall=_overall(metrics, min_counted),
        outcomes=outcomes_of(codes, profile),
        conditions=conditions_of(codes, profile),
        excluded_by_default=profile.kind == "utility",
        **base,
    )


#: The id reserved for the pooled figure, so the frontend can offer it in the
#: same selector as the real metrics without colliding with one.
OVERALL_ID = "__overall__"


def _overall(metrics: list[MetricSummary], min_counted: int) -> MetricSummary | None:
    """Accuracy pooled across every metric — correct trials over scored trials.

    Why this exists, and why it is the heatmap's default: **a single metric
    cannot show a side bias.** An animal that pokes right on every trial scores
    ~1.0 on "P(R | Odor 1)" and ~0.0 on "P(L | Odor 3)", so a heatmap keyed on
    the first metric alone paints a completely bias-locked animal as one of the
    best in the cohort. Pooling puts it at chance, which is the truth.

    Pooled by summing hits and trials rather than averaging the two
    proportions, so a session that scored 90 odor-1 trials and 10 odor-3 trials
    is weighted the way it actually happened.
    """
    scored = [m for m in metrics if m.p_session is not None and m.counted > 0]
    if not scored:
        return None
    counted = sum(m.counted for m in scored)
    hits = sum(round(m.p_session * m.counted) for m in scored)  # type: ignore[operator]
    interval = wilson_interval(hits, counted)
    return MetricSummary(
        id=OVERALL_ID,
        label="Overall accuracy",
        p_session=hits / counted,
        p_window=None,
        counted=counted,
        triggered=sum(m.triggered for m in scored),
        excluded=sum(m.excluded for m in scored),
        window_size=0,
        wilson_low=interval[0] if interval else None,
        wilson_high=interval[1] if interval else None,
        low_confidence=counted < min_counted,
    )


def _summarize_metric(
    metric: LiveMetric,
    codes: list[int],
    boundaries: frozenset[int],
    min_counted: int,
) -> MetricSummary:
    rolling = compute_series(metric, codes, boundaries)

    # Whole-session P: the same accumulator with its window widened past the
    # session length, so trial classification is byte-for-byte the live rules
    # and only the averaging window differs. `deque(maxlen=…)` does not
    # preallocate, so a large maxlen costs nothing.
    unwindowed = replace(metric, window_size=max(1, len(codes) or 1))
    whole = compute_series(unwindowed, codes, boundaries)

    counted = len(rolling)
    triggered = codes.count(metric.trigger_code)
    p_session = whole[-1] if whole else None
    p_window = rolling[-1] if rolling else None

    interval = (
        wilson_interval(round(p_session * counted), counted)
        if p_session is not None and counted > 0
        else None
    )

    return MetricSummary(
        id=metric.id,
        label=metric.label,
        p_session=p_session,
        p_window=p_window,
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
    )


def series(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    mode: str = "rolling",
    metric_ids: Iterable[str] | None = None,
) -> list[MetricSeries]:
    """The within-session trajectory, one entry per counted trial (§5).

    `mode="cumulative"` widens the window to the whole session, so the curve
    is the running whole-session average rather than the rolling one.
    """
    if profile is None or not profile.live_metrics:
        return []
    wanted = set(metric_ids) if metric_ids is not None else None
    codes = codes_of(document)
    boundaries = boundaries_for(profile)

    out: list[MetricSeries] = []
    for metric in profile.live_metrics:
        if wanted is not None and metric.id not in wanted:
            continue
        effective = (
            replace(metric, window_size=max(1, len(codes) or 1))
            if mode == "cumulative"
            else metric
        )
        values = compute_series(effective, codes, boundaries)
        out.append(
            MetricSeries(
                id=metric.id,
                label=metric.label,
                values=values,
                counts=_window_lengths(len(values), effective.window_size),
                window_size=effective.window_size,
            )
        )
    return out


def strategy_trail(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    min_window: int = DEFAULT_MIN_COUNTED,
) -> list[StrategyPoint]:
    """The within-session walk through the strategy space (§4.4).

    The cross-session strategy space (§4) plots one point per session, so a
    session is an endpoint there and its shape is invisible: an animal that
    spent the first eighty trials answering one port and then started
    discriminating lands in exactly the same place as one that was steady
    throughout. This is that same plane, walked at trial resolution.

    Why it cannot be assembled on the frontend from `series`: those are indexed
    by each metric's **own** counted trials, and the conditions interleave, so
    index *k* of one is not the same moment as index *k* of the other. Pairing
    them requires replaying the stream with both accumulators fed together —
    which is what happens here, using the live `MetricAccumulator` so the walk
    agrees with what Mission Control displayed rather than approximating it.

    Sampled after every counted trial in either condition, at each metric's own
    authored `windowSize`: the point is "what strategy is this animal running
    *right now*", which is the rolling figure, never the whole-session one.

    **The walk starts once both windows hold `min_window` trials**, not at the
    first scored trial. A rolling proportion over one trial is exactly 0.0 or
    1.0, so an unfiltered walk begins pinned to a corner of the plane and
    thrashes between the edges for its first few trials — an artefact of the
    estimator that reads as a behaviour, which is the worst kind of wrong here.
    `DEFAULT_MIN_COUNTED` is reused rather than a fresh constant invented: it is
    already the app's answer to "too few trials to read firmly" (§3.5). A window
    authored shorter than that caps the requirement at its own size, so a
    small-window profile still gets a walk instead of silently getting none.
    """
    if profile is None or len(profile.live_metrics) != 2:
        return []
    codes = codes_of(document)
    boundaries = boundaries_for(profile)
    x_metric, y_metric = profile.live_metrics
    x_acc = MetricAccumulator(x_metric, boundaries)
    y_acc = MetricAccumulator(y_metric, boundaries)
    x_floor = max(1, min(min_window, x_metric.window_size))
    y_floor = max(1, min(min_window, y_metric.window_size))

    out: list[StrategyPoint] = []
    counted = 0
    for code in codes:
        x_acc.offer(code)
        y_acc.offer(code)
        total = x_acc.counted_total + y_acc.counted_total
        if total == counted:
            continue
        counted = total
        x_value, y_value = x_acc.value(), y_acc.value()
        # Until both conditions carry enough trials to mean anything there is no
        # position in the plane. A run that only ever triggered one odor has a
        # coordinate and a blank, which is not a point either.
        if x_value.value is None or y_value.value is None:
            continue
        if x_value.n < x_floor or y_value.n < y_floor:
            continue
        out.append(
            StrategyPoint(
                trial=counted,
                x=x_value.value,
                y=y_value.value,
                # The weaker of the two windows: a point is only as trustworthy
                # as the condition supporting it least.
                n=min(x_value.n, y_value.n),
            )
        )
    return out


def _window_lengths(counted: int, window_size: int) -> list[int]:
    """Sample size behind each point: `1, 2, 3, …` until the window fills.

    The accumulator's window is a `deque(maxlen=windowSize)` fed one counted
    trial at a time, so after k counted trials it holds `min(k, windowSize)`.
    That — not the cumulative count — is the n a confidence band must use.
    """
    return [min(index + 1, window_size) for index in range(counted)]


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


def _round(value: float | None) -> float | None:
    """Six decimals on the wire — smaller frames, and no `0.8500000000000001`."""
    return None if value is None else round(value, 6)
