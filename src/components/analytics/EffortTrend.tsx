import { motion } from "framer-motion";
import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { useRevealOnView } from "@/components/charts/reveal";
import { UnitChart } from "@/components/charts/UnitChart";
import type { AnalyticsSummary, ProfileGroup } from "@/lib/analytics/types";
import {
  sessionOutcomePoints,
  sessionSlot,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * Cohort effort across sessions (`analytics.md` §6.6) — how many trials each
 * session ran, and how many the animals actually engaged with.
 *
 * Every accuracy above this panel divides by `administered`, so a flat
 * rewarded line over collapsing trial counts is a very different cohort from
 * the same line over steady ones (§3.8) — this is the panel that tells those
 * apart. Each session is one bar: total height is `trials`, the filled span
 * is `administered`, and the outlined remainder is the aborted trials —
 * engagement that never happened, drawn as an absence rather than as another
 * solid category that could be misread as an outcome.
 *
 * Counts, not rates, so the y scale is the cohort's own maximum rather than
 * 0–1 — the one across-session panel where that is the honest axis.
 */

const HEIGHT = 54;

/** Fixed rather than aspect-driven, for the reason `RewardedTrend` states —
 *  and the same value, so the row below it reads as one band. */
const PLOT_PX = 132;

export function EffortTrend(props: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen (§2.7). */
  revealKey: string;
}) {
  return <EffortBody key={props.revealKey} {...props} />;
}

function EffortBody({
  summary,
  profile,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
}) {
  const { ref, seen } = useRevealOnView();
  const points = useMemo(() => sessionOutcomePoints(summary, profile), [summary, profile]);

  if (points.length === 0) return null;

  const maxTrials = Math.max(...points.map((point) => point.outcomes.trials), 1);
  const totals = points.reduce(
    (sum, point) => ({
      trials: sum.trials + point.outcomes.trials,
      administered: sum.administered + point.outcomes.administered,
    }),
    { trials: 0, administered: 0 },
  );
  const width = barWidth(points.length);

  return (
    <div className="surface rounded-md p-4" ref={ref}>
      <ChartFrame
        title={
          <span>
            Effort
            <span className="ml-2 text-static/70">
              trials per session · filled = administered, outline = aborted
            </span>
          </span>
        }
        yTop={String(maxTrials)}
        yBottom="0"
        xLeft={points[0]!.session.date}
        xRight={points[points.length - 1]!.session.date}
        // Kept short on purpose: this panel is half-width, and a long footer
        // squeezes the two date labels either side of it into ellipses.
        footer={
          <span className="truncate text-static/70">
            {totals.administered} of {totals.trials} administered
          </span>
        }
      >
        <div style={{ height: PLOT_PX }}>
          <UnitChart height={HEIGHT} className="h-full w-full">
            {points.map((point, index) => (
              <EffortBar
                key={point.session.id}
                point={point}
                x={barLeft(index, points.length, width)}
                width={width}
                max={maxTrials}
                seen={seen}
                // Bars surface in the order the sessions happened, so the
                // reveal reads as history being laid down (§2.7).
                delay={sessionSlot(index, points.length) * 0.5}
              />
            ))}
          </UnitChart>
        </div>
      </ChartFrame>
    </div>
  );
}

function EffortBar({
  point,
  x,
  width,
  max,
  seen,
  delay,
}: {
  point: SessionOutcomePoint;
  x: number;
  width: number;
  max: number;
  seen: boolean;
  delay: number;
}) {
  const { trials, administered } = point.outcomes;
  const trialsTop = (1 - trials / max) * HEIGHT;
  const administeredTop = (1 - administered / max) * HEIGHT;

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: seen ? 1 : 0 }}
      transition={{ duration: 0.28, delay }}
    >
      <title>{describeBar(point)}</title>
      {trials > administered && (
        <rect
          x={x}
          y={trialsTop}
          width={width}
          height={Math.max(administeredTop - trialsTop, 0)}
          fill="none"
          stroke="var(--color-halo)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      )}
      {administered > 0 && (
        <rect
          x={x}
          y={administeredTop}
          width={width}
          height={HEIGHT - administeredTop}
          fill="var(--color-pulsar)"
          fillOpacity={0.85}
        />
      )}
    </motion.g>
  );
}

function describeBar(point: SessionOutcomePoint): string {
  const { session, outcomes } = point;
  return (
    `${session.prefixName}_${session.sessionNumber} · ${session.date}\n` +
    `${outcomes.trials} trials · ${outcomes.administered} administered · ` +
    `${outcomes.aborted} aborted`
  );
}

/** Bar width in viewBox units — a slice of the slot spacing, capped so a
 *  two-session cohort doesn't read as two slabs. */
export function barWidth(total: number): number {
  return total <= 1 ? 6 : Math.min(6, (100 / (total - 1)) * 0.55);
}

/** Left edge for the bar centred on its session slot, nudged inward at the
 *  extremes so the first and last bars aren't halved by the viewBox. */
export function barLeft(index: number, total: number, width: number): number {
  const centre = sessionSlot(index, total) * 100;
  return Math.min(Math.max(centre - width / 2, 0), 100 - width);
}
