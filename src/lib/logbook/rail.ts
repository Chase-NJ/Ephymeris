/**
 * The Log's time rail — layout maths, pure (`USER-GUIDE.md#keeping-the-log`).
 *
 * Sessions are spaced by **real calendar days**, newest at the top, so a
 * missed day or a weekend is visible as distance: a gap in training often
 * explains the dip after it, which is the same reason the Analytics session
 * rail sits on a date axis (`DATA.md#session-order`). Long gaps are capped so
 * a summer break doesn't push the rest of the year off screen; past the cap
 * the rail draws a break and says how long it was.
 *
 * Days come from the ISO `date` through `Date.UTC`, never through a local
 * `Date`, so a daylight-saving change can't shift a session onto its
 * neighbour. Order is the sidecar's `ordinal` — never the session number.
 */

import type { SessionListItem } from "../analytics/types";

/** Height of one session row — enough for its label. */
export const ROW_PX = 32;
/** Extra distance per missing calendar day between two sessions. */
export const GAP_PX = 12;
/** Missing days drawn to scale before the rail breaks instead. */
export const GAP_CAP = 6;
/** A break's height, in missing-day units — one more than the cap, so a long
 *  absence never looks shorter than the longest gap drawn to scale. */
const BREAK_SPAN = GAP_CAP + 1;

const DAY_MS = 86_400_000;

/** Whole days since the epoch for an ISO `YYYY-MM-DD`; NaN when unreadable. */
export function dayNumber(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return Number.NaN;
  return Math.round(Date.UTC(y, m - 1, d) / DAY_MS);
}

/** ISO `YYYY-MM-DD` for a day number. */
export function isoOfDay(day: number): string {
  return new Date(day * DAY_MS).toISOString().slice(0, 10);
}

function weekday(day: number): number {
  return new Date(day * DAY_MS).getUTCDay(); // 0 = Sunday
}

export function isWeekend(day: number): boolean {
  const w = weekday(day);
  return w === 0 || w === 6;
}

/** Every `y` is a pixel offset from the rail's top: a session's is the top
 *  of its row, an empty day's and a break's are their centre lines. */
export interface RailSession {
  kind: "session";
  id: string;
  y: number;
  day: number;
  /** First (topmost) session on its day — the one that carries the date label. */
  labelsDay: boolean;
}

export interface RailEmptyDay {
  kind: "empty";
  y: number;
  day: number;
  weekend: boolean;
}

export interface RailBreak {
  kind: "break";
  y: number;
  /** Calendar days skipped, end-exclusive: 14 means two weeks without a session. */
  days: number;
}

export type RailItem = RailSession | RailEmptyDay | RailBreak;

export interface RailLayout {
  items: RailItem[];
  /** Session ids newest first — the order j/k walks. */
  order: string[];
  /** y of each session id. */
  positions: Map<string, number>;
  height: number;
}

/** Newest first, by the sidecar's chronological ordinal. */
export function newestFirst(sessions: readonly SessionListItem[]): SessionListItem[] {
  return [...sessions].sort((a, b) => b.ordinal - a.ordinal);
}

export function layoutRail(sessions: readonly SessionListItem[]): RailLayout {
  const sorted = newestFirst(sessions).filter((s) => !Number.isNaN(dayNumber(s.date)));
  const items: RailItem[] = [];
  const positions = new Map<string, number>();
  let y = 0;
  let previousDay: number | null = null;

  for (const session of sorted) {
    const day = dayNumber(session.date);
    if (previousDay === null) {
      // First row sits at the top.
    } else if (day === previousDay) {
      y += ROW_PX; // same day: stacked
    } else {
      // Older day. `missing` days had no session at all: drawn to scale up
      // to the cap, one tick each, and replaced by a single break past it.
      const missing = Math.max(0, previousDay - day - 1);
      if (missing > GAP_CAP) {
        items.push({ kind: "break", y: y + ROW_PX + (BREAK_SPAN * GAP_PX) / 2, days: missing });
        y += ROW_PX + BREAK_SPAN * GAP_PX;
      } else {
        for (let k = 1; k <= missing; k += 1) {
          const empty = previousDay - k;
          items.push({
            kind: "empty",
            y: y + ROW_PX + (k - 0.5) * GAP_PX,
            day: empty,
            weekend: isWeekend(empty),
          });
        }
        y += ROW_PX + missing * GAP_PX;
      }
    }
    items.push({
      kind: "session",
      id: session.id,
      y,
      day,
      labelsDay: day !== previousDay,
    });
    positions.set(session.id, y);
    previousDay = day;
  }

  return {
    items,
    order: sorted.map((s) => s.id),
    positions,
    height: sorted.length === 0 ? 0 : y + ROW_PX,
  };
}

/** One step along the rail. `+1` is older (down), `-1` newer (up); clamped. */
export function stepFrom(order: readonly string[], current: string | null, delta: number): string | null {
  if (order.length === 0) return null;
  const index = current === null ? -1 : order.indexOf(current);
  if (index === -1) return order[0] ?? null;
  const next = Math.min(order.length - 1, Math.max(0, index + delta));
  return order[next] ?? null;
}

export interface MonthBin {
  /** `YYYY-MM`. */
  key: string;
  label: string;
  year: number;
  /** Sessions per calendar day of the month, index 0 = the 1st. */
  days: number[];
  total: number;
  /** The month's newest session — where a click on it lands. */
  newestId: string | null;
}

/**
 * The month strip: every month from the cohort's first session to its last,
 * **including empty ones**, so a month off reads as a hole in the strip.
 * Oldest first, left to right — a timeline reads that way across.
 */
export function monthBins(sessions: readonly SessionListItem[]): MonthBin[] {
  const dated = sessions.filter((s) => !Number.isNaN(dayNumber(s.date)));
  if (dated.length === 0) return [];
  const months = dated.map((s) => s.date.slice(0, 7)).sort();
  const first = months[0]!;
  const last = months[months.length - 1]!;
  const bins: MonthBin[] = [];
  let [y, m] = first.split("-").map(Number) as [number, number];
  const [ly, lm] = last.split("-").map(Number) as [number, number];
  // A cohort's span is months to a few years; the guard only stops a corrupt
  // date from spinning this forever.
  for (let guard = 0; guard < 600 && (y < ly || (y === ly && m <= lm)); guard += 1) {
    const key = `${y}-${String(m).padStart(2, "0")}`;
    const length = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const inMonth = dated.filter((s) => s.date.startsWith(key));
    const days = Array.from({ length }, () => 0);
    for (const s of inMonth) {
      const d = Number(s.date.slice(8, 10));
      if (d >= 1 && d <= length) days[d - 1]! += 1;
    }
    const newest = newestFirst(inMonth)[0];
    bins.push({
      key,
      label: new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", {
        month: "short",
        timeZone: "UTC",
      }),
      year: y,
      days,
      total: inMonth.length,
      newestId: newest?.id ?? null,
    });
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return bins;
}

/**
 * The newest session in the month before (`-1`) or after (`+1`) the current
 * one's, skipping empty months; the current id when there is none.
 */
export function monthJump(
  sessions: readonly SessionListItem[],
  current: string | null,
  delta: -1 | 1,
): string | null {
  const bins = monthBins(sessions).filter((b) => b.total > 0);
  const here = sessions.find((s) => s.id === current);
  if (!here) return bins[bins.length - 1]?.newestId ?? null;
  const index = bins.findIndex((b) => b.key === here.date.slice(0, 7));
  const target = bins[index + delta];
  return target?.newestId ?? current;
}
