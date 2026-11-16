/**
 * The named-event PSTH view's arithmetic (`RECORDING.md#event-psth`). Pure.
 */

import type { EventPsth, EventPsthSite } from "@/lib/ws/protocol";

/** The windows offered, before and after the event, with a bin that keeps ~40–60 bars. */
export const WINDOWS = [
  { id: "short", label: "−0.1 … +0.3 s", preMs: 100, postMs: 300, binMs: 10 },
  { id: "mid", label: "−0.5 … +1 s", preMs: 500, postMs: 1000, binMs: 25 },
  { id: "long", label: "−1 … +3 s", preMs: 1000, postMs: 3000, binMs: 100 },
] as const;

export type WindowId = (typeof WINDOWS)[number]["id"];

/** Spikes per bin over trials → Hz, per bin. A group with no trials is all zero, never NaN. */
export function binRates(counts: readonly number[], trials: number, binMs: number): number[] {
  if (trials <= 0 || binMs <= 0) return counts.map(() => 0);
  return counts.map((n) => (n * 1000) / (trials * binMs));
}

/** A round axis top at or above `value`: 1, 2 or 5 times a power of ten. */
export function niceMax(value: number): number {
  if (!(value > 0)) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) if (step * magnitude >= value) return step * magnitude;
  return 10 * magnitude;
}

/** The highest rate any group reaches at one site: the shared y axis. */
export function siteMax(site: EventPsthSite, psth: Pick<EventPsth, "groups" | "binMs">): number {
  let top = 0;
  site.counts.forEach((counts, g) => {
    const trials = psth.groups[g]?.trials ?? 0;
    for (const hz of binRates(counts, trials, psth.binMs)) top = Math.max(top, hz);
  });
  return niceMax(top);
}

/** Sites by verdict, responsive first, then by |t|: the order a reader scans in. */
export function rankSites(sites: readonly EventPsthSite[]): EventPsthSite[] {
  const weight = (s: EventPsthSite) => (s.responsive === "none" ? 1 : 0);
  return [...sites].sort(
    (a, b) => weight(a) - weight(b) || Math.abs(b.t ?? 0) - Math.abs(a.t ?? 0) || a.channel.localeCompare(b.channel),
  );
}

/** "60 placed · 0 missed · 0 stray", and whether to worry. */
export function describeSync(sync: EventPsth["sync"]): { text: string; trouble: boolean } {
  return {
    text: `${sync.matched} placed · ${sync.missed} missed · ${sync.stray} stray`,
    trouble: sync.missed > 0 || (sync.matched === 0 && sync.stray > 0),
  };
}
