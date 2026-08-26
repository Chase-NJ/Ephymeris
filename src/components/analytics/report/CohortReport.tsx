import { useMemo } from "react";

import { AccuracyTrend } from "@/components/analytics/AccuracyTrend";
import { AnimalRail } from "@/components/analytics/AnimalRail";
import { EffortTrend } from "@/components/analytics/EffortTrend";
import { LearningCurves } from "@/components/analytics/LearningCurves";
import { OutcomeMix } from "@/components/analytics/OutcomeMix";
import { StrategySpace } from "@/components/analytics/StrategySpace";
import { TaskStrip } from "@/components/analytics/TaskStrip";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import { sessionOutcomePoints, taskLabels } from "@/lib/analytics/view";

import type { ReportInput } from "./ReportSheet";

/**
 * The across-session sheet — the cohort compared with itself over time.
 *
 * Same panels as the dashboard's `ALL_SESSIONS` scope, in the same order: the
 * x-slot-sharing run first (task strip, the combined accuracy figure, effort
 * and outcome mix), then the rail beside the strategy tile and learning
 * curves.
 *
 * One deliberate difference throughout. Every grid here is a plain
 * `grid-cols-2` rather than the route's `xl:` variant, because Tailwind's
 * breakpoints are *viewport* queries and the sheet's authored width has
 * nothing to do with the window's.
 *
 * `SessionRail` is left out: it is a control, not a reading, and it wraps a
 * horizontal scroller that would rasterize to whatever happened to be in view.
 * The masthead carries its date range instead.
 */
export function CohortReport({ input }: { input: ReportInput }) {
  const { summary, colors } = input;
  // Distinct from the live tree's, because both are mounted at once and
  // `SessionStrategy` builds SVG gradient ids out of it — two identical ids in
  // one document and every `url(#…)` resolves to the first.
  const revealKey = `${input.revealKey}:report`;
  const points = useMemo(() => sessionOutcomePoints(summary), [summary]);
  const labels = useMemo(() => taskLabels(summary), [summary]);

  return (
    <div className="flex flex-col gap-3">
      {/* The headline run leads, exactly as on screen: strip, the combined
          accuracy figure, then effort and outcome mix — all sharing x slots,
          one unbroken run. */}
      <TaskStrip points={points} labels={labels} />
      <AccuracyTrend summary={summary} colors={colors} revealKey={revealKey} />
      <div className="grid min-w-0 grid-cols-2 gap-3">
        <EffortTrend summary={summary} revealKey={revealKey} />
        <OutcomeMix summary={summary} revealKey={revealKey} />
      </div>

      {/* `items-start` so a short roster gives a compact card here too, the
          way the capped rail does on screen. The rail itself takes
          `scroll={false}`: a rasterizer captures a scroll container as
          whatever was in view, so a long roster would lose animals off the
          bottom of the PNG with nothing to show for it. Unbounded here, it
          may make this row taller than the strategy tile — which is the right
          trade for a figure that cannot be scrolled. */}
      <div className="grid grid-cols-[224px_minmax(0,1fr)] items-start gap-3">
        <AnimalRail summary={summary} colors={colors} scroll={false} />
        <div className="grid min-w-0 grid-cols-2 gap-3">
          <StrategySpace summary={summary} colors={colors} />
          <LearningCurves
            summary={summary}
            colors={colors}
            sessionScope={ALL_SESSIONS}
            sessionRuns={[]}
            series={[]}
          />
        </div>
      </div>
    </div>
  );
}
