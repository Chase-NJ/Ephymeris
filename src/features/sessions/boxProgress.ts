/**
 * One box's run in counts: how many trials were offered, how many the animal
 * completed, and how many it got right, over the run so far
 * (`ARCHITECTURE.md#live-session-views`).
 *
 * The sidecar counts; this only adds up what it sent and keeps the totals it
 * has seen, in order, so Mission Control can draw the run's shape. A run's
 * totals ride each live metric (`session.telemetry`), one per condition.
 * Nothing here reads a strobe.
 *
 * Pure.
 */

import type { TelemetryMetric } from "@/lib/ws/protocol";

export interface Tally {
  /** Trials offered: every trial that began, the open one included. */
  offered: number;
  /** Trials that ended in a scored response, right or wrong. */
  completed: number;
  /** Completed trials the animal got right. */
  correct: number;
}

/** Enough points to draw any session at a tab's width. */
export const PROGRESS_LIMIT = 600;

/** A run's totals, summed over its conditions; null when it has none. */
export function telemetryTally(metrics: readonly TelemetryMetric[]): Tally | null {
  if (metrics.length === 0) return null;
  const tally = { offered: 0, completed: 0, correct: 0 };
  for (const metric of metrics) {
    tally.offered += metric.triggered;
    tally.completed += metric.counted;
    tally.correct += metric.hits;
  }
  return tally;
}

function same(a: Tally, b: Tally): boolean {
  return a.offered === b.offered && a.completed === b.completed && a.correct === b.correct;
}

/**
 * The series with `next` on the end. Totals that repeat the last add nothing
 * (a run reports on every strobe, most of which end no trial), and the
 * same array comes back so a subscriber does not re-render. Totals that went
 * backwards are a new run's, and start the series over. Past the limit every
 * other point is dropped, the first and the newest kept, so a long session
 * loses resolution evenly and never its beginning.
 */
export function appendProgress(series: readonly Tally[], next: Tally): readonly Tally[] {
  const last = series[series.length - 1];
  if (last && same(last, next)) return series;
  if (last && next.offered < last.offered) return [next];
  const grown = [...series, next];
  if (grown.length <= PROGRESS_LIMIT) return grown;
  return grown.filter((_, index) => index === 0 || index === grown.length - 1 || index % 2 === 1);
}

export interface ProgressLines {
  /** Completed trials against trials offered, both as fractions of the trials offered so far. */
  completed: Array<{ x: number; y: number }>;
  correct: Array<{ x: number; y: number }>;
}

/**
 * The run as a cumulative record: x is trials offered, y is how many of them
 * were completed, and how many were correct. Both axes share one scale (the
 * trials offered so far), so a run where every trial is completed and correct
 * climbs the diagonal, and how far each line falls below it is what was
 * missed. Each line starts at the origin: a series that began mid-run (the
 * page was reloaded) is joined to it by a straight segment, which is the only
 * honest guess at trials nobody watched.
 */
export function progressLines(series: readonly Tally[]): ProgressLines {
  const total = series[series.length - 1]?.offered ?? 0;
  if (total <= 0) return { completed: [], correct: [] };
  const origin = { x: 0, y: 0 };
  return {
    completed: [origin, ...series.map((t) => ({ x: t.offered / total, y: t.completed / total }))],
    correct: [origin, ...series.map((t) => ({ x: t.offered / total, y: t.correct / total }))],
  };
}

export interface OutcomeMix {
  correct: number;
  /** Completed and wrong. */
  wrong: number;
  /** Offered and not completed: no scored response, or the trial still open. */
  unanswered: number;
}

/** How the trials offered so far divide; the three always sum to `offered`. */
export function outcomeMix(tally: Tally): OutcomeMix {
  const completed = Math.min(tally.completed, tally.offered);
  const correct = Math.min(tally.correct, completed);
  return { correct, wrong: completed - correct, unanswered: tally.offered - completed };
}

/** Whole-run P(correct) among completed trials, or null before one. */
export function accuracy(tally: Tally): number | null {
  return tally.completed > 0 ? tally.correct / tally.completed : null;
}

/**
 * Trials completed per minute over the run so far, or null in its first
 * minute's opening seconds, where one early trial would read as a sprint.
 */
export function pacePerMinute(tally: Tally, elapsedSeconds: number | null): number | null {
  if (elapsedSeconds === null || elapsedSeconds < 30) return null;
  return tally.completed / (elapsedSeconds / 60);
}
