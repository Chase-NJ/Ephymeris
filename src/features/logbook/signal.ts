/**
 * How much there is to sort in a recorded run (`RECORDING.md#unit-like-sites`). Pure.
 *
 * Ephymeris never sorts spikes. What it can say, from what RHX saved, is how
 * many of an animal's electrode sites carried **unit-like** signal: spikes that
 * stand well clear of the site's own noise, arriving often enough to be a
 * neuron rather than the odd large transient, with artifacts already set
 * aside by the sidecar. That count is an estimate of how much a sorter will
 * find, good for deciding which day to sort first and nothing finer.
 *
 * The sidecar sends raw measurements (`RunSignal`); every threshold is here,
 * so changing one re-judges every recorded run with nothing to migrate.
 *
 * A run whose waveforms were never measured (no snapshots, or the after-stop
 * pass has not run) falls back to the live crossing counts: its sites are
 * *active* or *quiet* only, and it is given no grade. Crossings alone cannot
 * tell a neuron from a chewing artifact (`RECORDING.md#active-site-yield`).
 */

import type { RunSignal, SiteSignal } from "./types";

/**
 * A spike counts toward a unit when its amplitude is at least this many noise
 * SDs. RHX's detection threshold sits near 4 SDs, so 4 or 5 counts nearly
 * every crossing; 6 leaves about 1.5 SDs of headroom above it.
 */
export const UNIT_SNR = 6;
/**
 * ...and a site is unit-like when such spikes arrive at least this often.
 * Both were set on the lab's 2.8-hour recording of April 2026 (two animals,
 * 32 sites each): this pair kept the sites whose mean waveform was a spike's
 * and dropped the artifact-heavy ones a lower rate let in. A sparse large
 * unit under this rate is not counted.
 */
export const UNIT_MIN_HZ = 0.5;
/** A site is active at this mean crossing rate, as `features/intan/yield.ts`'s default. */
export const ACTIVE_SITE_HZ = 0.5;
/** Under this share of the run covered by the spike stream, live counts read low. */
export const FULL_COVERAGE = 0.9;
/** A measurement over less than this says nothing. */
export const MIN_SECONDS = 10;

/** Unit-like, in rank order: the three are one scale, never three kinds. */
export type SiteClass = "unit" | "active" | "quiet";

export interface SiteVerdict {
  channel: string;
  cls: SiteClass;
  /** Rate of spikes clearing `UNIT_SNR`; null when waveforms were not measured. */
  unitHz: number | null;
  /** Mean rate of every crossing or saved spike, whichever the run has. */
  rateHz: number | null;
  noiseUv: number | null;
}

/** `sort-first` … `none`, or null for a run judged on crossings alone. */
export type Grade = "sort-first" | "worth-sorting" | "low-yield" | "none";

export interface RunVerdict {
  runId: string;
  sessionId: string;
  animalId: string;
  box: number | null;
  /** What the sites were judged on. */
  basis: "waveforms" | "crossings";
  sites: SiteVerdict[];
  total: number;
  unitLike: number;
  /** Active and not unit-like. */
  active: number;
  quiet: number;
  grade: Grade | null;
  /** The seconds the judgement rests on. */
  seconds: number;
  /** Live counts over a stream with a gap: every site reads quieter than it was. */
  partial: boolean;
}

export const GRADE_LABEL: Record<Grade, string> = {
  "sort-first": "Sort first",
  "worth-sorting": "Worth sorting",
  "low-yield": "Low yield",
  none: "Nothing unit-like",
};

/** Share of an animal's sites that must be unit-like for each grade. First guesses. */
const SORT_FIRST_SHARE = 0.5;
const WORTH_SORTING_SHARE = 0.25;

export function gradeOf(unitLike: number, total: number): Grade {
  if (total === 0 || unitLike === 0) return "none";
  const share = unitLike / total;
  if (share >= SORT_FIRST_SHARE) return "sort-first";
  if (share >= WORTH_SORTING_SHARE) return "worth-sorting";
  return "low-yield";
}

/** Spikes at or above `minSnr`, from the site's amplitude histogram. */
export function spikesAbove(
  counts: readonly number[],
  edges: readonly number[],
  minSnr: number,
): number {
  let total = 0;
  for (let bin = 0; bin < counts.length; bin += 1) {
    // A bin counts only when it lies wholly at or above the bar: a threshold
    // between two edges takes the next edge up, never a share of a bin.
    if ((edges[bin] ?? Number.POSITIVE_INFINITY) >= minSnr) total += counts[bin] ?? 0;
  }
  return total;
}

function judgeSite(site: SiteSignal, run: RunSignal, measured: boolean): SiteVerdict {
  const counted = run.countedSeconds ?? 0;
  const crossingHz = site.crossings !== null && counted > 0 ? site.crossings / counted : null;
  if (!measured || site.snrCounts === null || run.recordedSeconds === null) {
    return {
      channel: site.channel,
      cls: crossingHz !== null && crossingHz >= ACTIVE_SITE_HZ ? "active" : "quiet",
      unitHz: null,
      rateHz: crossingHz,
      noiseUv: site.noiseUv,
    };
  }
  const seconds = run.recordedSeconds;
  const unitHz = spikesAbove(site.snrCounts, run.snrEdges, UNIT_SNR) / seconds;
  // Artifacts are not signal: the saved-spike rate leaves them out.
  const kept = site.spikes === null ? null : site.spikes - (site.artifacts ?? 0);
  const spikeHz = kept === null ? crossingHz : kept / seconds;
  const cls: SiteClass =
    unitHz >= UNIT_MIN_HZ
      ? "unit"
      : spikeHz !== null && spikeHz >= ACTIVE_SITE_HZ
        ? "active"
        : "quiet";
  return { channel: site.channel, cls, unitHz, rateHz: spikeHz, noiseUv: site.noiseUv };
}

/** One run judged; null when it was measured for too short a time to say anything. */
export function judgeRun(run: RunSignal): RunVerdict | null {
  const measured =
    run.recordedSeconds !== null &&
    run.recordedSeconds >= MIN_SECONDS &&
    run.sites.some((site) => site.snrCounts !== null);
  const counted = run.countedSeconds ?? 0;
  if (!measured && counted < MIN_SECONDS) return null;
  const sites = run.sites.map((site) => judgeSite(site, run, measured));
  const unitLike = sites.filter((site) => site.cls === "unit").length;
  const active = sites.filter((site) => site.cls === "active").length;
  const coverage =
    run.runSeconds !== null && run.runSeconds > 0 ? Math.min(1, counted / run.runSeconds) : 0;
  return {
    runId: run.runId,
    sessionId: run.sessionId,
    animalId: run.animalId,
    box: run.box,
    basis: measured ? "waveforms" : "crossings",
    sites,
    total: sites.length,
    unitLike,
    active,
    quiet: sites.length - unitLike - active,
    grade: measured ? gradeOf(unitLike, sites.length) : null,
    seconds: measured ? (run.recordedSeconds ?? 0) : counted,
    partial: !measured && coverage < FULL_COVERAGE,
  };
}

/**
 * Each animal's verdict for a session's runs. An animal restarted mid-session
 * has more than one run: the one measured longest speaks for the day.
 */
export function sessionVerdicts(runs: readonly RunSignal[]): Map<string, RunVerdict> {
  const byAnimal = new Map<string, RunVerdict>();
  for (const run of runs) {
    const verdict = judgeRun(run);
    if (!verdict) continue;
    const held = byAnimal.get(run.animalId);
    if (!held || rank(verdict) > rank(held)) byAnimal.set(run.animalId, verdict);
  }
  return byAnimal;
}

/** Measured waveforms beat crossings; then the longer measurement. */
function rank(verdict: RunVerdict): number {
  return (verdict.basis === "waveforms" ? 1e9 : 0) + verdict.seconds;
}

/**
 * An animal's unit-like counts across its recorded sessions, oldest first:
 * the trend a session's count is read against. Runs judged on crossings alone
 * are left out, since their count is of a different thing.
 */
export function unitTrend(
  runs: readonly RunSignal[],
  animalId: string,
  sessionOrder: ReadonlyMap<string, number>,
): Array<{ sessionId: string; unitLike: number; total: number }> {
  const bySession = new Map<string, RunSignal[]>();
  for (const run of runs) {
    if (run.animalId !== animalId) continue;
    const list = bySession.get(run.sessionId) ?? [];
    list.push(run);
    bySession.set(run.sessionId, list);
  }
  const points: Array<{ sessionId: string; unitLike: number; total: number; at: number }> = [];
  for (const [sessionId, list] of bySession) {
    const verdict = sessionVerdicts(list).get(animalId);
    if (!verdict || verdict.basis !== "waveforms") continue;
    points.push({
      sessionId,
      unitLike: verdict.unitLike,
      total: verdict.total,
      at: sessionOrder.get(sessionId) ?? 0,
    });
  }
  return points.sort((a, b) => a.at - b.at).map(({ at: _at, ...point }) => point);
}

/** A session's sites pooled over its animals: what the contents page prints per day. */
export function sessionTotals(verdicts: Iterable<RunVerdict>): {
  unitLike: number;
  total: number;
  graded: boolean;
} {
  let unitLike = 0;
  let total = 0;
  let graded = false;
  for (const verdict of verdicts) {
    if (verdict.basis !== "waveforms") continue;
    graded = true;
    unitLike += verdict.unitLike;
    total += verdict.total;
  }
  return { unitLike, total, graded };
}
