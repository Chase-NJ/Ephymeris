import { motion } from "framer-motion";
import { useMemo } from "react";

import { Button } from "@/components/common/controls";
import { useAnalyticsStore } from "@/lib/analytics/context";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import type { AnalyticsSummary, SessionListItem } from "@/lib/analytics/types";
import { springSnappy } from "@/lib/motion";
import { binFor, daysBetween } from "@/lib/analytics/view";

/**
 * The session browser, and a visualization in its own right (`data.md`
 * §2.2).
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

  if (sessions.length === 0) {
    return (
      <div className="surface rounded-md px-4 py-3">
        <p className="text-[12px] text-static">
          No sessions recorded for this cohort yet.
        </p>
      </div>
    );
  }

  const { marks, ticks, width, days, showNumbers } = layout;
  const selectedSession = sessions.find((s) => s.id === selected) ?? null;

  return (
    <div className="surface rounded-md px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[11px] text-static">
          Sessions
          <span className="ml-2 text-static/70">spaced by date — a gap is a real gap</span>
        </span>
        <Button
          variant={selected === ALL_SESSIONS ? "primary" : "outline"}
          onClick={() => store.selectSession(ALL_SESSIONS)}
        >
          All sessions
        </Button>
      </div>

      <div className="mt-1 overflow-x-auto pb-1">
        <div className="relative h-[62px]" style={{ width }}>
          {/* The axis itself, drawn only across the span the data occupies. */}
          <div
            className="absolute border-t border-halo"
            style={{ left: PAD, right: PAD, top: AXIS_Y }}
          />

          {ticks.map((tick) => (
            <div key={tick.date}>
              <div
                className="absolute w-px bg-halo"
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
                stat={stat}
                selected={isSelected}
                showNumber={showNumbers || isSelected}
                onSelect={() => store.selectSession(mark.session.id)}
              />
            );
          })}
        </div>
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

function SessionMark({
  session,
  x,
  stat,
  selected,
  showNumber,
  onSelect,
}: {
  session: SessionListItem;
  x: number;
  stat: Stat;
  selected: boolean;
  showNumber: boolean;
  onSelect: () => void;
}) {
  const scored = stat.mean !== null;
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
        onClick={onSelect}
        whileHover={{ scale: 1.25 }}
        whileTap={{ scale: 0.95 }}
        transition={springSnappy}
        aria-pressed={selected}
        aria-label={ariaLabel(session, stat)}
        title={tooltip(session, stat)}
        // The button is the hit target and is comfortably larger than the dot
        // it draws — a 3px mark is not something to ask anyone to click.
        className="absolute flex items-center justify-center rounded-full focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-starlight"
        style={{
          left: x - MARK_GAP / 2,
          top: AXIS_Y - MARK_GAP / 2,
          width: MARK_GAP,
          height: MARK_GAP,
        }}
      >
        <span
          className="block rounded-full"
          style={{
            width: MARK,
            height: MARK,
            // An unscored session is hollow rather than grey: "nothing to
            // score" and "scored badly" must not look alike.
            background: scored ? binFor(stat.mean!).fill : "transparent",
            border: scored ? "none" : "1px dashed var(--color-static)",
            boxShadow: selected ? "0 0 0 2px var(--color-starlight)" : "none",
          }}
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

  const widest = Math.max(...[...byDate.values()].map((group) => group.length));
  const clusterSpan = (widest - 1) * MARK_GAP;
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
    group.forEach((session, index) => {
      marks.push({ session, x: x + (index - (group.length - 1) / 2) * MARK_GAP });
    });
  }

  // Per-mark numbers only when the tightest pair can hold them.
  const gaps = marks.slice(1).map((mark, i) => mark.x - marks[i]!.x);
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
