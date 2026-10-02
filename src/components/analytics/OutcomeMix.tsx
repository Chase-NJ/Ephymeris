import { ChartPie } from "lucide-react";
import { motion } from "framer-motion";
import { useMemo } from "react";

import { barLeft, barWidth } from "@/components/analytics/EffortTrend";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { useRevealOnView } from "@/components/charts/reveal";
import { UnitChart } from "@/components/charts/UnitChart";
import type { AnalyticsSummary } from "@/lib/analytics/types";
import {
  OUTCOME_STYLE,
  describeTaskMix,
  poolOutcomes,
  sessionOutcomePoints,
  sessionSlot,
  taskChanges,
  taskLabels,
  type OutcomeKey,
  type PooledOutcomes,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * How each session's administered trials resolved (`DATA.md#pooling-across-tasks`).
 *
 * The rewarded line above answers "how often was fluid earned"; this panel
 * answers "and what happened instead" — whether the misses were hold
 * failures, wrong wells, or silence, in the same outcome colours the session
 * cards use, so the same behaviour is the same colour in both places.
 * A cohort drifting from wrong-well to hold-failure errors is *learning the
 * discrimination* while the rewarded line barely moves, and this is the panel
 * where that shows.
 *
 * Shares its x slots with the panels above. Each bar is normalised to its own
 * administered count — composition, deliberately not effort, because the
 * effort panel beside it already shows the counts and folding both into one
 * bar would hide each behind the other. A session that administered nothing
 * leaves its slot empty rather than inventing a composition (`DATA.md#pooling-across-tasks`).
 */

const HEIGHT = 54;

/** Fixed rather than aspect-driven, matching the panels above. */
const PLOT_PX = 132;

/** Stack order, bottom to top — rewarded sits on the baseline so its share
 *  reads against the same edge as the rewarded line's y axis. */
const STACK: readonly OutcomeKey[] = ["rewarded", "holdFailed", "wrongWell", "noResponse"];

export function OutcomeMix(props: {
  summary: AnalyticsSummary;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen. */
  revealKey: string;
}) {
  return <MixBody key={props.revealKey} {...props} />;
}

function MixBody({ summary }: { summary: AnalyticsSummary }) {
  const { ref, seen } = useRevealOnView();
  const points = useMemo(() => sessionOutcomePoints(summary), [summary]);
  const labels = useMemo(() => taskLabels(summary), [summary]);

  if (points.length === 0) return null;

  const overall = poolOutcomes(summary.runs);
  const changes = taskChanges(points).map((change) => ({
    from: { x: change.x, y: 0 },
    to: { x: change.x, y: 1 },
  }));
  const width = barWidth(points.length);

  return (
    <div className="surface rounded-md p-4" ref={ref}>
      <ChartFrame
        icon={ChartPie}
        title={
          <span>
            Outcome mix
            <span className="ml-2 text-static/70">
              how administered trials resolved · share per session
            </span>
          </span>
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft={points[0]!.session.date}
        xRight={points[points.length - 1]!.session.date}
        // No footer: the cohort-wide composition is four figures long and this
        // panel is half-width, so it rides the legend row below instead of
        // crushing the dates on either side of it.
      >
        <div style={{ height: PLOT_PX }}>
          <UnitChart
            height={HEIGHT}
            className="h-full w-full"
            references={[{ y: 0.5 }, ...changes]}
          >
            {points.map((point, index) =>
              point.outcomes.administered === 0 ? null : (
                <MixBar
                  key={point.session.id}
                  point={point}
                  x={barLeft(index, points.length, width)}
                  width={width}
                  seen={seen}
                  labels={labels}
                  // Bars surface in session order, like the effort panel.
                  delay={sessionSlot(index, points.length) * 0.5}
                />
              ),
            )}
          </UnitChart>
        </div>
      </ChartFrame>
      <Legend overall={overall} />
    </div>
  );
}

function MixBar({
  point,
  x,
  width,
  seen,
  labels,
  delay,
}: {
  point: SessionOutcomePoint;
  x: number;
  width: number;
  seen: boolean;
  labels: Map<string, string>;
  delay: number;
}) {
  const administered = point.outcomes.administered;
  let floor = 0;
  const segments = STACK.flatMap((key) => {
    const share = point.outcomes[key] / administered;
    if (share === 0) return [];
    const segment = { key, from: floor, to: floor + share };
    floor += share;
    return [segment];
  });

  return (
    <motion.g
      initial={{ opacity: 0 }}
      animate={{ opacity: seen ? 1 : 0 }}
      transition={{ duration: 0.28, delay }}
    >
      <title>{describeBar(point, labels)}</title>
      {segments.map((segment) => (
        <rect
          key={segment.key}
          x={x}
          y={(1 - segment.to) * HEIGHT}
          width={width}
          height={(segment.to - segment.from) * HEIGHT}
          fill={OUTCOME_STYLE[segment.key].fill}
        />
      ))}
    </motion.g>
  );
}

function describeBar(point: SessionOutcomePoint, labels: Map<string, string>): string {
  const { session, outcomes } = point;
  return (
    `${session.prefixName}_${session.sessionNumber} · ${session.date}` +
    ` · ${describeTaskMix(point.tasks, labels)}\n` +
    `${outcomes.administered} administered — ${shares(outcomes)}`
  );
}

function shares(outcomes: PooledOutcomes): string {
  return STACK.filter((key) => outcomes[key] > 0)
    .map(
      (key) =>
        `${pct(outcomes[key] / outcomes.administered)} ${OUTCOME_STYLE[key].label}`,
    )
    .join(" · ");
}

/**
 * The four outcomes with the cohort's own share of each beside them — the
 * legend and the summary in one row, so the swatch that names a colour also
 * carries the number it resolves to across every session.
 */
function Legend({ overall }: { overall: PooledOutcomes }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[9px] text-static/70">
      {STACK.map((key) => (
        <span key={key} className="flex items-center gap-1">
          <span
            className="inline-block size-2 rounded-[2px]"
            style={{ background: OUTCOME_STYLE[key].fill }}
          />
          {OUTCOME_STYLE[key].label}
          {overall.administered > 0 && (
            <span className="tabular-nums text-static">
              {pct(overall[key] / overall.administered)}
            </span>
          )}
        </span>
      ))}
      <span className="ml-auto">cohort, all sessions</span>
    </div>
  );
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}
