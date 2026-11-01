/**
 * A spine run's trial table and outcome tallies, ready to draw
 * (`ANALYTICS.md#how-a-spine-run-is-scored`). The sidecar reads every trial
 * off its replay; this only words and colours what it reports, and never
 * decides an outcome.
 */

import type { OutcomeTally, RateEstimate, ReplayTrial, TrialTable, WindowRate } from "@/lib/ws/protocol";

/** An outcome class's colour. A class this build has never seen is still
 *  drawn, in the neutral tone, so a new class needs no change here. */
const CLASS_FILL: Record<string, string> = {
  correct: "var(--color-status-ok)",
  withheld: "var(--color-status-ok)",
  wrong_response: "var(--color-status-error)",
  false_alarm: "var(--color-status-error)",
  hold_broken: "var(--color-status-warning)",
};
const NEUTRAL = "var(--color-halo)";

/** `wrong_response` → "wrong response"; null → "no outcome". */
export function outcomeLabel(outcome: string | null): string {
  return outcome === null ? "no outcome" : outcome.replace(/_/g, " ");
}

export function outcomeFill(outcome: string | null): string {
  return (outcome !== null && CLASS_FILL[outcome]) || NEUTRAL;
}

export interface ClassPart {
  key: string;
  label: string;
  n: number;
  fill: string;
}

/**
 * A scope's trials split by outcome class, unclassified last, empty classes
 * dropped. The parts sum to `trials` by construction: the sidecar's classes
 * and its unclassified count partition them.
 */
export function classParts(classes: OutcomeTally[], unclassified: number): ClassPart[] {
  const parts = classes
    .filter((c) => c.n > 0)
    .map((c) => ({
      key: c.outcomeClass,
      label: outcomeLabel(c.outcomeClass),
      n: c.n,
      fill: outcomeFill(c.outcomeClass),
    }));
  if (unclassified > 0) {
    parts.push({ key: "", label: outcomeLabel(null), n: unclassified, fill: NEUTRAL });
  }
  return parts;
}

/** `m:ss` from ms since the session's first tick. */
export function clockOf(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export interface TrialRowView {
  key: number;
  number: number;
  at: string;
  row: string;
  outcome: string;
  fill: string;
  reward: string;
  response: string;
  /** One cell per phase: ms after the trial's start it entered that phase. */
  phases: string[];
  complete: boolean;
}

/** One table row per trial, every value as the sidecar reported it. */
export function trialRows(table: TrialTable): TrialRowView[] {
  return table.trials.map((t: ReplayTrial) => ({
    key: t.index,
    number: t.index + 1,
    at: t.atMs === null ? "—" : clockOf(t.atMs),
    row: t.rowName ?? t.row ?? "—",
    outcome: outcomeLabel(t.outcome),
    fill: outcomeFill(t.outcome),
    reward: t.rewarded
      ? `${t.rewardLine ?? "paid"}${t.rewardMs !== null ? ` ${t.rewardMs} ms` : ""}`
      : "—",
    response:
      t.response === null
        ? "—"
        : `${t.response}${t.latencyMs !== null ? ` +${t.latencyMs} ms` : ""}`,
    phases: t.phaseEntries.map((at) => (at === null || t.atMs === null ? "—" : `+${at - t.atMs}`)),
    complete: t.complete,
  }));
}

export interface RateRowView {
  key: string;
  row: string;
  /** The phase, numbered from 1, and its kind. */
  window: string;
  channel: string;
  rate: string;
  /** The paired difference against the reference phase, or "baseline" on it. */
  versus: string;
  n: number;
  lowConfidence: boolean;
}

function estimateText(e: RateEstimate, signed: boolean): string {
  if (e.mean === null) return "—";
  const fixed = (v: number) => v.toFixed(1);
  const mean = `${signed && e.mean >= 0 ? "+" : ""}${fixed(e.mean)}/s`;
  return e.low === null || e.high === null ? mean : `${mean} [${fixed(e.low)}, ${fixed(e.high)}]`;
}

/**
 * Each row's phase-window rates (`ANALYTICS.md#phase-window-rates`), worded:
 * the rate with its interval, and its difference against the channel's
 * reference phase with its own. Every number is the sidecar's.
 */
export function rateRows(rates: WindowRate[]): RateRowView[] {
  return rates.map((w) => ({
    key: `${w.rowId}:${w.phase}:${w.channel}`,
    row: w.name,
    window: `${w.phase + 1} ${w.label}`,
    channel: w.channel,
    rate: estimateText(w.rate, false),
    versus:
      w.reference === null || w.versus === null
        ? "baseline"
        : w.versus.mean === null
          ? "—"
          : `${estimateText(w.versus, true)} vs ${w.reference + 1}`,
    n: w.rate.n,
    lowConfidence: w.lowConfidence,
  }));
}
