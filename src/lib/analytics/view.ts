/**
 * Pure view helpers for Analytics — colour identity, the diverging ramp, the
 * date scale, and the run pivot (`DATA.md#analytics-views`).
 *
 * Kept free of React and of the store so each piece is obvious in isolation:
 * these are the parts where a quiet mistake shows up as a wrong-looking chart
 * rather than an error.
 */

import { sketchName } from "@/lib/sessions/types";

import type {
  AnalyticsSummary,
  ProfileGroup,
  ProfileMetricInfo,
  RunSummary,
  SessionListItem,
} from "./types";

// --- per-animal identity colour (`DATA.md#colour-palette`) ------------------

/**
 * Emitted as `var(--…)` strings for direct SVG `fill`/`stroke` use, exactly
 * like `constellationStyle.ts` does. **Never** as a templated Tailwind class:
 * `fill-series-${n}` is invisible to the static scanner and silently produces
 * no utility at all.
 */
export const SERIES_VARS = [
  "var(--color-series-1)",
  "var(--color-series-2)",
  "var(--color-series-3)",
  "var(--color-series-4)",
  "var(--color-series-5)",
  "var(--color-series-6)",
] as const;

/** Beyond six the ramp repeats — panels with row labels disambiguate. */
export function colorForIndex(index: number): string {
  return SERIES_VARS[index % SERIES_VARS.length]!;
}

/**
 * Stable per animal by roster position, so one animal keeps one colour across
 * its card, its curve and its trail — which is what makes cross-filtering
 * readable without a legend lookup.
 */
export function buildAnimalColors(
  animals: Array<{ id: string }>,
): Map<string, string> {
  return new Map(animals.map((animal, index) => [animal.id, colorForIndex(index)]));
}

// --- the diverging ramp (`DATA.md#colour-palette`) --------------------------

export interface HeatBin {
  /** Exclusive upper bound. */
  max: number;
  fill: string;
  /** Which label colour clears AA on this fill. Precomputed, not derived at
   *  runtime — the bins are a fixed table, so no OKLCH maths is needed. */
  label: "void" | "starlight";
}

export const HEAT_BINS: readonly HeatBin[] = [
  { max: 0.2, fill: "var(--color-heat-1)", label: "void" },
  { max: 0.35, fill: "var(--color-heat-2)", label: "starlight" },
  { max: 0.45, fill: "var(--color-heat-3)", label: "starlight" },
  { max: 0.55, fill: "var(--color-heat-4)", label: "starlight" },
  { max: 0.65, fill: "var(--color-heat-5)", label: "starlight" },
  { max: 0.85, fill: "var(--color-heat-6)", label: "starlight" },
  { max: Infinity, fill: "var(--color-heat-7)", label: "void" },
];

export function binFor(p: number): HeatBin {
  return HEAT_BINS.find((bin) => p < bin.max) ?? HEAT_BINS[HEAT_BINS.length - 1]!;
}

export function labelColor(bin: HeatBin): string {
  return bin.label === "void" ? "var(--color-void)" : "var(--color-starlight)";
}

/*
 * Thin and absent cells are decided where they are drawn: `SessionTable` flags
 * a thin cell against `minCountedTrials`, and `SessionRail` colours a session
 * mark through the `binFor` ramp.
 */

/** The pooled figure the sidecar computes alongside the declared metrics. */
export const OVERALL_ID = "__overall__";

export function pickMetric(run: RunSummary, metricId: string | null) {
  if (metricId === OVERALL_ID) return run.overall;
  if (run.metrics.length === 0) return null;
  // Default to the pooled figure where there is one: a single condition
  // cannot distinguish an animal that learned from one that is simply
  // answering the same port every trial.
  if (metricId === null) return run.overall ?? run.metrics[0]!;
  return run.metrics.find((m) => m.id === metricId) ?? null;
}

// --- the date scale (`DATA.md#session-order`) -------------------------------

/**
 * Whole calendar days between two ISO dates.
 *
 * Parsed field-by-field through `Date.UTC` rather than `new Date(string)`:
 * the latter is timezone-sensitive enough to shift a training gap by a day
 * depending on the machine's offset, which is exactly the thing the date-
 * positioned rail exists to show honestly.
 */
export function daysBetween(from: string, to: string): number {
  const a = parseIsoDate(from);
  const b = parseIsoDate(to);
  if (a === null || b === null) return 0;
  return Math.round((b - a) / 86_400_000);
}

function parseIsoDate(value: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/*
 * Mark placement used to live here as `placeByDate`, returning 0–1 fractions
 * for an SVG whose viewBox was stretched to the rail's width. That stretch
 * distorted every mark, and a fraction of a day cannot promise two same-day
 * marks a legible gap in pixels — so the layout moved into `SessionRail`,
 * where it can reason in the units it actually draws with. `daysBetween`
 * above is the part that was genuinely shared.
 */

// --- task scoping (`DATA.md#pooling-across-tasks`) --------------------------
//
// There is no global task filter. The outcome tallies and the engagement
// ladder are defined by the shared strobe vocabulary, not
// by any task's declared metrics, so the panels built on them show **every
// run** and disclose the task mix instead of hiding part of the archive. The
// declared metrics remain incomparable across tasks — the panels that plot
// them scope *themselves* (`twoMetricGroups`) rather than asking the reader
// to maintain a filter.

/**
 * Short display label per profile hash — the program (sketch folder) name,
 * which is what the session summary's chips already taught the reader.
 *
 * From the runs rather than `ProfileGroup.taskName`: the authored task name
 * ("GRGL 2-Odor Discrimination") is prose, and these labels annotate axes and
 * column headers where a chip-length name is the difference between a label
 * and an overlap. Keyed `hash ?? ""` so unprofiled runs get a label too.
 */
export function taskLabels(summary: AnalyticsSummary): Map<string, string> {
  const byHash = new Map<string, Map<string, number>>();
  for (const run of summary.runs) {
    const hash = run.profileHash ?? "";
    const label = programOf(run);
    const counts = byHash.get(hash) ?? new Map<string, number>();
    counts.set(label, (counts.get(label) ?? 0) + 1);
    byHash.set(hash, counts);
  }
  const out = new Map<string, string>();
  for (const [hash, counts] of byHash) {
    let best = "unknown program";
    let most = -1;
    for (const [label, count] of counts) {
      if (count > most) [best, most] = [label, count];
    }
    out.set(hash, best);
  }
  return out;
}

/**
 * The program a run says it ran — the Program column, the card chip, and
 * every task label above.
 *
 * **The recorded name first, the resolved path second, and the order is the
 * whole point.** `sketchPath` is where *this machine* found a `task.json` to
 * decode with, which is empty for a session recorded on the other rig and
 * copied into the cohort folder: the archive walk adopts the file, the name it
 * records matches no sketch in this install, and the run scores by inference
 * (`DATA.md#which-profile-decodes-a-run`). Reading the path alone displayed
 * every such run as "unknown sketch" — a claim that the record is silent, when
 * the file says exactly what it ran.
 */
export function programOf(run: RunSummary): string {
  return run.sketchName || sketchName(run.sketchPath) || "unknown program";
}

/**
 * How one profile's conditions fold onto the strategy plane's two axes.
 *
 * **Sides, not conditions.** The plane's whole meaning is that an animal
 * answering the same way regardless of stimulus sits on `x + y = 1`, so its
 * axes have to be opposing answers. With two conditions that was automatic —
 * one per well — and the panels simply took `liveMetrics[0]` and `[1]`. A
 * four-odor task has four metrics and no pair to take, so both panels went
 * blank on exactly the task that most needs reading. Folding by side
 * generalizes without changing what a position means.
 *
 * x takes the side of the FIRST declared metric, matching
 * `derive.strategy_axes` so the session walk and the cross-session trail agree
 * — and so a two-condition task keeps precisely the orientation it always had.
 */
export interface StrategyAxis {
  side: string;
  /** What to print on the axis — the side, and how many conditions folded. */
  label: string;
  /** The metric ids pooled onto it. */
  ids: string[];
  /** Those conditions' own labels, for the hover and the note. */
  conditions: string[];
}

export interface StrategyAxes {
  x: StrategyAxis;
  y: StrategyAxis;
}

const SIDE_LABEL: Record<string, string> = {
  left: "left well",
  right: "right well",
  port: "response port",
};

export function strategyAxes(group: ProfileGroup | null): StrategyAxes | null {
  const metrics = declaredMetrics(group);
  const order: string[] = [];
  const bySide = new Map<string, ProfileMetricInfo[]>();
  for (const metric of metrics) {
    const side = metric.answerSide;
    // A withhold is the ABSENCE of an answer: no opposing side, so no axis.
    if (!side || side === "withhold") continue;
    if (!bySide.has(side)) {
      bySide.set(side, []);
      order.push(side);
    }
    bySide.get(side)!.push(metric);
  }
  if (order.length !== 2) return null;
  const axis = (side: string): StrategyAxis => {
    const own = bySide.get(side) ?? [];
    const name = SIDE_LABEL[side] ?? side;
    return {
      side,
      // `×2` rather than "· 2 conditions": this prints in a chart footer beside
      // its twin, where the count is a qualifier and the SIDE is the label.
      label: own.length > 1 ? `${name} ×${own.length}` : name,
      ids: own.map((metric) => metric.id),
      conditions: own.map((metric) => metric.label),
    };
  };
  return { x: axis(order[0]!), y: axis(order[1]!) };
}

/**
 * One run's position on one axis — pooled over integers, never over rates.
 *
 * Summing hits and counted answers "how often was this animal right on either
 * of these conditions". Averaging the two proportions instead would let a
 * condition the animal barely met pull the axis as hard as one it met
 * constantly — the same mistake `_overall` exists to avoid
 * (`DATA.md#pooled-accuracy`).
 */
export function pooledAxis(
  run: RunSummary,
  ids: readonly string[],
): { p: number | null; counted: number } {
  let hits = 0;
  let counted = 0;
  for (const metric of run.metrics) {
    if (!ids.includes(metric.id)) continue;
    hits += metric.hits;
    counted += metric.counted;
  }
  return { p: counted > 0 ? hits / counted : null, counted };
}

/**
 * One run's accuracy at one well, pooled over integers across every condition
 * answered there — read off the run's OWN metrics (`answerSide`), so no profile
 * group is needed and any task lands on the same two axes
 * (`DATA.md#strategy-plane`).
 *
 * Left is left whatever the task: a side is a physical well, which is what
 * makes runs of different tasks comparable on one plane when conditions are
 * not. The same integer pooling as `pooledAxis`, for the same reason.
 */
export function sideAccuracy(
  run: RunSummary,
  side: "left" | "right",
): { p: number | null; counted: number } {
  let hits = 0;
  let counted = 0;
  for (const metric of run.metrics) {
    if (metric.id === OVERALL_ID || metric.answerSide !== side) continue;
    hits += metric.hits;
    counted += metric.counted;
  }
  return { p: counted > 0 ? hits / counted : null, counted };
}

/** The strategy space's fixed axes: x = left well, y = right well. */
export const SIDE_AXES: StrategyAxes = {
  x: { side: "left", label: "left well", ids: [], conditions: [] },
  y: { side: "right", label: "right well", ids: [], conditions: [] },
};

/**
 * The cohort's `limit` most recent sessions that hold at least one scored run,
 * oldest first. `summary.sessions` is already chronological (the sidecar orders
 * it by date and start time — never by session number, which is free text).
 */
export function recentSessions(
  summary: AnalyticsSummary,
  limit: number,
): AnalyticsSummary["sessions"] {
  const scored = new Set(
    summary.runs.filter((run) => run.status === "ok").map((run) => run.sessionId),
  );
  return summary.sessions.filter((session) => scored.has(session.id)).slice(-limit);
}

/**
 * Every task profile the cohort's data actually contains, most-run first, each
 * carrying whether it can put a point on the plane and why not when it cannot.
 *
 * **Drawn from the runs, not from a list of known tasks.** A cohort holds
 * whatever it holds: sessions recorded on this rig, sessions copied from
 * another and decoded from their own embedded snapshot
 * (`DATA.md#the-embedded-task-profile`), and runs whose conditions were
 * inferred from the strobes because no profile resolved at all. All three are
 * real profiles with real runs and all three belong in the picker — what
 * separates them is provenance, which the runs carry, not membership.
 */
export interface StrategyProfile {
  group: ProfileGroup;
  axes: StrategyAxes | null;
  /** Why there is no plane, in words an operator can act on. */
  reason: string | null;
}

export function strategyProfiles(summary: AnalyticsSummary | null): StrategyProfile[] {
  if (!summary) return [];
  return summary.profileGroups
    .filter((group) => group.runCount > 0)
    .sort((a, b) => b.runCount - a.runCount)
    .map((group) => {
      const axes = strategyAxes(group);
      const conditions = declaredMetrics(group);
      return {
        group,
        axes,
        reason: axes
          ? null
          : conditions.length < 2
            ? "one condition — a plane needs two opposing answers"
            : conditions.every((metric) => !metric.answerSide)
              ? "this profile doesn't record which well each condition rewards"
              : "every condition is answered at the same place",
      };
    });
}

/** One session's task composition, dominant first. */
export interface SessionTaskMix {
  /** `profileHash ?? ""` — the `taskLabels` key. */
  hash: string;
  runCount: number;
}

function taskMixOf(runs: RunSummary[]): SessionTaskMix[] {
  const counts = new Map<string, number>();
  for (const run of runs) {
    const hash = run.profileHash ?? "";
    counts.set(hash, (counts.get(hash) ?? 0) + 1);
  }
  return [...counts]
    .map(([hash, runCount]) => ({ hash, runCount }))
    .sort((a, b) => b.runCount - a.runCount);
}

/**
 * Where the cohort's dominant task changes, on the shared session slots.
 *
 * `x` sits at the midpoint between the last session of the old task and the
 * first of the new one — between the columns, where a boundary belongs. The
 * first session is not a change: the strip names it, and a rule before any
 * data would read as data.
 */
export function taskChanges(
  points: SessionOutcomePoint[],
): Array<{ index: number; x: number; hash: string }> {
  const out: Array<{ index: number; x: number; hash: string }> = [];
  let previous: string | null = null;
  points.forEach((point, index) => {
    const dominant = point.tasks[0]?.hash ?? "";
    if (previous !== null && dominant !== previous) {
      const before = sessionSlot(index - 1, points.length);
      const here = sessionSlot(index, points.length);
      out.push({ index, x: (before + here) / 2, hash: dominant });
    }
    previous = dominant;
  });
  return out;
}

/**
 * A profile's real, task-declared metrics — without the pooled figure the
 * sidecar offers alongside them.
 *
 * The strategy space needs exactly two *conditions* to have two axes, and the
 * pooled entry is a summary of those conditions rather than another one. It
 * belongs in the metric selector; it must never be mistaken for an axis.
 */
export function declaredMetrics(group: ProfileGroup | null) {
  return group ? group.metrics.filter((metric) => metric.id !== OVERALL_ID) : [];
}

// --- trial outcomes (`DATA.md#rewarded-and-response-accuracy`) --------------

/**
 * The trial-outcome palette — status colours plus Halo, so nothing new enters
 * the theme for the outcome panels. Shared by the session cards and the
 * outcome-mix trend so the same behaviour is the same colour wherever it
 * appears.
 */
export const OUTCOME_STYLE = {
  rewarded: { fill: "var(--color-status-ok)", label: "rewarded" },
  holdFailed: { fill: "var(--color-status-warning)", label: "correct well, no hold" },
  wrongWell: { fill: "var(--color-status-error)", label: "wrong well" },
  noResponse: { fill: "var(--color-halo)", label: "no response" },
} as const;

export type OutcomeKey = keyof typeof OUTCOME_STYLE;

/** A pooled outcome tally — one session's, one animal's, or a whole cohort's. */
export interface PooledOutcomes {
  /** Every trial boundary seen — administered or not
   *  (`DATA.md#rewarded-and-response-accuracy`). */
  trials: number;
  administered: number;
  rewarded: number;
  holdFailed: number;
  wrongWell: number;
  noResponse: number;
  aborted: number;
  /** rewarded / administered — null when nothing was administered. */
  pRewarded: number | null;
  /** (rewarded + holdFailed) / administered. Always ≥ pRewarded. */
  pSide: number | null;
  /** 95% Wilson bounds on `pRewarded`, for its confidence band. */
  rewardedLow: number | null;
  rewardedHigh: number | null;
  /** The same, on `pSide`. Named for the figure rather than shared, because
   *  the two proportions have different numerators and therefore different
   *  widths — reusing one band under both curves would overstate the tighter
   *  and understate the wider. */
  sideLow: number | null;
  sideHigh: number | null;
}

export const NO_OUTCOMES: PooledOutcomes = {
  trials: 0,
  administered: 0,
  rewarded: 0,
  holdFailed: 0,
  wrongWell: 0,
  noResponse: 0,
  aborted: 0,
  pRewarded: null,
  pSide: null,
  rewardedLow: null,
  rewardedHigh: null,
  sideLow: null,
  sideHigh: null,
};

/** z for a 95% interval — the same constant the sidecar uses. */
const Z_95 = 1.959964;

/**
 * Wilson score interval, mirroring `derive.wilson_interval`.
 *
 * Recomputed here rather than summed from per-run bounds because an interval
 * is not additive: averaging two runs' bounds is not the bound of their pooled
 * proportion, and would understate the width at small n — exactly where this
 * data lives.
 */
export function wilsonInterval(hits: number, n: number): [number, number] | null {
  if (n <= 0) return null;
  const p = hits / n;
  const z2 = Z_95 * Z_95;
  const denominator = 1 + z2 / n;
  const centre = p + z2 / (2 * n);
  const margin = Z_95 * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n));
  return [
    Math.max(0, (centre - margin) / denominator),
    Math.min(1, (centre + margin) / denominator),
  ];
}

/**
 * Pool the outcome tallies of several runs.
 *
 * Pooled by summing trials rather than averaging each run's proportion, for
 * the same reason `_overall` does (`DATA.md#pooled-accuracy`): a session where
 * one animal ran 200 trials and another ran 20 is not two equal votes.
 */
export function poolOutcomes(runs: RunSummary[]): PooledOutcomes {
  const total = { ...NO_OUTCOMES };
  let any = false;
  for (const run of runs) {
    const outcomes = run.outcomes;
    if (!outcomes) continue;
    any = true;
    total.trials += outcomes.trials;
    total.administered += outcomes.administered;
    total.rewarded += outcomes.rewarded;
    total.holdFailed += outcomes.holdFailed;
    total.wrongWell += outcomes.wrongWell;
    total.noResponse += outcomes.noResponse;
    total.aborted += outcomes.aborted;
  }
  if (!any || total.administered === 0) return total;
  const rewarded = wilsonInterval(total.rewarded, total.administered);
  const side = wilsonInterval(total.rewarded + total.holdFailed, total.administered);
  return {
    ...total,
    pRewarded: total.rewarded / total.administered,
    pSide: (total.rewarded + total.holdFailed) / total.administered,
    rewardedLow: rewarded ? rewarded[0] : null,
    rewardedHigh: rewarded ? rewarded[1] : null,
    sideLow: side ? side[0] : null,
    sideHigh: side ? side[1] : null,
  };
}

/**
 * A pooled engagement ladder (`DATA.md#engagement-ladder`) — the layer above
 * `PooledOutcomes`, counting the trials the boxes *offered*.
 *
 * Monotone like the per-run ladder it sums: `presented ≥ poked ≥ odorDelivered`
 * survives summation because each rung is summed independently and each run
 * already satisfies it.
 */
export interface PooledEngagement {
  presented: number;
  poked: number;
  odorDelivered: number;
  /** poked / presented — null when nothing was offered, never 0. */
  pEngaged: number | null;
  engagedLow: number | null;
  engagedHigh: number | null;
  /** False when no run in the pool carried a ladder at all — the task declares
   *  no trial light, which is not the same as a cohort that never engaged. */
  known: boolean;
}

export const NO_ENGAGEMENT: PooledEngagement = {
  presented: 0,
  poked: 0,
  odorDelivered: 0,
  pEngaged: null,
  engagedLow: null,
  engagedHigh: null,
  known: false,
};

/** Pool several runs' engagement ladders — summed trials, not averaged rates,
 *  for the same reason `poolOutcomes` sums (`DATA.md#pooled-accuracy`). */
export function poolEngagement(runs: RunSummary[]): PooledEngagement {
  const total = { ...NO_ENGAGEMENT };
  for (const run of runs) {
    const engagement = run.engagement;
    if (!engagement) continue;
    total.known = true;
    total.presented += engagement.presented;
    total.poked += engagement.poked;
    total.odorDelivered += engagement.odorDelivered;
  }
  if (!total.known || total.presented === 0) return total;
  const band = wilsonInterval(total.poked, total.presented);
  return {
    ...total,
    pEngaged: total.poked / total.presented,
    engagedLow: band ? band[0] : null,
    engagedHigh: band ? band[1] : null,
  };
}

/** One session's pooled tally, on the shared across-session x slots. */
export interface SessionOutcomePoint {
  session: SessionListItem;
  outcomes: PooledOutcomes;
  /** The presentation layer above `outcomes` (`DATA.md#engagement-ladder`) —
   *  how many trials the boxes offered, which is the denominator the outcome
   *  counts are silently conditioned on. `known: false` for a task that
   *  declares no trial light. */
  engagement: PooledEngagement;
  /** The runs pooled into this point, kept for per-animal overlays. */
  runs: RunSummary[];
  /** Which tasks those runs were on, dominant first — the disclosure that
   *  makes pooling across the whole archive honest. */
  tasks: SessionTaskMix[];
}

/**
 * One point per session with at least one run that carries an outcome tally —
 * **every** such session, whatever tasks it ran. The outcome tally is defined
 * by the shared strobe vocabulary (`DATA.md#pooling-across-tasks`), not by any
 * task's metrics, so "fluid delivered / administered" is the same measurement
 * on a shaping day and a discrimination day. What differs is difficulty — which
 * is why each point carries its task mix and the panels draw the task changes,
 * instead of hiding every session that wasn't on one task.
 *
 * Every across-session outcome panel — rewarded accuracy, response accuracy,
 * effort, outcome mix — builds from this one list, so their x slots are
 * identical and a session sits above itself in all of them. The rewarded and
 * response panels depend on that especially: the gap between their curves only
 * means anything if a session is at the same x in both.
 *
 * A session whose runs all report `outcomes: null` contributes nothing: no
 * task in it has a reward vocabulary, which is not a session that earned
 * nothing (`DATA.md#rewarded-and-response-accuracy`). But a session whose
 * administered count is zero *stays* — "ran and aborted everything" is data,
 * and the panels that can't plot it show a gap rather than pretending the
 * session never happened (`DATA.md#edge-cases`).
 */
export function sessionOutcomePoints(summary: AnalyticsSummary): SessionOutcomePoint[] {
  const bySession = new Map<string, RunSummary[]>();
  for (const run of summary.runs) {
    const bucket = bySession.get(run.sessionId);
    if (bucket) bucket.push(run);
    else bySession.set(run.sessionId, [run]);
  }
  // `summary.sessions` is already chronological, so walking it keeps the
  // x-axis in session order without a second sort.
  return summary.sessions.flatMap((session) => {
    const runs = bySession.get(session.id);
    if (!runs || !runs.some((run) => run.outcomes !== null)) return [];
    return [
      {
        session,
        outcomes: poolOutcomes(runs),
        engagement: poolEngagement(runs),
        runs,
        tasks: taskMixOf(runs.filter((run) => run.outcomes !== null)),
      },
    ];
  });
}

/** The task mix spelled out for a hover title — `shaping_GR ×4 · GRGL_2-Odor ×2`. */
export function describeTaskMix(
  tasks: SessionTaskMix[],
  labels: Map<string, string>,
): string {
  return tasks
    .map((task) => `${labels.get(task.hash) ?? "unknown"} ×${task.runCount}`)
    .join(" · ");
}

/** Slot `index` of `total` on the unit x axis; a single session sits centred
 *  rather than pinned to the left edge. */
export function sessionSlot(index: number, total: number): number {
  return total <= 1 ? 0.5 : index / (total - 1);
}

/**
 * Which of a session's two accuracies a panel is plotting.
 *
 * The pair is deliberately symmetric — same x slots, same denominator, same
 * hollow-mark rule — because the whole point of showing both is that the
 * **vertical gap between them is the hold-failure rate**
 * (`DATA.md#rewarded-and-response-accuracy`). A reader can only read that gap
 * if nothing else differs.
 */
export interface AccuracyReading {
  value: (outcomes: PooledOutcomes) => number | null;
  low: (outcomes: PooledOutcomes) => number | null;
  high: (outcomes: PooledOutcomes) => number | null;
}

/** Fluid actually delivered. Conservative: a hold failure counts against it. */
export const REWARDED_ACCURACY: AccuracyReading = {
  value: (o) => o.pRewarded,
  low: (o) => o.rewardedLow,
  high: (o) => o.rewardedHigh,
};

/**
 * The correct well was answered, whether or not the hold earned the drop —
 * the choice rather than the consummatory act. Always ≥ rewarded accuracy,
 * and the figure the declared metrics themselves score
 * (`DATA.md#rewarded-and-response-accuracy`).
 */
export const RESPONSE_ACCURACY: AccuracyReading = {
  value: (o) => o.pSide,
  low: (o) => o.sideLow,
  high: (o) => o.sideHigh,
};

/**
 * The confidence ribbon, split wherever a session has no bounds to offer.
 *
 * A band polygon spanning a gap would assert confidence exactly where there
 * is none, so a run of fewer than two bounded sessions yields no polygon at
 * all rather than a degenerate one.
 */
export function accuracyBand(
  points: SessionOutcomePoint[],
  reading: AccuracyReading,
): Array<Array<{ x: number; low: number; high: number }>> {
  const out: Array<Array<{ x: number; low: number; high: number }>> = [];
  let current: Array<{ x: number; low: number; high: number }> = [];
  points.forEach((point, index) => {
    const low = reading.low(point.outcomes);
    const high = reading.high(point.outcomes);
    if (low === null || high === null) {
      if (current.length >= 2) out.push(current);
      current = [];
      return;
    }
    current.push({ x: sessionSlot(index, points.length), low, high });
  });
  if (current.length >= 2) out.push(current);
  return out;
}

/** One animal's own accuracy at a slot, or nothing where it ran nothing. */
export interface AnimalAccuracyPoint {
  x: number;
  y: number;
  /** Too few administered trials to read firmly — drawn hollow
   * (`DATA.md#uncertainty`). */
  thin: boolean;
}

/**
 * Each animal's own line at the pooled line's x slots, so the two are directly
 * comparable. A slot where the animal administered nothing stays `null`, so
 * its line shows the gap rather than interpolating through a session it sat
 * out (`DATA.md#edge-cases`). Animals that ran nothing at all are dropped
 * entirely.
 */
export function animalAccuracyLines(
  summary: AnalyticsSummary,
  points: SessionOutcomePoint[],
  reading: AccuracyReading,
  thinBelow: number,
): Array<{ animalId: string; points: Array<AnimalAccuracyPoint | null> }> {
  return summary.animals.flatMap((animal) => {
    const line = points.map((point, index) => {
      const own = poolOutcomes(point.runs.filter((run) => run.animalId === animal.id));
      const y = reading.value(own);
      return y === null
        ? null
        : {
            x: sessionSlot(index, points.length),
            y,
            thin: own.administered < thinBelow,
          };
    });
    return line.some((entry) => entry !== null) ? [{ animalId: animal.id, points: line }] : [];
  });
}

/** Chronological order for a trail: session date, then the run's own start. */
export function chronological(
  runs: RunSummary[],
  sessions: SessionListItem[],
): RunSummary[] {
  const order = new Map(sessions.map((session, index) => [session.id, index]));
  return [...runs].sort((a, b) => {
    const bySession = (order.get(a.sessionId) ?? 0) - (order.get(b.sessionId) ?? 0);
    return bySession !== 0 ? bySession : a.startedAt.localeCompare(b.startedAt);
  });
}

/**
 * The `SessionListItem` a Dashboard row's on-disk session folder refers to, or
 * `null` when this machine hasn't indexed it.
 *
 * The Dashboard's recent-session rows come from `analytics.recentSessions`,
 * which walks directory *names* and never opens a file — so a row carries a
 * folder path and no session id. This is where the two meet.
 *
 * Matched on the normalized path first, then on the identity the folder name
 * encodes. Both are needed. The sidecar compares these same two paths through
 * `Path.resolve()` (`analytics/service.py`'s `_normalize`) precisely because
 * the database's stored path and the walked one are not guaranteed to be the
 * same string, and a browser has no `resolve()` to reach for; the identity
 * fallback covers what separator-and-case folding can't.
 */
export function findSessionByFolder(
  sessions: SessionListItem[],
  disk: { folderPath: string; prefixName: string; sessionNumber: string; date: string },
): SessionListItem | null {
  const wanted = normalizeFolder(disk.folderPath);
  const byPath = sessions.find((s) => normalizeFolder(s.folderPath) === wanted);
  if (byPath) return byPath;
  return (
    sessions.find(
      (s) =>
        s.date === disk.date &&
        s.sessionNumber === disk.sessionNumber &&
        s.prefixName === disk.prefixName,
    ) ?? null
  );
}

/** Separator, trailing-slash and case folding — as far as a browser can go. */
function normalizeFolder(path: string): string {
  return path.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}
