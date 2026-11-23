/**
 * The notebook's pages, in order (`USER-GUIDE.md#keeping-the-log`). Pure.
 *
 * A cohort's Logbook is a bound notebook: one spread (a left and a right
 * page) per session, **oldest first**, so turning forward moves forward in
 * time and the newest session is the last written page. Ahead of them sits
 * the front matter, one spread holding the title page and the contents.
 *
 * Order is the sidecar's chronological `ordinal`, never the session number
 * and never the date as a string (`DATA.md#session-order`).
 */

import type { SessionListItem } from "@/features/analytics/types";

/** The front-matter spread's id: no session has it. */
export const FRONT = "front";

/** Oldest first — the order the pages are bound in. */
export function oldestFirst(sessions: readonly SessionListItem[]): SessionListItem[] {
  return [...sessions].sort((a, b) => a.ordinal - b.ordinal);
}

/** Every spread's id, front matter first. */
export function spreadOrder(sessions: readonly SessionListItem[]): string[] {
  return [FRONT, ...oldestFirst(sessions).map((s) => s.id)];
}

/** `delta` spreads on from `current`, stopping at the covers. Null for an empty book. */
export function turn(order: readonly string[], current: string | null, delta: number): string | null {
  if (order.length === 0) return null;
  const index = current === null ? -1 : order.indexOf(current);
  if (index === -1) return order[order.length - 1] ?? null;
  return order[Math.min(order.length - 1, Math.max(0, index + delta))] ?? null;
}

/** Which way the pages turn to get from one spread to another. */
export function direction(order: readonly string[], from: string, to: string): "forward" | "back" {
  return order.indexOf(to) >= order.indexOf(from) ? "forward" : "back";
}

/**
 * The folios printed on a spread. Front matter is numbered in roman, as a
 * book's is; the first session opens on page 1.
 */
export function folios(order: readonly string[], id: string): { verso: string; recto: string } {
  if (id === FRONT) return { verso: "i", recto: "ii" };
  const index = Math.max(0, order.indexOf(id) - 1);
  return { verso: String(index * 2 + 1), recto: String(index * 2 + 2) };
}

export interface ContentsRow {
  id: string;
  /** `19`. */
  day: string;
  /** `Thu`. */
  weekday: string;
  /** `2O-Bdisc_25`. */
  title: string;
  /** The folio of the session's left page. */
  page: string;
  status: SessionListItem["status"];
  /** Read from files this database never recorded (`DATA.md#orphan-adoption`). */
  recovered: boolean;
}

export interface ContentsMonth {
  /** `YYYY-MM`. */
  key: string;
  /** `November 2026`. */
  label: string;
  /** `Nov`, for the tab on the book's edge. */
  short: string;
  year: number;
  rows: ContentsRow[];
}

function utcDay(isoDate: string): Date | null {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(Date.UTC(y, m - 1, d));
}

/** The contents: every session under its month, in page order. */
export function contents(sessions: readonly SessionListItem[]): ContentsMonth[] {
  const order = spreadOrder(sessions);
  const months: ContentsMonth[] = [];
  for (const session of oldestFirst(sessions)) {
    const when = utcDay(session.date);
    const key = when ? session.date.slice(0, 7) : "undated";
    let month = months[months.length - 1];
    if (!month || month.key !== key) {
      month = {
        key,
        label: when
          ? when.toLocaleDateString("en-GB", { month: "long", year: "numeric", timeZone: "UTC" })
          : "Undated",
        short: when ? when.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }) : "—",
        year: when ? when.getUTCFullYear() : 0,
        rows: [],
      };
      months.push(month);
    }
    month.rows.push({
      id: session.id,
      day: when ? String(when.getUTCDate()) : "—",
      weekday: when
        ? when.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" })
        : "",
      title: `${session.prefixName}_${session.sessionNumber}`,
      page: folios(order, session.id).verso,
      status: session.status,
      recovered: session.id.startsWith("adopted:"),
    });
  }
  return months;
}

/** The month a spread falls in; null for the front matter. */
export function monthOf(months: readonly ContentsMonth[], id: string | null): string | null {
  if (id === null) return null;
  return months.find((month) => month.rows.some((row) => row.id === id))?.key ?? null;
}

/**
 * The first page of the month before (`-1`) or after (`+1`) the current
 * spread's. From the front matter, forward is the first month; stepping past
 * either end stays put.
 */
export function monthTurn(
  months: readonly ContentsMonth[],
  current: string | null,
  delta: -1 | 1,
): string | null {
  if (months.length === 0) return current;
  const here = monthOf(months, current);
  if (here === null) return delta === 1 ? (months[0]?.rows[0]?.id ?? current) : current;
  const index = months.findIndex((month) => month.key === here);
  const target = months[index + delta];
  if (!target) return delta === -1 && index === 0 ? FRONT : current;
  return target.rows[0]?.id ?? current;
}
