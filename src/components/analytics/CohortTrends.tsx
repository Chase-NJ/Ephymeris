import { useMemo } from "react";

import { AccuracyTrend } from "@/components/analytics/AccuracyTrend";
import { AnimalRail } from "@/components/analytics/AnimalRail";
import { EffortTrend } from "@/components/analytics/EffortTrend";
import { OutcomeMix } from "@/components/analytics/OutcomeMix";
import { StrategySpace } from "@/components/analytics/StrategySpace";
import { TaskStrip } from "@/components/analytics/TaskStrip";
import type { AnalyticsSummary } from "@/lib/analytics/types";
import { sessionOutcomePoints, taskLabels } from "@/lib/analytics/view";

/**
 * The cohort compared with itself over time (`DATA.md#analytics-views`) — one
 * layout for the dashboard's all-sessions scope and its PNG sheet, so the two
 * cannot drift apart.
 *
 * The first row answers "how is each animal doing": the roster, the strategy
 * plane, then the accuracy trend with the task strip over it. The strategy
 * plane is square and sits left of the trend at a fixed width, so the trend
 * keeps the rest of the row — slimmer below `2xl`, so a 1280px window still
 * leaves the trend half the row rather than a sliver. **The strip and the trend stay one column**: they
 * share x slots (`sessionOutcomePoints`), so a session must sit directly above
 * itself, and nothing may come between them. Effort and the outcome mix follow
 * as the second row — what the accuracy cost, and what happened instead.
 *
 * `sheet` swaps every responsive grid for a fixed one: Tailwind's breakpoints
 * measure the window, and a report sheet's authored width has nothing to do
 * with the window's (`DATA.md#exporting-a-sheet`).
 */
export function CohortTrends({
  summary,
  colors,
  revealKey,
  sheet = false,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  revealKey: string;
  sheet?: boolean;
}) {
  const points = useMemo(() => sessionOutcomePoints(summary), [summary]);
  const labels = useMemo(() => taskLabels(summary), [summary]);

  return (
    <div className="flex flex-col gap-3">
      <div
        className={
          sheet
            ? "grid grid-cols-[224px_340px_minmax(0,1fr)] items-start gap-3"
            : "grid grid-cols-1 gap-3 xl:grid-cols-[208px_minmax(240px,280px)_minmax(0,1fr)] 2xl:grid-cols-[224px_minmax(300px,360px)_minmax(0,1fr)] xl:items-start"
        }
      >
        {/* Stretches to the row so the capped rail has a height to cap
            against (`AnimalRail`'s `scroll`). */}
        <div className={sheet ? "" : "xl:relative xl:self-stretch"}>
          <AnimalRail summary={summary} colors={colors} scroll={sheet ? false : "xl"} />
        </div>
        {/* Stacked, the plane would grow as wide as the page and as tall; it
            keeps a square's worth of width instead. */}
        <div className={sheet ? "min-w-0" : "w-full max-w-[420px] min-w-0 xl:max-w-none"}>
          <StrategySpace summary={summary} colors={colors} />
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          <TaskStrip points={points} labels={labels} />
          <AccuracyTrend summary={summary} colors={colors} revealKey={revealKey} />
        </div>
      </div>
      <div className={sheet ? "grid grid-cols-2 gap-3" : "grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2"}>
        <EffortTrend summary={summary} revealKey={revealKey} />
        <OutcomeMix summary={summary} revealKey={revealKey} />
      </div>
    </div>
  );
}
