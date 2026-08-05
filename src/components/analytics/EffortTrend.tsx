import { motion } from "framer-motion";
import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { useRevealOnView } from "@/components/charts/reveal";
import { UnitChart } from "@/components/charts/UnitChart";
import type { AnalyticsSummary } from "@/lib/analytics/types";
import {
  describeTaskMix,
  sessionOutcomePoints,
  sessionSlot,
  taskChanges,
  taskLabels,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * Cohort effort across sessions (`data.md` §11.6) — how many trials each
 * session offered, and how many the animals actually engaged with.
 *
 * Every accuracy above this panel divides by `administered`, so a flat
 * rewarded line over collapsing trial counts is a very different cohort from
 * the same line over steady ones (§3.8) — this is the panel that tells those
 * apart. Each session is one bar: total height is `presented` (§3.10), the
 * filled span is `administered`, and the outlined remainder is everything in
 * between — drawn as an absence rather than as another solid category that
 * could be misread as an outcome.
 *
 * **The total is the trial light, not the odor onset.** It used to be
 * `trials`, which counts odor onsets — and the firmware only reaches its
 * odor-on strobe once the animal has poked and held, so a session the cohort
 * largely ignored drew a *short* bar rather than a mostly-hollow one. The
 * panel that exists to show collapsing engagement was the one place engagement
 * could hide. A profile with no declared trial light has no ladder and falls
 * back to `trials`, which is the most that can honestly be drawn for it.
 *
 * Counts, not rates, so the y scale is the cohort's own maximum rather than
 * 0–1 — the one across-session panel where that is the honest axis.
 */

const HEIGHT = 54;

/** Fixed rather than aspect-driven, for the reason `AccuracyTrend` states —
 *  this panel spans half the column, and an aspect-driven height would put a
 *  trend line in a field of empty plot. */
const PLOT_PX = 132;

export function EffortTrend(props: {
  summary: AnalyticsSummary;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen (§2.7). */
  revealKey: string;
}) {
  return <EffortBody key={props.revealKey} {...props} />;
}

function EffortBody({ summary }: { summary: AnalyticsSummary }) {
  const { ref, seen } = useRevealOnView();
  const points = useMemo(() => sessionOutcomePoints(summary), [summary]);
  const labels = useMemo(() => taskLabels(summary), [summary]);

  if (points.length === 0) return null;

  const maxTrials = Math.max(...points.map(offered), 1);
  const totals = points.reduce(
    (sum, point) => ({
      offered: sum.offered + offered(point),
      administered: sum.administered + point.outcomes.administered,
    }),
    { offered: 0, administered: 0 },
  );
  const width = barWidth(points.length);
  const changes = taskChanges(points).map((change) => ({
    from: { x: change.x, y: 0 },
    to: { x: change.x, y: 1 },
  }));

  return (
    <div className="surface rounded-md p-4" ref={ref}>
      <ChartFrame
        title={
          <span>
            Effort
            <span className="ml-2 text-static/70">
              trials offered per session · filled = administered
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
            {totals.administered} of {totals.offered} administered
          </span>
        }
      >
        <div style={{ height: PLOT_PX }}>
          <UnitChart height={HEIGHT} className="h-full w-full" references={changes}>
            {points.map((point, index) => (
              <EffortBar
                key={point.session.id}
                point={point}
                x={barLeft(index, points.length, width)}
                width={width}
                max={maxTrials}
                seen={seen}
                labels={labels}
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
  labels,
  delay,
}: {
  point: SessionOutcomePoint;
  x: number;
  width: number;
  max: number;
  seen: boolean;
  labels: Map<string, string>;
  delay: number;
}) {
  const { administered } = point.outcomes;
  const total = offered(point);
  const trialsTop = (1 - total / max) * HEIGHT;
  const administeredTop = (1 - administered / max) * HEIGHT;

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: seen ? 1 : 0 }}
      transition={{ duration: 0.28, delay }}
    >
      <title>{describeBar(point, labels)}</title>
      {total > administered && (
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

/**
 * The bar's total: trials the boxes offered (§3.10).
 *
 * Falls back to `trials` — odor onsets — for a profile that declares no trial
 * light. That undercounts, and knowingly: it is the largest number such a
 * profile can support, and drawing nothing would hide the session entirely.
 */
function offered(point: SessionOutcomePoint): number {
  return point.engagement.known ? point.engagement.presented : point.outcomes.trials;
}

function describeBar(point: SessionOutcomePoint, labels: Map<string, string>): string {
  const { session, outcomes, engagement } = point;
  // The full ladder when the profile can express it — the two gaps are
  // different behaviours (never engaged vs let go before odor) and the bar
  // itself can only show their sum.
  const effort = engagement.known
    ? `${engagement.presented} offered · ${engagement.poked} engaged · ` +
      `${outcomes.administered} administered\n` +
      `${engagement.presented - engagement.poked} never poked · ` +
      `${engagement.poked - engagement.odorDelivered} left before odor · ` +
      `${outcomes.aborted} aborted`
    : `${outcomes.trials} trials · ${outcomes.administered} administered · ` +
      `${outcomes.aborted} aborted`;
  return (
    `${session.prefixName}_${session.sessionNumber} · ${session.date}` +
    ` · ${describeTaskMix(point.tasks, labels)}\n${effort}`
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
