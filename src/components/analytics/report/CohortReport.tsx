import { AnimalRail } from "@/components/analytics/AnimalRail";
import { CohortHeatmap } from "@/components/analytics/CohortHeatmap";
import { EffortTrend } from "@/components/analytics/EffortTrend";
import { LearningCurves } from "@/components/analytics/LearningCurves";
import { OutcomeMix } from "@/components/analytics/OutcomeMix";
import { ResponseTrend } from "@/components/analytics/ResponseTrend";
import { RewardedTrend } from "@/components/analytics/RewardedTrend";
import { StrategySpace } from "@/components/analytics/StrategySpace";
import { ALL_SESSIONS } from "@/lib/analytics/store";

import type { ReportInput } from "./ReportSheet";

/**
 * The across-session sheet — the cohort compared with itself over time.
 *
 * Same panels as the dashboard's `ALL_SESSIONS` scope, in the same order: the
 * rail beside the strategy tile and learning curves, then the heatmap full
 * width, then the four x-slot-sharing trends as one unbroken run.
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
  const { summary, profile, colors, metricId } = input;
  // Distinct from the live tree's, because both are mounted at once and
  // `SessionStrategy` builds SVG gradient ids out of it — two identical ids in
  // one document and every `url(#…)` resolves to the first.
  const revealKey = `${input.revealKey}:report`;

  return (
    <div className="flex flex-col gap-3">
      {/* `items-start` so a short roster gives a compact card here too, the
          way the capped rail does on screen. The rail itself takes
          `scroll={false}`: a rasterizer captures a scroll container as
          whatever was in view, so a long roster would lose animals off the
          bottom of the PNG with nothing to show for it. Unbounded here, it
          may make this row taller than the strategy tile — which is the right
          trade for a figure that cannot be scrolled. */}
      <div className="grid grid-cols-[224px_minmax(0,1fr)] items-start gap-3">
        <AnimalRail
          summary={summary}
          profile={profile}
          colors={colors}
          metricId={metricId}
          scroll={false}
        />
        <div className="grid min-w-0 grid-cols-2 gap-3">
          <StrategySpace summary={summary} profile={profile} colors={colors} />
          <LearningCurves
            summary={summary}
            profile={profile}
            colors={colors}
            sessionScope={ALL_SESSIONS}
            series={[]}
          />
        </div>
      </div>

      <CohortHeatmap
        summary={summary}
        profile={profile}
        metricId={metricId}
        sessionScope={ALL_SESSIONS}
        revealKey={revealKey}
        scroll={false}
      />

      {/* Stacked full-width and never side by side, exactly as on screen:
          the two share x slots and a denominator, so the vertical gap
          between the curves *is* the hold-failure rate — a reading that
          only survives if a session sits above itself in both. Effort and
          outcome mix share those slots too, so all four stay one run. */}
      <RewardedTrend
        summary={summary}
        profile={profile}
        colors={colors}
        revealKey={revealKey}
      />
      <ResponseTrend
        summary={summary}
        profile={profile}
        colors={colors}
        revealKey={revealKey}
      />
      <div className="grid min-w-0 grid-cols-2 gap-3">
        <EffortTrend summary={summary} profile={profile} revealKey={revealKey} />
        <OutcomeMix summary={summary} profile={profile} revealKey={revealKey} />
      </div>
    </div>
  );
}
