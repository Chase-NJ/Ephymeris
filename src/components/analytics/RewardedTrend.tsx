import { motion } from "framer-motion";
import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { UnitChart, type BandPoint, type Mark, type Point } from "@/components/charts/UnitChart";
import type { AnalyticsSummary, ProfileGroup, SessionListItem } from "@/lib/analytics/types";
import { poolOutcomes, runsInProfile, type PooledOutcomes } from "@/lib/analytics/view";

/**
 * Cohort mean **rewarded** accuracy across sessions (`analytics.md` §3.8).
 *
 * Deliberately a separate panel from the learning curves rather than another
 * line on them: those plot the declared metrics, which are
 * reward-*unconditional* — an animal that reaches the correct well and
 * releases before the hold still scores a hit there. This is the stricter
 * question, "how often did the cohort actually earn water", and the two
 * belong on separate axes or neither can be read honestly. The panel says
 * `fluid delivered` in the frame for exactly that reason.
 *
 * Across sessions only. Within one session there is a single pooled figure,
 * not a trend, and the session summary shows it per animal instead.
 */

/** Below this many administered trials the point is drawn hollow (§3.5). */
const THIN = 30;

export function RewardedTrend({
  summary,
  profile,
  revealKey,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  /** Changes when the data does — restarts the draw-on. */
  revealKey: string;
}) {
  const points = useMemo(() => buildPoints(summary, profile), [summary, profile]);

  if (points.length === 0) {
    return (
      <Panel>
        <p className="text-[12px] leading-relaxed text-static">
          No rewarded-trial data for this task. A task only reports it if its
          profile declares the reward vocabulary (§3.8).
        </p>
      </Panel>
    );
  }

  const line: Point[] = points.map((point, index) => ({
    x: at(index, points.length),
    y: point.outcomes.pRewarded ?? 0,
  }));
  const band: BandPoint[] = points.map((point, index) => ({
    x: at(index, points.length),
    low: point.outcomes.low ?? 0,
    high: point.outcomes.high ?? 0,
  }));
  const marks: Mark[] = points.map((point, index) => ({
    x: at(index, points.length),
    y: point.outcomes.pRewarded ?? 0,
    r: 1.6,
    fill: "var(--color-pulsar)",
    hollow: point.outcomes.administered < THIN,
  }));

  const overall = poolOutcomes(runsInProfile(summary.runs, profile));

  return (
    <Panel>
      <ChartFrame
        title={
          <span>
            Rewarded accuracy
            <span className="ml-2 text-static/70">
              fluid delivered · pooled across the cohort
            </span>
          </span>
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft={points[0]!.session.date}
        xRight={points[points.length - 1]!.session.date}
        footer={
          <span className="truncate text-static/70">
            {overall.pRewarded !== null
              ? `${pct(overall.pRewarded)} of ${overall.administered} administered trials earned fluid`
              : "no administered trials"}
            {" · band = 95% Wilson"}
          </span>
        }
      >
        {/* The band is drawn by the chart; the line draws itself on top so the
            reveal reads as the cohort's history being laid down in order. */}
        <div className="relative">
          <UnitChart
            height={54}
            references={[{ y: 0.5 }]}
            bands={[{ points: band, fill: "var(--color-pulsar)", opacity: 0.14 }]}
            marks={marks}
          />
          <svg
            viewBox="0 0 100 54"
            preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 h-full w-full"
            aria-hidden
          >
            <motion.polyline
              key={revealKey}
              points={line.map((p) => `${p.x * 100},${(1 - p.y) * 54}`).join(" ")}
              fill="none"
              stroke="var(--color-pulsar)"
              strokeWidth={1.6}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.9, ease: "easeOut" }}
            />
          </svg>
        </div>
      </ChartFrame>
    </Panel>
  );
}

interface SessionPoint {
  session: SessionListItem;
  outcomes: PooledOutcomes;
}

/** One point per session that actually administered a trial on this task. */
function buildPoints(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
): SessionPoint[] {
  const eligible = runsInProfile(summary.runs, profile);
  const bySession = new Map<string, typeof eligible>();
  for (const run of eligible) {
    const bucket = bySession.get(run.sessionId);
    if (bucket) bucket.push(run);
    else bySession.set(run.sessionId, [run]);
  }
  // `summary.sessions` is already chronological, so walking it keeps the
  // x-axis in session order without a second sort.
  return summary.sessions.flatMap((session) => {
    const runs = bySession.get(session.id);
    if (!runs) return [];
    const outcomes = poolOutcomes(runs);
    if (outcomes.pRewarded === null) return [];
    return [{ session, outcomes }];
  });
}

/** A single session sits centred rather than pinned to the left edge. */
function at(index: number, total: number): number {
  return total <= 1 ? 0.5 : index / (total - 1);
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function Panel({ children }: { children: React.ReactNode }) {
  return <div className="surface rounded-md p-4">{children}</div>;
}
