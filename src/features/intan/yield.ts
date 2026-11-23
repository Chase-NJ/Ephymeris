/**
 * Active-site yield (`RECORDING.md#active-site-yield`). Pure.
 *
 * RHX's spikes are threshold crossings, not sorted units, so what can be
 * counted honestly is *active sites*: a recorded site whose mean crossing
 * rate over a run is at least `activeSiteHz` (a recording default, 0.5 Hz).
 * The rate is over the seconds RHX's spike stream actually covered, so a gap
 * in the stream does not read as a quiet electrode; a run with poor coverage
 * is marked rather than trusted.
 */

import type { RunYield } from "@/lib/ws/protocol";

export const DEFAULT_ACTIVE_SITE_HZ = 0.5;
/** Below this share of the run covered by the spike stream, a run's yield is marked partial. */
export const FULL_COVERAGE = 0.9;
/** A run counted for less than this says nothing. */
const MIN_COUNTED_S = 10;

export type RunYieldSummary = {
  runId: string;
  startedAt: string | null;
  active: number;
  total: number;
  /** countedSeconds / runSeconds, 0…1. */
  coverage: number;
  partial: boolean;
  /** Spike detection was set up differently from the most recent run, so the counts don't compare. */
  thresholdDiffers: boolean;
};

export function activeSiteCount(
  counts: Readonly<Record<string, number>>,
  seconds: number,
  minHz: number,
): { active: number; total: number } {
  const values = Object.values(counts);
  if (!(seconds > 0)) return { active: 0, total: values.length };
  return { active: values.filter((n) => n / seconds >= minHz).length, total: values.length };
}

/** Each run judged, oldest first; runs counted for too short a time are left out. */
export function summarizeYield(runs: readonly RunYield[], minHz: number): RunYieldSummary[] {
  const latest = runs[runs.length - 1];
  const latestThreshold = latest ? JSON.stringify(latest.threshold ?? null) : "null";
  return runs
    .filter((run) => run.countedSeconds >= MIN_COUNTED_S)
    .map((run) => {
      const { active, total } = activeSiteCount(run.counts, run.countedSeconds, minHz);
      const coverage = run.runSeconds > 0 ? Math.min(1, run.countedSeconds / run.runSeconds) : 0;
      return {
        runId: run.runId,
        startedAt: run.startedAt,
        active,
        total,
        coverage,
        partial: coverage < FULL_COVERAGE,
        thresholdDiffers: JSON.stringify(run.threshold ?? null) !== latestThreshold,
      };
    });
}

/** Heals the stored default: a positive rate up to 100 Hz. */
export function normalizeActiveSiteHz(raw: unknown): number {
  return typeof raw === "number" && Number.isFinite(raw) && raw >= 0.01 && raw <= 100
    ? raw
    : DEFAULT_ACTIVE_SITE_HZ;
}

export type { RunYield };
