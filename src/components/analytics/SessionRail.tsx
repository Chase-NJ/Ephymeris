import { CalendarDays } from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { PanelTitle } from "@/components/charts/PanelTitle";

import { Button } from "@/components/common/controls";
import { useAnalyticsStore } from "@/lib/analytics/context";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import type { AnalyticsSummary, SessionListItem } from "@/lib/analytics/types";
import { springSnappy } from "@/lib/motion";
import { binFor, daysBetween } from "@/lib/analytics/view";

/**
 * The session browser, and a visualization in its own right
 * (`DATA.md#session-order`).
 *
 * Marks are placed by **real calendar date**, not evenly by index, so a
 * five-day break in training renders as five days of empty axis — which is
 * frequently the thing that explains the dip after it. Each mark carries the
 * cohort's mean P for that session, making the rail a sparkline of progress
 * that you also click.
 *
 * **Laid out in pixels, not a stretched viewBox.** The rail scrolls, so its
 * width is data-dependent; a `viewBox` scaled to that width with
 * `preserveAspectRatio="none"` turned every mark into an ellipse that grew
 * wider the longer the archive got. Pixel space also lets the marks be real
 * buttons — focusable, with hit targets larger than the dot they draw.
 *
 * Two things a date axis cannot express on its own, handled here:
 * same-day sessions (a supported workflow — reruns share a date and so share a
 * position) fan out horizontally around their date, and a day is never
 * narrower than the widest such fan, so one date's cluster can't drift into
 * the next and make a real gap look smaller than it is.
 */

/** Dot diameter; the button around it is deliberately larger. */
const MARK = 11;
/** Horizontal step between same-day marks. */
const MARK_GAP = 17;
/** How far a same-day cluster's odd marks lift off the axis. Two rows halve a
 *  cluster's horizontal span, which is what stops one six-rerun day from
 *  widening every quiet day in the rail (`pxPerDay` is global). */
const ROW_LIFT = 13;
/** Floor on a day's width, so a dense week still reads as a week. */
const MIN_PX_PER_DAY = 34;
const MIN_SPAN_WIDTH = 300;
const PAD = 20;
/** Below this spacing, per-mark number labels would collide — drop them. */
const LABEL_MIN_GAP = 24;
/** Same, for the date labels under the axis. */
const DATE_LABEL_MIN_GAP = 52;

const AXIS_Y = 34;

export function SessionRail({
  sessions,
  summary,
  selected,
}: {
  sessions: SessionListItem[];
  summary: AnalyticsSummary | null;
  selected: string;
}) {
  const store = useAnalyticsStore();
  const stats = useMemo(() => sessionStats(summary), [summary]);
  const layout = useMemo(() => layOut(sessions), [sessions]);
  const scroller = useRef<HTMLDivElement | null>(null);
  const [overflow, setOverflow] = useState({ left: false, right: false });

  // Which archive is on the rail — not how many sessions it has. Keyed on the
  // endpoints so a rescan that appends a session re-anchors to the new end,
  // while a mere re-render (hover, selection) never yanks the scroll position.
  const archiveKey = `${sessions[0]?.id ?? ""}:${sessions[sessions.length - 1]?.id ?? ""}`;

  const syncOverflow = () => {
    const el = scroller.current;
    if (!el) return;
    setOverflow({
      left: el.scrollLeft > 2,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2,
    });
  };

  // Open at the recent end: the reader's question is almost always about the
  // latest sessions, and a rail that opens on week one answers last month.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    el.scrollLeft = el.scrollWidth;
    syncOverflow();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [archiveKey]);

  // Keep the selected mark in view — the Dashboard arrival path selects a
  // session this rail has never shown. Manual arithmetic rather than
  // `scrollIntoView`, which would also scroll the page vertically.
  useEffect(() => {
    const el = scroller.current;
    if (!el || selected === ALL_SESSIONS) return;
    const mark = el.querySelector<HTMLElement>(`[data-session-id="${CSS.escape(selected)}"]`);
    if (!mark) return;
    const centre = mark.offsetLeft + mark.offsetWidth / 2;
    const target = centre - el.clientWidth / 2;
    if (Math.abs(el.scrollLeft - target) > el.clientWidth / 4) {
      el.scrollTo({ left: target, behavior: "smooth" });
    }
    syncOverflow();
  }, [selected, archiveKey]);

  if (sessions.length === 0) {
    return (
      <div className="rounded-md px-4 py-3">
        <p className="text-[12px] text-static">
          No sessions recorded for this cohort yet.
        </p>
      </div>
    );
  }

  const { marks, ticks, width, days, showNumbers } = layout;
  const selectedSession = sessions.find((s) => s.id === selected) ?? null;

  return (
    // No surface: the rail floats on the sky, its marks reading as the small
    // constellation they are. The panels below keep their cards; the rail is
    // chrome-free navigation above them.
    <div className="rounded-md px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11px] text-static">
          <CalendarDays size={13} strokeWidth={1.75} className="text-pulsar" />
          <PanelTitle
            name="Sessions"
            note="spaced by date — a gap is a real gap"
          />
        </span>
        <Button
          variant={selected === ALL_SESSIONS ? "primary" : "outline"}
          onClick={() => store.selectSession(ALL_SESSIONS)}
        >
          All sessions
        </Button>
      </div>

      {/* `relative` wrapper so the edge fades can sit over the scroller —
          a scroller with no visible edge reads as a static picture. */}
      <div className="relative">
        <div
          ref={scroller}
          className="scrollbar-slim mt-1 overflow-x-auto pb-1"
          onScroll={syncOverflow}
        >
          <div className="relative h-[62px]" style={{ width }}>
          {/* The axis itself, drawn only across the span the data occupies. */}
            <div
              className="absolute border-t border-static/25"
              style={{ left: PAD, right: PAD, top: AXIS_Y }}
            />

          {ticks.map((tick) => (
            <div key={tick.date}>
              <div
                className="absolute w-px bg-static/30"
                style={{ left: tick.x, top: AXIS_Y, height: 4 }}
              />
              {tick.labelled && (
                <div
                  className="absolute -translate-x-1/2 whitespace-nowrap font-mono text-[9px] tabular-nums text-static/70"
                  style={{ left: tick.x, top: AXIS_Y + 7 }}
                >
                  {shortDate(tick.date)}
                </div>
              )}
            </div>
          ))}

            {marks.map((mark) => {
              const stat = stats.get(mark.session.id) ?? EMPTY_STAT;
              const isSelected = selected === mark.session.id;
              return (
                <SessionMark
                  key={mark.session.id}
                  session={mark.session}
                  x={mark.x}
                  lift={mark.lift}
                  stat={stat}
                  selected={isSelected}
                  // Stacked cluster marks share an x, so their labels would
                  // print through each other — the selected one wins alone.
                  showNumber={(showNumbers && !mark.clustered) || isSelected}
                  onSelect={() => store.selectSession(mark.session.id)}
                />
              );
            })}
          </div>
        </div>
        {overflow.left && <EdgeFade side="left" />}
        {overflow.right && <EdgeFade side="right" />}
      </div>

      {/* One line that names what is selected, so the rail doesn't rely on a
          hover tooltip to answer "which session am I looking at?". */}
      <div className="mt-1.5 border-t border-halo pt-1.5 font-mono text-[10px] tabular-nums text-static/80">
        {selectedSession ? (
          <SelectedLine
            session={selectedSession}
            stat={stats.get(selectedSession.id) ?? EMPTY_STAT}
          />
        ) : (
          <span>
            {sessions.length} {sessions.length === 1 ? "session" : "sessions"}
            {days > 0 ? ` · ${days} days` : ""} · {sessions[0]!.date} →{" "}
            {sessions[sessions.length - 1]!.date}
          </span>
        )}
      </div>
    </div>
  );
}

function SelectedLine({ session, stat }: { session: SessionListItem; stat: Stat }) {
  return (
    <span>
      <span className="text-starlight">
        {session.prefixName}_{session.sessionNumber}
      </span>{" "}
      · {session.date} ·{" "}
      {stat.runs === 0 ? (
        // The distinction the user actually needs: a session that ran nothing
        // is not a session that ran badly.
        <span style={{ color: "var(--color-status-warning)" }}>
          no runs recorded — nothing was strobed
        </span>
      ) : (
        <>
          {stat.runs} run{stat.runs === 1 ? "" : "s"} ·{" "}
          {stat.mean === null ? "no scored runs" : `mean P ${stat.mean.toFixed(2)}`}
        </>
      )}
    </span>
  );
}

/** The scrim that says "there is more this way". Void-tinted rather than a
 *  solid, because `.surface` is translucent over the sky. */
function EdgeFade({ side }: { side: "left" | "right" }) {
  return (
    <span
      aria-hidden
      className={`pointer-events-none absolute inset-y-0 w-7 ${side === "left" ? "left-0" : "right-0"}`}
      style={{
        background: `linear-gradient(to ${side === "left" ? "right" : "left"}, color-mix(in srgb, var(--color-void) 80%, transparent), transparent)`,
      }}
    />
  );
}

function SessionMark({
  session,
  x,
  lift,
  stat,
  selected,
  showNumber,
  onSelect,
}: {
  session: SessionListItem;
  x: number;
  /** True for a cluster's odd marks, drawn a row above the axis. */
  lift: boolean;
  stat: Stat;
  selected: boolean;
  showNumber: boolean;
  onSelect: () => void;
}) {
  const scored = stat.mean !== null;
  const centreY = AXIS_Y - (lift ? ROW_LIFT : 0);
  return (
    <>
      {showNumber && (
        <div
          className={`pointer-events-none absolute -translate-x-1/2 whitespace-nowrap font-mono text-[9px] tabular-nums ${
            selected ? "text-starlight" : "text-static/70"
          }`}
          style={{ left: x, top: 2 }}
        >
          {session.sessionNumber}
        </div>
      )}
      <motion.button
        type="button"
        data-session-id={session.id}
        onClick={onSelect}
        whileHover={{ scale: 1.25 }}
        whileTap={{ scale: 0.95 }}
        transition={springSnappy}
        aria-pressed={selected}
        aria-label={ariaLabel(session, stat)}
        title={tooltip(session, stat)}
        // The button is the hit target and is comfortably larger than the dot
        // it draws — a 3px mark is not something to ask anyone to click.
        className="group absolute flex items-center justify-center rounded-full focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-starlight"
        style={{
          left: x - MARK_GAP / 2,
          top: centreY - MARK_GAP / 2,
          width: MARK_GAP,
          height: MARK_GAP,
        }}
      >
        <span
          // Hovering lights the mark in its own colour — a session-mark glow,
          // never one on the Pulsar accent (the theme's no-glow rule protects
          // the accent, not the data). Inline `boxShadow` on the selected mark
          // wins over the hover class, so the ring never flickers.
          className="block rounded-full transition-[box-shadow] duration-150 group-hover:[box-shadow:0_0_9px_1px_var(--mark-glow)]"
          style={{
            width: MARK,
            height: MARK,
            // An unscored session is hollow rather than grey: "nothing to
            // score" and "scored badly" must not look alike.
            background: scored ? binFor(stat.mean!).fill : "transparent",
            border: scored ? "none" : "1px dashed var(--color-static)",
            "--mark-glow": scored ? binFor(stat.mean!).fill : "var(--color-static)",
            boxShadow: selected
              ? "0 0 0 2px var(--color-starlight), 0 0 12px 2px color-mix(in srgb, var(--color-starlight) 40%, transparent)"
              : undefined,
          } as React.CSSProperties}
        />
      </motion.button>
    </>
  );
}

function ariaLabel(session: SessionListItem, stat: Stat): string {
  const name = `Session ${session.prefixName} ${session.sessionNumber}, ${session.date}`;
  if (stat.runs === 0) return `${name}, no runs recorded`;
  if (stat.mean === null) return `${name}, ${stat.runs} runs, none scored`;
  return `${name}, ${stat.runs} runs, mean P ${stat.mean.toFixed(2)}`;
}

function tooltip(session: SessionListItem, stat: Stat): string {
  const head = `${session.prefixName} ${session.sessionNumber} · ${session.date}`;
  if (stat.runs === 0) return `${head}\nno runs recorded`;
  const runs = `${stat.runs} run${stat.runs === 1 ? "" : "s"}`;
  return stat.mean === null
    ? `${head}\n${runs} · no scored runs`
    : `${head}\n${runs} · mean P = ${stat.mean.toFixed(2)}`;
}

/** `2026-07-24` → `Jul 24`, which is what a reader scans an axis for. */
function shortDate(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${months[Number(match[2]) - 1] ?? match[2]} ${Number(match[3])}`;
}

interface Mark {
  session: SessionListItem;
  x: number;
  /** Odd cluster members sit a row above the axis (`ROW_LIFT`). */
  lift: boolean;
  /** Part of a same-day cluster — its number label is suppressed unless
   *  selected, since stacked marks share an x. */
  clustered: boolean;
}

interface Tick {
  date: string;
  x: number;
  labelled: boolean;
}

/** What an empty archive lays out to. Not merely defensive: the caller's
 *  `useMemo` runs before its own empty-state return, because hook order can't
 *  be conditional — so this branch is reached on every cohort that has no
 *  sessions yet, which every cohort is on the day it is created. */
const EMPTY_LAYOUT = { marks: [], ticks: [], width: PAD * 2, days: 0, showNumbers: true };

/**
 * Pixel positions for every mark and date tick, plus the scroll width they
 * need. Sessions arrive oldest-first (`sessions.list` orders by date), which
 * this relies on for both grouping order and label thinning.
 */
function layOut(sessions: SessionListItem[]): {
  marks: Mark[];
  ticks: Tick[];
  width: number;
  days: number;
  showNumbers: boolean;
} {
  if (sessions.length === 0) return EMPTY_LAYOUT;

  const first = sessions[0]!;
  const last = sessions[sessions.length - 1]!;
  const days = Math.max(0, daysBetween(first.date, last.date));

  const byDate = new Map<string, SessionListItem[]>();
  for (const session of sessions) {
    const bucket = byDate.get(session.date);
    if (bucket) bucket.push(session);
    else byDate.set(session.date, [session]);
  }

  // Same-day marks zigzag over two rows, so a cluster's horizontal span is
  // set by ceil(n/2) columns — one dense rerun day used to widen every day.
  const widest = Math.max(...[...byDate.values()].map((group) => group.length));
  const clusterSpan = (Math.ceil(widest / 2) - 1) * MARK_GAP;
  // A day has to be at least as wide as the widest same-day cluster plus a
  // gap, or two dates' clusters overlap and the axis understates a real break.
  const pxPerDay = Math.max(MIN_PX_PER_DAY, clusterSpan + MARK_GAP);
  const usable = days > 0 ? Math.max(MIN_SPAN_WIDTH, days * pxPerDay) : 0;
  const width = usable + clusterSpan + PAD * 2;
  const originX = PAD + clusterSpan / 2;

  const marks: Mark[] = [];
  const ticks: Tick[] = [];
  let lastLabelX = -Infinity;

  for (const [date, group] of byDate) {
    const x =
      days > 0 ? originX + (daysBetween(first.date, date) / days) * usable : width / 2;
    const labelled = x - lastLabelX >= DATE_LABEL_MIN_GAP;
    if (labelled) lastLabelX = x;
    ticks.push({ date, x, labelled });
    const columns = Math.ceil(group.length / 2);
    group.forEach((session, index) => {
      marks.push({
        session,
        x: x + (Math.floor(index / 2) - (columns - 1) / 2) * MARK_GAP,
        lift: index % 2 === 1,
        clustered: group.length > 1,
      });
    });
  }

  // Per-mark numbers only when the tightest pair of *label positions* can
  // hold them. Stacked marks share an x and are excluded — their labels are
  // suppressed per mark instead (`clustered`).
  const xs = [...new Set(marks.filter((m) => !m.clustered).map((m) => m.x))].sort(
    (a, b) => a - b,
  );
  const gaps = xs.slice(1).map((x, i) => x - xs[i]!);
  const showNumbers = gaps.length === 0 || Math.min(...gaps) >= LABEL_MIN_GAP;

  return { marks, ticks, width, days, showNumbers };
}

interface Stat {
  /** Runs recorded against the session, scored or not. */
  runs: number;
  /** Mean whole-session P across every *scored* run, or null. */
  mean: number | null;
}

const EMPTY_STAT: Stat = { runs: 0, mean: null };

function sessionStats(summary: AnalyticsSummary | null): Map<string, Stat> {
  const out = new Map<string, Stat>();
  if (!summary) return out;
  const totals = new Map<string, { sum: number; n: number; runs: number }>();
  for (const run of summary.runs) {
    const bucket = totals.get(run.sessionId) ?? { sum: 0, n: 0, runs: 0 };
    bucket.runs += 1;
    const value = (run.overall ?? run.metrics[0])?.pSession;
    if (value !== null && value !== undefined) {
      bucket.sum += value;
      bucket.n += 1;
    }
    totals.set(run.sessionId, bucket);
  }
  for (const [sessionId, bucket] of totals) {
    out.set(sessionId, {
      runs: bucket.runs,
      mean: bucket.n > 0 ? bucket.sum / bucket.n : null,
    });
  }
  return out;
}
