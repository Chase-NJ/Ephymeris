import { AnimalRail } from "@/components/analytics/AnimalRail";
import { LearningCurves } from "@/components/analytics/LearningCurves";
import { SessionStrategy } from "@/components/analytics/SessionStrategy";
import { SessionSummary } from "@/components/analytics/SessionSummary";
import type { SessionListItem } from "@/lib/analytics/types";

import type { ReportInput } from "./ReportSheet";

/**
 * One session's sheet — the inside of a single run of the rig.
 *
 * Deliberately narrow in scope: the within-session strategy walk, the learning
 * curves on their trial axis, and the per-animal condition tables. None of the
 * across-session trends and no heatmap, because "just this session" is what
 * this export is for.
 *
 * `AnimalRail` is the one thing here that spans the whole archive, and it earns
 * that twice over. It is the colour→animal legend every other panel on the
 * sheet depends on, so dropping it would mean inventing a second one; and its
 * sparklines say where this session falls in each animal's history, which is
 * the context a single-session figure most often gets asked for.
 */
export function SessionReport({
  input,
  session,
}: {
  input: ReportInput;
  session: SessionListItem;
}) {
  const { summary, profile, colors, metricId, sessionRuns, sessionSeries } = input;
  // See `CohortReport` — kept distinct from the live tree's for the SVG ids.
  const revealKey = `${input.revealKey}:report`;

  return (
    <div className="flex flex-col gap-3">
      {/* `items-start` and an unbounded rail, as in `CohortReport`: a PNG
          cannot scroll, so the roster must be allowed to run past the tile
          beside it rather than be quietly cropped. */}
      <div className="grid grid-cols-[224px_minmax(0,1fr)] items-start gap-3">
        <AnimalRail
          summary={summary}
          profile={profile}
          colors={colors}
          metricId={metricId}
          scroll={false}
        />
        <div className="grid min-w-0 grid-cols-2 gap-3">
          <SessionStrategy
            summary={summary}
            profile={profile}
            colors={colors}
            runs={sessionRuns}
            series={sessionSeries}
            revealKey={revealKey}
          />
          {/* Scoped to the session, so the curves are per-trial rolling
              trajectories rather than one dot per session. */}
          <LearningCurves
            summary={summary}
            profile={profile}
            colors={colors}
            sessionScope={session.id}
            series={sessionSeries}
          />
        </div>
      </div>

      {/* Two-up explicitly: `"auto"` is the route's `xl:` breakpoint, which
          measures the window and would collapse these cards to one column on a
          narrow screen — changing the figure based on nothing to do with it. */}
      <SessionSummary
        summary={summary}
        profile={profile}
        colors={colors}
        session={session}
        runs={sessionRuns}
        series={sessionSeries}
        revealKey={revealKey}
        columns={2}
      />
    </div>
  );
}
