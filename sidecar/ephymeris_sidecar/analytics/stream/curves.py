"""A run walked trial by trial — `DATA.md#learning-curves`, `DATA.md#strategy-plane`.

The summary is a session's endpoint; these are its shape. Both replay the
stream through the live accumulator, so a curve agrees with what Mission
Control displayed rather than approximating it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from ...tasks.profile import TaskProfile
from .document import codes_of
from .stats import _round
from .summary import DEFAULT_MIN_COUNTED, answer_side_of
from .trials import MetricAccumulator, boundaries_for, compute_series


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
    """One sample of the within-session strategy walk (`DATA.md#strategy-plane`)."""

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


def series(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    mode: str = "rolling",
    metric_ids: Iterable[str] | None = None,
) -> list[MetricSeries]:
    """The within-session trajectory, one entry per counted trial
    (`DATA.md#learning-curves`).

    `mode="cumulative"` widens the window to the whole session, so the curve
    is the running whole-session average rather than the rolling one. Unlike
    `_summarize_metric`, which only wants the endpoint and reads it off the
    accumulator's totals, this needs the value *after every trial* — so the
    widened window is the mechanism rather than a shortcut. `len(codes)` is a
    safe width for it: a counted trial costs at least two codes (a trigger and
    a response), so the window can never fill and never drops a trial.
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


@dataclass(frozen=True)
class StrategyAxes:
    """How this profile's conditions fold onto the plane's two axes
    (`DATA.md#strategy-plane`).

    The plane's whole meaning is that **an animal answering the same way
    regardless of stimulus sits on `x + y = 1`**, so its two axes have to be
    opposing answers. With two conditions that was automatic — one per side —
    and the code simply took `live_metrics[0]` and `[1]`. A four-odor task broke
    that silently: it has four metrics, so there was no pair to take and both
    strategy panels went blank on exactly the task that most needs reading.

    So the axes are **sides**, not metrics, and any number of conditions folds
    onto them: x is every condition answered at one well, y every condition
    answered at the other. Pooled over integers (see `MetricSummary.hits`), so a
    condition with 200 trials counts for ten of a condition with 20.

    x takes the side of the FIRST declared metric, deliberately: on the
    two-condition tasks this lab has always run that is exactly the orientation
    the plane had before, so no familiar plot silently transposes.
    """

    x_side: str
    y_side: str
    x_metrics: tuple[str, ...]
    y_metrics: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "xSide": self.x_side,
            "ySide": self.y_side,
            "xMetrics": list(self.x_metrics),
            "yMetrics": list(self.y_metrics),
        }


def strategy_axes(profile: TaskProfile | None) -> StrategyAxes | None:
    """Fold a profile's conditions onto two opposing axes, or `None`.

    `None` — no plane — whenever the conditions cannot be split into two
    opposing answers: a one-condition shaping task, a task whose success codes
    resolve to nothing, or one whose conditions all reward the same well. Every
    one of those is a real answer rather than a failure, and the panels say so.
    """
    if profile is None or not profile.live_metrics:
        return None
    sides: dict[str, list[str]] = {}
    order: list[str] = []
    for metric in profile.live_metrics:
        side = answer_side_of(profile, metric)
        # A withhold is not an axis: it is the ABSENCE of an answer, so it has
        # no opposing side to be plotted against.
        if side is None or side == "withhold":
            continue
        if side not in sides:
            sides[side] = []
            order.append(side)
        sides[side].append(metric.id)
    if len(order) != 2:
        return None
    x_side, y_side = order
    return StrategyAxes(
        x_side=x_side,
        y_side=y_side,
        x_metrics=tuple(sides[x_side]),
        y_metrics=tuple(sides[y_side]),
    )


def strategy_trail(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    min_window: int = DEFAULT_MIN_COUNTED,
) -> list[StrategyPoint]:
    """The within-session walk through the strategy space (`DATA.md#strategy-plane`).

    The cross-session strategy space plots one point per session, so a
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

    Sampled after every counted trial in any condition, at each metric's own
    authored `windowSize`: the point is "what strategy is this animal running
    *right now*", which is the rolling figure, never the whole-session one.

    **Any number of conditions, folded onto two axes by `strategy_axes`.** This
    used to demand exactly two metrics, which silently blanked the panel for
    every task presenting more — the four-odor task got no walk at all, on
    precisely the plot that would have told its operator whether the animal was
    discriminating or picking a side.

    **The walk starts once both windows hold `min_window` trials**, not at the
    first scored trial. A rolling proportion over one trial is exactly 0.0 or
    1.0, so an unfiltered walk begins pinned to a corner of the plane and
    thrashes between the edges for its first few trials — an artefact of the
    estimator that reads as a behaviour, which is the worst kind of wrong here.
    `DEFAULT_MIN_COUNTED` is reused rather than a fresh constant invented: it is
    already the app's answer to "too few trials to read firmly"
    (`ANALYTICS.md#uncertainty`). A window
    authored shorter than that caps the requirement at its own size, so a
    small-window profile still gets a walk instead of silently getting none.
    """
    axes = strategy_axes(profile)
    if profile is None or axes is None:
        return []
    codes = codes_of(document)
    boundaries = boundaries_for(profile)
    by_id = {metric.id: metric for metric in profile.live_metrics}

    def side(ids: tuple[str, ...]) -> list[MetricAccumulator]:
        return [MetricAccumulator(by_id[i], boundaries) for i in ids if i in by_id]

    x_accs, y_accs = side(axes.x_metrics), side(axes.y_metrics)
    if not x_accs or not y_accs:
        return []

    def floor(ids: tuple[str, ...]) -> int:
        # The requirement is per SIDE, not per condition: three conditions of
        # five trials each is a readable side, and demanding the floor from each
        # of them would blank a walk that is perfectly well supported.
        windows = [by_id[i].window_size for i in ids if i in by_id]
        return max(1, min(min_window, max(windows) if windows else min_window))

    x_floor, y_floor = floor(axes.x_metrics), floor(axes.y_metrics)

    def pooled(accs: list[MetricAccumulator]) -> tuple[float | None, int]:
        """One side's rolling figure, over integers.

        Summed hits over summed window lengths — never the mean of the
        conditions' proportions, which would let a condition the animal barely
        met drag the side as hard as one it met constantly.
        """
        hits = 0
        n = 0
        for acc in accs:
            value = acc.value()
            if value.value is None:
                continue
            hits += round(value.value * value.n)
            n += value.n
        return (hits / n if n else None), n

    out: list[StrategyPoint] = []
    counted = 0
    for code in codes:
        for acc in (*x_accs, *y_accs):
            acc.offer(code)
        total = sum(acc.counted_total for acc in (*x_accs, *y_accs))
        if total == counted:
            continue
        counted = total
        x_value, x_n = pooled(x_accs)
        y_value, y_n = pooled(y_accs)
        # Until both SIDES carry enough trials to mean anything there is no
        # position in the plane. A run that only ever triggered one side has a
        # coordinate and a blank, which is not a point either.
        if x_value is None or y_value is None:
            continue
        if x_n < x_floor or y_n < y_floor:
            continue
        out.append(
            StrategyPoint(
                trial=counted,
                x=x_value,
                y=y_value,
                # The weaker of the two sides: a point is only as trustworthy as
                # the axis supporting it least.
                n=min(x_n, y_n),
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
