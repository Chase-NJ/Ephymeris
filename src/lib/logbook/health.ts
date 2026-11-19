/**
 * Weigh-ins, read (`DATA.md#weigh-ins`). Pure.
 *
 * A weigh-in belongs to an animal and a calendar day, never to a session, so
 * every reading here is made from the animal's whole history and a day: the
 * day's own weight, the weigh-in before it, and the reference weight in force
 * (the latest one marked `baseline` at or before the day).
 *
 * A percentage is only ever of a **marked** reference. The first weigh-in on
 * record is not assumed to be a free-feeding weight: an animal may have been
 * weeks into restriction before anyone typed one in, and a percentage of that
 * would read as healthy when it is not.
 */

import type { HealthEntry } from "./types";

/** What `logbook.setHealth` accepts, so the page can refuse before the sidecar does. */
export const MIN_WEIGHT_G = 1;
export const MAX_WEIGHT_G = 2000;

/**
 * Under this share of the reference weight a weigh-in is marked low. The
 * common floor for restricted rodents; the mark is a prompt to look, not a
 * rule the app enforces.
 */
export const LOW_WEIGHT_FRACTION = 0.85;

export interface WeightReading {
  /** The day's own weigh-in. */
  entry: HealthEntry | null;
  /** The latest weigh-in before the day. */
  previous: HealthEntry | null;
  /** Grams gained since `previous`; negative is a loss. */
  deltaG: number | null;
  /** The reference weight in force on the day (it may be the day's own). */
  reference: HealthEntry | null;
  /** `entry` as a share of `reference`, 0…; null without both. */
  ofReference: number | null;
  /** Under `LOW_WEIGHT_FRACTION` of the reference. */
  low: boolean;
}

/** One animal's history, oldest first. Dates are ISO days, so they order as strings. */
export function byDay(entries: readonly HealthEntry[]): HealthEntry[] {
  return [...entries].sort((a, b) => a.date.localeCompare(b.date));
}

export function readWeight(history: readonly HealthEntry[], date: string): WeightReading {
  let entry: HealthEntry | null = null;
  let previous: HealthEntry | null = null;
  let reference: HealthEntry | null = null;
  for (const item of byDay(history)) {
    if (item.date > date) break;
    if (item.date === date) entry = item;
    else previous = item;
    if (item.baseline) reference = item;
  }
  const ofReference =
    entry && reference && reference.weightG > 0 ? entry.weightG / reference.weightG : null;
  return {
    entry,
    previous,
    deltaG: entry && previous ? entry.weightG - previous.weightG : null,
    reference,
    ofReference,
    low: ofReference !== null && ofReference < LOW_WEIGHT_FRACTION,
  };
}

/** The last `count` weights up to and including `date`, oldest first — a trend's points. */
export function weightTrend(
  history: readonly HealthEntry[],
  date: string,
  count: number,
): HealthEntry[] {
  return byDay(history)
    .filter((item) => item.date <= date)
    .slice(-count);
}

export type ParsedWeight =
  | { kind: "weight"; grams: number }
  /** An emptied field: remove the day's weigh-in. */
  | { kind: "clear" }
  | { kind: "invalid"; reason: string };

/**
 * What an operator typed into a weight cell: `312`, `312.4`, `312,4`, with or
 * without a trailing `g`. Kept to one decimal, a bench scale's resolution.
 */
export function parseWeight(text: string): ParsedWeight {
  const trimmed = text.trim().replace(/\s*g$/i, "").replace(",", ".");
  if (trimmed === "") return { kind: "clear" };
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return { kind: "invalid", reason: "A weight is a number of grams." };
  const grams = Math.round(Number(trimmed) * 10) / 10;
  if (grams < MIN_WEIGHT_G || grams > MAX_WEIGHT_G) {
    return { kind: "invalid", reason: `A weight is between ${MIN_WEIGHT_G} and ${MAX_WEIGHT_G} g.` };
  }
  return { kind: "weight", grams };
}

/** `312.4` — always one decimal, so a column of them aligns on the point. */
export function formatGrams(grams: number): string {
  return grams.toFixed(1);
}

/** `+2.1` / `−3.4` / `0.0`, with a true minus so the sign has the plus's width. */
export function formatDelta(grams: number): string {
  const rounded = Math.round(grams * 10) / 10;
  if (rounded === 0) return "0.0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded).toFixed(1)}`;
}

/** `92%` of the reference weight. */
export function formatShare(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}
