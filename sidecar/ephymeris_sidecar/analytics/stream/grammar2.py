"""A stream-grammar-2 run as a trial table (`ANALYTICS.md#stream-grammar-2`).

A board flashed with stream grammar 2 (`TASKS.md#stream-grammar`) frames every
trial the same way whatever happened in it: a header (`TRIAL_START`, the
side the row rewards, the row's `TRIAL_TYPE_<n>` code), the timeline
`runTrial()` strobes, exactly one outcome code, `INVALID_TRIAL` when the same
trial comes back, and `END_TRIAL`. So a trial is decoded by splitting on the
header and reading, never by matching a pattern against the names: `table_of`
reads such a run into the rows a legacy run has (`legacy/decode.py`), and
`rows_of` into the per-trial table its `.json` and `.mat` carry
(`DATA.md#the-derived-trial-table`).

Which grammar a run speaks is `grammar_of`: the `stream` the board announced
before `READY` when the file records one; otherwise the codes themselves, a
stream closed by grammar 1's terminators being grammar 1 and one carrying both
the header and the footer being grammar 2.

Names come out of the profile's `strobes` map, never from numbers
(`TASKS.md#strobes`); the decoder reads the vocabulary's own names and a
profile whose map lacks them decodes nothing here.

What differs from a legacy row (`ANALYTICS.md#how-a-legacy-run-becomes-a-trial-table`):
`outcome` is the trial's one outcome code, in the spine's classes; `correct` is
read from it (a hold failure is wrong, an abort is excluded), while `scores`
still carries the profile's metric verdicts, as Mission Control showed them;
`latencyMs` is the reaction time, `ODOR_UNPOKE` to the first well poke;
`correction` says whether the trial re-presented an error; a lazy trial and an
early release are rows of their own, with their abort class.

**Pure**, like the rest of `stream/`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import Any

from ...rig.registry import Vocabulary
from ...tasks.profile import LiveMetric, TaskProfile
from .document import _pairs_of, codes_of
from .engagement import TrialEngagement
from .legacy import infer
from .legacy import strobes as legacy_strobes
from .legacy.decode import GAP_COUNTS, GAP_PHASES, Condition, conditions_of
from .legacy.trials import MetricAccumulator, boundaries_for
from .outcomes import ConditionOutcomes, TrialOutcomes, TrialRecord
from .trial_table import ConditionScore, ReplayTrial, correct_of

#: The grammars a board can announce (`STREAM=<n>`), and what a file records as `stream`.
GRAMMAR_1 = 1
GRAMMAR_2 = 2
STREAM_KEY = "stream"

# The vocabulary's names for the grammar (`TASKS.md#stream-grammar`).
HEADER = "TRIAL_START"
SIDES = {"TRIAL_GO_LEFT": "left", "TRIAL_GO_RIGHT": "right", "TRIAL_NO_GO": "withhold"}
END = "END_TRIAL"
REPEAT = "INVALID_TRIAL"
TERMINATORS_1 = ("END_CORRECT_ITI", "END_INCORRECT_ITI")
_TYPE = re.compile(r"^TRIAL_TYPE_(\d+)$")
_ONSET = re.compile(r"^ODOR_(\d+)_ON$")
LIGHTS_ON, ODOR_POKE, ODOR_OFF, ODOR_UNPOKE, LIGHTS_OFF = (
    "LIGHTS_ON", "ODOR_POKE", "ODOR_OFF", "ODOR_UNPOKE", "LIGHTS_OFF")
POKES = {"WATER_POKE_L": "left", "WATER_POKE_R": "right"}
FLUIDS = {"FLUID_L": "STOP_FLUID_G_L", "FLUID_R": "STOP_FLUID_G_R"}

#: Each outcome code's class (`taskdef/lowering.py`'s `OUTCOME_CLASSES`). A
#: `WATER_POKE_ERROR_*` inside a no-go trial is a false alarm, not a wrong well.
OUTCOME_CLASS = {
    "CORRECT": "correct",
    "WATER_POKE_ERROR_L": "wrong_response",
    "WATER_POKE_ERROR_R": "wrong_response",
    "WATER_UNPOKE_EARLY_L": "hold_broken",
    "WATER_UNPOKE_EARLY_R": "hold_broken",
    "RESP_OMIT": "omission",
    "WATER_POKE_NONE": "withheld",
    "LAZY_RAT": "abort_before_stimulus",
    "ODOR_UNPOKE_EARLY": "abort_before_stimulus",
    "ODOR_UNPOKE_EARLY_SAMPLING": "abort_during_sampling",
}
#: The legacy bucket of each class (`outcomes.TrialOutcomes`), as the spine's
#: crossover files them; an abort before the stimulus is on the engagement
#: ladder and in no tally, as a lazy trial never was.
_BUCKET = {"correct": "rewarded", "hold_broken": "hold_failed", "wrong_response": "wrong_well",
           "omission": "no_response", "withheld": "withheld", "false_alarm": "false_alarm",
           "abort_during_sampling": "aborted"}


@dataclass(frozen=True)
class TrialRow:
    """One trial of the per-trial table a grammar-2 run's files carry
    (`DATA.md#the-derived-trial-table`): what the header, the timeline and the
    outcome said, column by column. Every value is plain, and every time is ms
    from the run's earliest strobe."""

    index: int
    #: The row's 1-based slot in the trial table, from its `TRIAL_TYPE_<n>` code.
    type_slot: int | None
    #: The odor line the trial presented, from its `ODOR_<n>_ON` code; None when
    #: no odor was delivered.
    odor_line: int | None
    #: What the header said the row rewards: `left`, `right` or `no_go`.
    side: str | None
    #: Odor was delivered: the trial carries an onset code.
    sampled: bool
    #: The outcome code's vocabulary name (`LAZY_RAT`, `CORRECT`, ...).
    outcome: str | None
    #: Its class (`correct`, `wrong_response`, ..., `abort_before_stimulus`).
    outcome_class: str | None
    #: Right, wrong, or None for a trial no accuracy counts (an abort).
    correct: bool | None
    #: The well first poked, `left` or `right`; None when none was.
    response: str | None
    #: `ODOR_UNPOKE` to the first well poke.
    reaction_ms: int | None
    #: The next trial re-presents this one (`INVALID_TRIAL` in the footer).
    repeat: bool
    start_ms: int | None
    light_on_ms: int | None
    odor_poke_ms: int | None
    odor_on_ms: int | None
    odor_off_ms: int | None
    odor_unpoke_ms: int | None
    response_ms: int | None
    outcome_ms: int | None
    end_ms: int | None


@dataclass(frozen=True)
class Grammar2Table:
    """A grammar-2 run's trial table: the rows a legacy table has, read off the
    grammar rather than off patterns, with the per-trial rows beside them."""

    trials: tuple[ReplayTrial, ...]
    conditions: tuple[Condition, ...]
    rows: tuple[TrialRow, ...]
    #: Strobes in the file, for the cumulative curve's window.
    events: int
    #: Every metric verdict in the order the strobes gave them: (strobe index,
    #: row index, condition id), as `LegacyTable.settled`.
    settled: tuple[tuple[int, int, str], ...] = ()
    #: The grammar can always say these; kept as attributes so every reader of
    #: a legacy table reads this one.
    outcomes: bool = True
    engagement: bool = True

    @property
    def gaps(self) -> tuple[str, ...]:
        return (GAP_PHASES, GAP_COUNTS)

    def to_json(self) -> dict[str, Any]:
        return {"kind": "grammar2", "phases": [], "gaps": list(self.gaps),
                "trials": [t.to_json() for t in self.trials]}


def _names(profile: TaskProfile | None) -> dict[str, int]:
    """name → code, upper-cased, out of the profile's strobes map."""
    if profile is None:
        return {}
    return {name.strip().upper(): code for code, name in profile.strobes.items()}


def grammar_of(document: dict[str, Any], profile: TaskProfile | None) -> int:
    """Which stream grammar a run speaks.

    The board's own word first: a file that records `stream` was written from
    a board that announced it. Without one, the codes decide: a stream closed
    by grammar 1's terminators is grammar 1, whatever else it carries, and one
    with the grammar-2 header AND footer is grammar 2. Anything else is
    grammar 1, which every recorded run before the header existed is; so is a
    phase-spine stream with no snapshot, which opens its trials with the same
    `TRIAL_START` but never closes one with `END_TRIAL`.
    """
    stream = document.get(STREAM_KEY)
    if isinstance(stream, int) and not isinstance(stream, bool):
        return stream
    names = _names(profile)
    header, footer = names.get(HEADER), names.get(END)
    if header is None or footer is None:
        return GRAMMAR_1
    seen = set(codes_of(document))
    if header not in seen or footer not in seen:
        return GRAMMAR_1
    if any(names.get(t) in seen for t in TERMINATORS_1):
        return GRAMMAR_1
    return GRAMMAR_2


def is_grammar2_run(document: dict[str, Any], profile: TaskProfile | None) -> bool:
    return grammar_of(document, profile) == GRAMMAR_2


def scores_grammar_2(profile: TaskProfile) -> bool:
    """The profile's metrics read grammar 2: one scores `CORRECT` as its hit."""
    correct = _names(profile).get("CORRECT")
    return correct is not None and any(m.success_code == correct for m in profile.live_metrics)


def for_grammar_1(profile: TaskProfile, codes: list[int], vocabulary: Vocabulary) -> TaskProfile:
    """`profile` as a grammar-1 stream can be scored by it
    (`ANALYTICS.md#stream-grammar-2`).

    A generated profile's metrics score the outcome codes, and a stream
    recorded before the grammar carries none: scored as declared, every trial
    would be excluded. So each such condition is re-expressed as the metric
    the archive always had, the first well poked, with its side read from the
    stream's own reward and error evidence the way inference reads it
    (`legacy/infer.py`), and the id, label and window kept. A condition the
    stream never answered keeps its declared metric, which then scores
    nothing, as it should. A no-go condition misses at either well's poke,
    as the grammar-1 generator wrote it. A profile that reads grammar 1
    already comes back as it is.

    Why here and not in the profile: the profile describes the stream its
    sketch emits today, and the archive is decoded by the profile's
    conditions, never by rewriting history into it.
    """
    if not scores_grammar_2(profile):
        return profile
    names = _names(profile)
    correct, withhold = names.get("CORRECT"), names.get("WATER_POKE_NONE")
    inferred = infer.infer_profile(codes, vocabulary=vocabulary)
    by_trigger = {m.trigger_code: m for m in inferred.live_metrics} if inferred else {}
    pokes = infer.no_go_alternates(vocabulary)
    metrics: list[LiveMetric] = []
    for metric in profile.live_metrics:
        twin = by_trigger.get(metric.trigger_code)
        if metric.success_code == correct and twin is not None and twin.success_code != withhold:
            metric = replace(metric, success_code=twin.success_code, alternate_codes=twin.alternate_codes)
        elif metric.success_code == withhold and pokes:
            metric = replace(metric, alternate_codes=pokes)
        metrics.append(metric)
    return replace(profile, live_metrics=metrics)


@dataclass(frozen=True)
class _Span:
    """One trial's strobes, from its header to the next."""

    start: int
    end: int
    #: (vocabulary name, strobe index, ms) per strobe, names upper-cased; a
    #: code the profile cannot name is `None`.
    strobes: tuple[tuple[str | None, int, int | None], ...]

    def first(self, *names: str) -> tuple[str, int, int | None] | None:
        for name, index, ms in self.strobes:
            if name in names:
                return name, index, ms
        return None

    def first_matching(self, pattern: re.Pattern[str]) -> tuple[str, int, int | None] | None:
        for name, index, ms in self.strobes:
            if name is not None and pattern.match(name):
                return name, index, ms
        return None

    def has(self, name: str) -> bool:
        return any(n == name for n, _, _ in self.strobes)


def _spans(pairs: list[tuple[int, int | None]], names: dict[str, int], base: int | None) -> list[_Span]:
    header = names.get(HEADER)
    by_code = {code: name for name, code in names.items()}
    starts = [i for i, (code, _) in enumerate(pairs) if code == header]
    out: list[_Span] = []
    for k, start in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(pairs)
        strobes = tuple(
            (by_code.get(code), i, ts - base if ts is not None and base is not None else None)
            for i, (code, ts) in enumerate(pairs[start:end], start)
        )
        out.append(_Span(start, end, strobes))
    return out


def _side_of(span: _Span) -> str | None:
    """What the header said, `left`, `right` or `withhold`: the code right after it."""
    if len(span.strobes) < 2:
        return None
    return SIDES.get(span.strobes[1][0] or "")


def _outcome_of(span: _Span, side: str | None) -> tuple[str, int, int | None, str] | None:
    """The trial's one outcome: (name, strobe index, ms, class)."""
    for name, index, ms in span.strobes:
        klass = OUTCOME_CLASS.get(name or "")
        if klass is None:
            continue
        if klass == "wrong_response" and side == "withhold":
            klass = "false_alarm"
        return name or "", index, ms, klass
    return None


def table_of(document: dict[str, Any], profile: TaskProfile | None) -> Grammar2Table:
    """A grammar-2 run's document as its trial table."""
    pairs = _pairs_of(document)
    names = _names(profile)
    conditions = conditions_of(profile)
    stamps = [ts for _, ts in pairs if ts is not None]
    base = min(stamps) if stamps else None
    if HEADER not in names:
        return Grammar2Table((), conditions, (), len(pairs))
    spans = _spans(pairs, names, base)

    # The verdicts: each accumulator fed every strobe, as live, and a count that
    # moves at strobe i settles the trial whose span holds i (`legacy/decode.py`).
    codes = [code for code, _ in pairs]
    boundaries = boundaries_for(profile)
    accumulators = [(m.id, MetricAccumulator(m, boundaries)) for m in profile.live_metrics] if profile else []
    span_at: list[int | None] = [None] * len(codes)
    for k, span in enumerate(spans):
        for i in range(span.start, span.end):
            span_at[i] = k
    # Every condition a trial opens is scored under it, None until a verdict
    # lands: an excluded trial still counts as triggered (`legacy/decode.py`).
    scores: list[dict[str, bool | None]] = [
        {c.id: None for c in conditions if any(codes[i] == c.trigger for i in range(span.start, span.end))}
        for span in spans
    ]
    settled: list[tuple[int, int, str]] = []
    for i, code in enumerate(codes):
        for mid, acc in accumulators:
            counted, hits = acc.counted_total, acc.hits_total
            acc.offer(code)
            k = span_at[i]
            if acc.counted_total != counted and k is not None:
                scores[k][mid] = acc.hits_total != hits
                settled.append((i, k, mid))

    by_trigger: dict[int, Condition] = {}
    for c in conditions:
        by_trigger.setdefault(c.trigger, c)
    strobes_map = profile.strobes if profile else {}
    by_code = {code: name for name, code in names.items()}

    trials: list[ReplayTrial] = []
    rows: list[TrialRow] = []
    previous_repeats_an_error = False
    for k, span in enumerate(spans):
        side = _side_of(span)
        type_code = span.first_matching(_TYPE)
        onset = span.first_matching(_ONSET)
        outcome = _outcome_of(span, side)
        response = span.first(*POKES)
        light = span.first(LIGHTS_ON)
        poke = span.first(ODOR_POKE)
        odor_off = span.first(ODOR_OFF)
        unpoke = span.first(ODOR_UNPOKE)
        end = span.first(END)
        fluid = span.first(*FLUIDS)
        stop = span.first(FLUIDS[fluid[0]]) if fluid else None
        at = span.strobes[0][2] if span.strobes else None
        klass = outcome[3] if outcome else None
        # The condition: the metric whose trigger the trial carries, the type
        # code or the onset, whichever a profile keys its conditions on.
        condition = next(
            (by_trigger[code] for _, i, _ in span.strobes if (code := codes[i]) in by_trigger), None)
        response_ms = response[2] if response else None
        reaction = (response_ms - unpoke[2] if response_ms is not None and unpoke and unpoke[2] is not None
                    and response_ms >= unpoke[2] else None)
        repeats = span.has(REPEAT)
        trials.append(ReplayTrial(
            index=k,
            at_ms=at,
            row=condition.id if condition else None,
            row_name=condition.label if condition else None,
            response=by_code.get(codes[response[1]]) if response else None,
            response_ms=response_ms,
            latency_ms=reaction,
            outcome=klass,
            outcome_ms=outcome[2] if outcome else None,
            correct=correct_of(klass),
            rewarded=klass == "correct" and fluid is not None,
            reward_line=(strobes_map.get(codes[fluid[1]]) or str(codes[fluid[1]])) if fluid else None,
            reward_ms=(stop[2] - fluid[2] if fluid and stop and fluid[2] is not None and stop[2] is not None
                       and stop[2] >= fluid[2] else None),
            correction=previous_repeats_an_error,
            complete=end is not None,
            presented=light is not None,
            scores=tuple(ConditionScore(c, v) for c, v in scores[k].items()),
        ))
        rows.append(TrialRow(
            index=k,
            type_slot=int(_TYPE.match(type_code[0]).group(1)) if type_code else None,  # type: ignore[union-attr]
            odor_line=int(_ONSET.match(onset[0]).group(1)) if onset else None,  # type: ignore[union-attr]
            side="no_go" if side == "withhold" else side,
            sampled=onset is not None,
            outcome=outcome[0] if outcome else None,
            outcome_class=klass,
            correct=correct_of(klass),
            response=POKES[response[0]] if response else None,
            reaction_ms=reaction,
            repeat=repeats,
            start_ms=at,
            light_on_ms=light[2] if light else None,
            odor_poke_ms=poke[2] if poke else None,
            odor_on_ms=onset[2] if onset else None,
            odor_off_ms=odor_off[2] if odor_off else None,
            odor_unpoke_ms=unpoke[2] if unpoke else None,
            response_ms=response_ms,
            outcome_ms=outcome[2] if outcome else None,
            end_ms=end[2] if end else None,
        ))
        previous_repeats_an_error = repeats and klass in ("wrong_response", "hold_broken", "omission",
                                                          "false_alarm")

    sided = tuple(_with_side(c, trials, spans, profile) for c in conditions)
    return Grammar2Table(tuple(trials), sided, tuple(rows), len(pairs), tuple(settled))


def _with_side(condition: Condition, trials: list[ReplayTrial], spans: list[_Span],
               profile: TaskProfile | None) -> Condition:
    """A condition's answer side from the headers of its trials, by majority;
    the profile's own word (`legacy/strobes.answer_side_of`) when none says."""
    votes = Counter(side for t, span in zip(trials, spans)
                    if t.row == condition.id and (side := _side_of(span)) is not None)
    if votes:
        return replace(condition, answer_side=votes.most_common(1)[0][0])
    return condition


def rows_of(document: dict[str, Any], profile: TaskProfile | None) -> tuple[TrialRow, ...]:
    """The per-trial table of a grammar-2 run, for its files."""
    return table_of(document, profile).rows


def verdicts(table: Grammar2Table, condition: str) -> list[bool]:
    """A condition's counted verdicts, in row order, as `curves.verdicts` reads a legacy table."""
    return [v for t in table.trials if (v := t.verdict(condition)) is not None]


def _buckets(table: Grammar2Table) -> list[tuple[ReplayTrial, str | None]]:
    return [(t, _BUCKET.get(t.outcome or "")) for t in table.trials]


def _tally(buckets: list[str | None]) -> TrialOutcomes:
    counts = Counter(b for b in buckets if b is not None)
    return TrialOutcomes(
        trials=sum(counts.values()),
        # As the legacy tally and the spine's crossover: every answered or
        # unanswered trial; an abort during sampling is not among them.
        administered=sum(n for b, n in counts.items() if b != "aborted"),
        rewarded=counts["rewarded"],
        hold_failed=counts["hold_failed"],
        wrong_well=counts["wrong_well"],
        no_response=counts["no_response"],
        aborted=counts["aborted"],
        withheld=counts["withheld"],
        false_alarm=counts["false_alarm"],
    )


def tally_outcomes(table: Grammar2Table) -> TrialOutcomes:
    """The run's outcome tally, from each trial's one outcome code."""
    return _tally([b for _, b in _buckets(table)])


def tally_conditions(table: Grammar2Table) -> list[ConditionOutcomes]:
    """The same tally per condition, in authored order, with the side the
    headers gave it."""
    buckets = _buckets(table)
    return [
        ConditionOutcomes(metric_id=c.id, label=c.label, trigger_code=c.trigger,
                          outcomes=_tally([b for t, b in buckets if t.row == c.id]),
                          answer_side=c.answer_side if c.answer_side != "withhold" else None)
        for c in table.conditions
    ]


def tape_of(table: Grammar2Table) -> list[TrialRecord]:
    """The per-trial tape (`ANALYTICS.md#per-trial-tape`): the rows the tallies
    sum over, in order, one per trial a condition opened and a tally counts."""
    trigger = {c.id: c.trigger for c in table.conditions}
    out: list[TrialRecord] = []
    for t, bucket in _buckets(table):
        if t.row is None or bucket is None:
            continue
        out.append(TrialRecord(
            index=len(out),
            trigger_code=trigger[t.row],
            outcome=bucket,
            at_ms=t.at_ms,
            latency_ms=t.outcome_ms - t.at_ms
            if t.outcome_ms is not None and t.at_ms is not None and t.outcome_ms >= t.at_ms
            else None,
        ))
    return out


def tally_engagement(table: Grammar2Table) -> TrialEngagement:
    """The ladder, read off the rows: offered (the light came on), poked, and
    given odor, each from the strobe that says so."""
    shown = [r for r in table.rows if r.light_on_ms is not None]
    return TrialEngagement(
        presented=len(shown),
        poked=sum(1 for r in shown if r.odor_poke_ms is not None),
        odor_delivered=sum(1 for r in shown if r.sampled),
    )
