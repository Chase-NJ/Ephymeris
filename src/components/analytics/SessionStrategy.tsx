import { motion } from "framer-motion";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { useHasHighlight, useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import type {
  AnalyticsSummary,
  ProfileGroup,
  RunSeries,
  RunSummary,
  StrategyPoint,
} from "@/lib/analytics/types";
import { declaredMetrics } from "@/lib/analytics/view";
import {
  NoPlane,
  PLANE_VIEWBOX,
  PlaneReferences,
  StrategyNote,
  StrategyPanel,
  px,
  py,
} from "./strategyPlane";

/**
 * The strategy plane, walked **within one session** (`analytics.md` §4.4).
 *
 * `StrategySpace` plots one point per session, so a session is an endpoint
 * there and its shape is invisible: an animal that answered the same port for
 * the first eighty trials and then began discriminating lands in exactly the
 * same place as one that was steady throughout. Same axes, same reference
 * marks, same region meanings — walked at trial resolution instead.
 *
 * Each animal's walk is one path from a hollow start marker to a filled end
 * marker, fading dim → full along its length. That is the same
 * direction-of-travel grammar the across-session trail uses, deliberately: one
 * reading serves both panels, and the only thing that changes between them is
 * the clock.
 *
 * The coordinates are the **rolling** figure at the profile's authored window,
 * never the running whole-session average — the question is what strategy is
 * running right now, and a cumulative average is dominated by its own history,
 * which would flatten the very transition this panel exists to show. The walk
 * arrives on `analytics.series` as `trail`; it cannot be assembled here from
 * the per-metric series, whose indices are each metric's own counted trials and
 * therefore not a shared clock.
 */
export function SessionStrategy({
  summary,
  profile,
  colors,
  runs,
  series,
  revealKey,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  runs: RunSummary[];
  series: RunSeries[];
  revealKey: string;
}) {
  const axes = declaredMetrics(profile);
  const names = new Map(summary.animals.map((animal) => [animal.id, animal.name]));

  if (!profile || axes.length !== 2) {
    return (
      <NoPlane
        taskName={profile?.taskName ?? null}
        metricCount={axes.length}
        hasProfile={profile !== null}
      />
    );
  }

  const [xMetric, yMetric] = axes;
  const walks = runs
    .map((run) => ({
      run,
      points: series.find((entry) => entry.runId === run.runId)?.trail ?? [],
    }))
    .filter((walk) => walk.points.length > 0);

  return (
    <StrategyPanel>
      <ChartFrame
        title={
          <span>
            Strategy within this session
            <span className="ml-2 text-static/70">one point per trial</span>
          </span>
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft="0.0"
        xRight="1.0"
        footer={
          <span className="truncate text-static/70">
            ↑ {yMetric!.label} · → {xMetric!.label}
          </span>
        }
      >
        <svg
          viewBox={PLANE_VIEWBOX}
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Each animal's strategy over the course of this session"
        >
          <PlaneReferences />
          {walks.map((walk) => (
            <AnimalWalk
              key={walk.run.runId}
              run={walk.run}
              name={names.get(walk.run.animalId) ?? walk.run.animalId}
              points={walk.points}
              color={colors.get(walk.run.animalId) ?? "var(--color-series-1)"}
              revealKey={revealKey}
            />
          ))}
        </svg>
      </ChartFrame>

      {walks.length === 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-static">
          No walk to draw — a position needs both conditions to have scored at
          least one trial, and nothing in this session reached that.
        </p>
      )}

      <StrategyNote xMetric={xMetric!} yMetric={yMetric!} />
      <p className="mt-1 text-[10px] leading-relaxed text-static/80">
        Hollow marker is where the animal started, filled is where it ended;
        the path fades in along the way. Position is the rolling window, so it
        is the strategy running at that moment rather than the session average.
      </p>
    </StrategyPanel>
  );
}

/**
 * One animal's walk.
 *
 * A separate component per animal because that is what the cross-panel
 * highlight scheme requires (`context.ts`'s `useIsHighlighted` invariant) — a
 * single component looping over animals would re-render every walk on every
 * hover and silently lose the isolation.
 *
 * The fade is drawn as one gradient-stroked path rather than as per-segment
 * opacity: a hundred-trial walk is a hundred segments, and a hundred elements
 * per animal in a panel that re-renders on hover is the thing to avoid.
 */
function AnimalWalk({
  run,
  name,
  points,
  color,
  revealKey,
}: {
  run: RunSummary;
  name: string;
  points: StrategyPoint[];
  color: string;
  revealKey: string;
}) {
  const store = useAnalyticsStore();
  const highlighted = useIsHighlighted(run.animalId);
  const someoneHighlighted = useHasHighlight();
  const dimmed = someoneHighlighted && !highlighted;

  const start = points[0]!;
  const end = points[points.length - 1]!;
  const path = points.map((p) => `${px(p.x)},${py(p.y)}`).join(" ");
  // Unique per animal *and* per reveal, so two panels' gradients can never
  // collide in the document and a rescan doesn't reuse a stale definition.
  const gradientId = `walk-${run.runId}-${revealKey}`.replace(/[^a-zA-Z0-9-]/g, "-");

  return (
    <g
      opacity={dimmed ? 0.15 : 1}
      onPointerEnter={() => store.hoverAnimal(run.animalId)}
      onPointerLeave={() => store.hoverAnimal(null)}
      style={{ cursor: "crosshair" }}
    >
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1={px(start.x)}
          y1={py(start.y)}
          x2={px(end.x)}
          y2={py(end.y)}
        >
          <stop offset="0%" stopColor={color} stopOpacity={0.25} />
          <stop offset="100%" stopColor={color} stopOpacity={0.95} />
        </linearGradient>
      </defs>

      <motion.polyline
        key={revealKey}
        points={path}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={highlighted ? 1.6 : 0.9}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        <title>{describe(name, points)}</title>
      </motion.polyline>

      {/* Where it started: hollow, so it never competes with the endpoint. */}
      <circle
        cx={px(start.x)}
        cy={py(start.y)}
        r={1.5}
        fill="none"
        stroke={color}
        strokeWidth={0.6}
        opacity={0.7}
        vectorEffect="non-scaling-stroke"
      />
      {/* Where it ended — the same weight the across-session panel gives its
          latest session, for the same reason. */}
      <circle cx={px(end.x)} cy={py(end.y)} r={2.2} fill={color}>
        <title>{describe(name, points)}</title>
      </circle>
    </g>
  );
}

function describe(name: string, points: StrategyPoint[]): string {
  const start = points[0]!;
  const end = points[points.length - 1]!;
  return [
    name,
    `start  ${start.x.toFixed(2)}, ${start.y.toFixed(2)}  (trial ${start.trial})`,
    `end    ${end.x.toFixed(2)}, ${end.y.toFixed(2)}  (trial ${end.trial})`,
    `rolling window, n=${end.n} at the weaker condition`,
  ].join("\n");
}
