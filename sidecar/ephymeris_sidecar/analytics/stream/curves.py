"""A run walked trial by trial — `DATA.md#learning-curves`, `DATA.md#strategy-plane`.

The summary is a session's endpoint; these are its shape. Both read the run's
trial table, the same rows the summary is counted from, so a curve agrees with
the summary beside it, and on a legacy run with what Mission Control
displayed, since its verdicts are the live accumulator's.
"""

from __future__ import annotations

from collections import deque
from itertools import groupby
from dataclasses import dataclass
from typing import Any, Iterable

from ...tasks.profile import TaskProfile
from . import legacy
from .document import codes_of
from .spine import SpineDecodeError, is_spine_run, replayed
from .stats import _round
from .summary import DEFAULT_MIN_COUNTED
from .table_metrics import CORRECT, verdicts


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




@dataclass(frozen=True)
class _Curve:
    """One condition's counted trials, in order, and its authored window (None
    for a spine row, which has none)."""

    id: str
    label: str
    window: int | None
    verdicts: list[bool]


def _curves(document: dict[str, Any], profile: TaskProfile | None) -> list[_Curve]:
    """Each condition's verdicts, read off the run's trial table: a spine run's
    rows (complete trials only, as its metrics count them), or a legacy run's
    conditions."""
    if is_spine_run(document):
        try:
            result = replayed(document)
        except SpineDecodeError:
            return []
        if result.divergence is not None:
            return []
        done = [t for t in result.trials if t.complete]
        return [
            _Curve(id=f"replay:{row}:{CORRECT}", label=f"P({CORRECT} | {name or row})", window=None,
                   verdicts=[t.correct for t in done if t.row == row and t.correct is not None])
            for row, name in result.rows
        ]
    if profile is None or not profile.live_metrics:
        return []
    table = legacy.table_of(document, profile)
    return [_Curve(id=c.id, label=c.label, window=c.window, verdicts=verdicts(table, c.id))
            for c in table.conditions]


def series(
    document: dict[str, Any],
    profile: TaskProfile | None,
    *,
    mode: str = "rolling",
    metric_ids: Iterable[str] | None = None,
) -> list[MetricSeries]:
    """The within-session trajectory, one entry per counted trial
    (`DATA.md#learning-curves`), read off the run's trial table.

    `mode="cumulative"` widens the window to the whole session, so the curve
    is the running whole-session average rather than the rolling one.
    `len(codes)` is a safe width for it: a counted trial costs at least two
    codes (a trigger and a response), so the window can never fill and never
    drops a trial. A spine row has no authored window, so its curve is the
    cumulative one in either mode.
    """
    wanted = set(metric_ids) if metric_ids is not None else None
    whole = max(1, len(codes_of(document)) or 1)
    out: list[MetricSeries] = []
    for curve in _curves(document, profile):
        if wanted is not None and curve.id not in wanted:
            continue
        width = curve.window if mode != "cumulative" and curve.window is not None else whole
        values = [
            sum(window) / len(window)
            for k in range(len(curve.verdicts))
            if (window := curve.verdicts[max(0, k + 1 - width): k + 1] if width > 0 else [])
        ]
        out.append(
            MetricSeries(
                id=curve.id,
                label=curve.label,
                values=values,
                counts=_window_lengths(len(values), width),
                window_size=width,
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
    return _axes(legacy.decode.conditions_of(profile))


def _axes(conditions: Iterable[legacy.Condition]) -> StrategyAxes | None:
    sides: dict[str, list[str]] = {}
    order: list[str] = []
    for condition in conditions:
        side = condition.answer_side
        # A withhold is not an axis: it is the ABSENCE of an answer, so it has
        # no opposing side to be plotted against.
        if side is None or side == "withhold":
            continue
        if side not in sides:
            sides[side] = []
            order.append(side)
        sides[side].append(condition.id)
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
    them needs the verdicts in the order the strobes gave them, which the
    legacy table keeps (`LegacyTable.settled`): one point after each strobe
    that counted a trial on either side, as the live accumulators would.

    Sampled at each condition's own authored `windowSize`: the point is "what
    strategy is this animal running *right now*", which is the rolling figure,
    never the whole-session one. **Any number of conditions, folded onto two
    axes by `strategy_axes`.**

    **The walk starts once both windows hold `min_window` trials**, not at the
    first scored trial. A rolling proportion over one trial is exactly 0.0 or
    1.0, so an unfiltered walk begins pinned to a corner of the plane and
    thrashes between the edges for its first few trials — an artefact of the
    estimator that reads as a behaviour, which is the worst kind of wrong here.
    `DEFAULT_MIN_COUNTED` is reused rather than a fresh constant invented: it is
    already the app's answer to "too few trials to read firmly"
    (`ANALYTICS.md#uncertainty`). A window authored shorter than that caps the
    requirement at its own size, so a small-window profile still gets a walk.
    A spine run has no answer sides, so no walk.
    """
    if profile is None or is_spine_run(document):
        return []
    table = legacy.table_of(document, profile)
    axes = _axes(table.conditions)
    if axes is None:
        return []
    by_id = {condition.id: condition for condition in table.conditions}
    x_ids = [i for i in axes.x_metrics if i in by_id]
    y_ids = [i for i in axes.y_metrics if i in by_id]
    if not x_ids or not y_ids:
        return []
    windows = {i: deque(maxlen=by_id[i].window) for i in (*x_ids, *y_ids)}

    def floor(ids: list[str]) -> int:
        # The requirement is per SIDE, not per condition: three conditions of
        # five trials each is a readable side, and demanding the floor from each
        # of them would blank a walk that is perfectly well supported.
        sizes = [by_id[i].window for i in ids]
        return max(1, min(min_window, max(sizes) if sizes else min_window))

    x_floor, y_floor = floor(x_ids), floor(y_ids)

    def pooled(ids: list[str]) -> tuple[float | None, int]:
        """One side's rolling figure, over integers: summed hits over summed
        window lengths, never the mean of the conditions' proportions."""
        hits = sum(sum(windows[i]) for i in ids)
        n = sum(len(windows[i]) for i in ids)
        return (hits / n if n else None), n

    out: list[StrategyPoint] = []
    counted = 0
    for _, step in groupby(table.settled, key=lambda s: s[0]):
        moved = False
        for _, row, condition in step:
            if condition in windows:
                windows[condition].append(bool(table.trials[row].verdict(condition)))
                counted += 1
                moved = True
        if not moved:
            continue
        x_value, x_n = pooled(x_ids)
        y_value, y_n = pooled(y_ids)
        # Until both SIDES carry enough trials to mean anything there is no
        # position in the plane.
        if x_value is None or y_value is None:
            continue
        if x_n < x_floor or y_n < y_floor:
            continue
        # The weaker of the two sides: a point is only as trustworthy as the
        # axis supporting it least.
        out.append(StrategyPoint(trial=counted, x=x_value, y=y_value, n=min(x_n, y_n)))
    return out


def _window_lengths(counted: int, window_size: int) -> list[int]:
    """Sample size behind each point: `1, 2, 3, …` until the window fills.

    The accumulator's window is a `deque(maxlen=windowSize)` fed one counted
    trial at a time, so after k counted trials it holds `min(k, windowSize)`.
    That — not the cumulative count — is the n a confidence band must use.
    """
    return [min(index + 1, window_size) for index in range(counted)]
