import { Route } from "lucide-react";
import { motion } from "framer-motion";
import { useMemo, useState } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { HowToRead } from "@/components/charts/HowToRead";
import { useHasHighlight, useIsHighlighted, useAnalyticsStore } from "@/lib/analytics/context";
import type {
  AnalyticsSummary,
  RunSeries,
  RunSummary,
  StrategyPoint,
} from "@/lib/analytics/types";
import { strategyProfiles, taskLabels } from "@/lib/analytics/view";
import { ProfilePicker } from "./ProfilePicker";
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
 * The strategy plane, walked **within one session** (`data.md` §11.1).
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
  colors,
  runs,
  series,
  revealKey,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  /** Every run in the selected session, whatever task (`session.ts`). */
  runs: RunSummary[];
  series: RunSeries[];
  revealKey: string;
}) {
  const names = new Map(summary.animals.map((animal) => [animal.id, animal.name]));
  const labels = useMemo(() => taskLabels(summary), [summary]);

  /*
   * Self-scoped, like the across-session plane — but over the profiles THIS
   * SESSION actually ran, ordered by how many of its runs each holds. A session
   * rarely mixes tasks; when it does, the picker says which one the plane is
   * showing and the note below counts the runs it leaves out.
   *
   * Ordered by presence in the session rather than by the cohort's totals: the
   * question here is about this session, and the cohort's most-run task may not
   * be in it at all.
   */
  const profiles = useMemo(() => {
    const here = new Set(runs.map((run) => run.profileHash));
    return strategyProfiles(summary)
      .filter((entry) => here.has(entry.group.hash))
      .sort(
        (a, b) =>
          runs.filter((run) => run.profileHash === b.group.hash).length -
          runs.filter((run) => run.profileHash === a.group.hash).length,
      );
  }, [summary, runs]);
  const plottable = profiles.filter((entry) => entry.axes !== null);
  const [chosen, setChosen] = useState<string | null>(null);
  const selected =
    plottable.find((entry) => entry.group.hash === chosen) ?? plottable[0] ?? null;
  const profile = selected?.group ?? null;
  const axes = selected?.axes ?? null;

  if (!profile || !axes) {
    return (
      <NoPlane hasRuns={runs.length > 0} reason={profiles[0]?.reason ?? null} />
    );
  }

  const planeRuns = runs.filter((run) => run.profileHash === profile.hash);
  const elsewhere = runs.length - planeRuns.length;
  const walks = planeRuns
    .map((run) => ({
      run,
      points: series.find((entry) => entry.runId === run.runId)?.trail ?? [],
    }))
    .filter((walk) => walk.points.length > 0);

  return (
    <StrategyPanel>
      <ChartFrame
        icon={Route}
        title={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>
              Strategy within this session
              <span className="ml-2 text-static/70">one point per trial</span>
            </span>
            {profiles.length > 1 ? (
              <ProfilePicker
                profiles={profiles}
                value={profile.hash}
                onChange={setChosen}
                labels={labels}
              />
            ) : (
              <span className="font-mono text-[9px] text-static/70">
                {labels.get(profile.hash) ?? profile.taskName}
              </span>
            )}
          </span>
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft="0.0"
        xRight="1.0"
        footer={
          <span
            className="truncate text-static/70"
            title={`↑ ${axes.y.conditions.join(" · ")}\n→ ${axes.x.conditions.join(" · ")}`}
          >
            ↑ {axes.y.label} · → {axes.x.label} · P(correct)
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
      {/* A data disclosure, not education — stays outside the fold. */}
      {elsewhere > 0 && (
        <p className="mt-1 font-mono text-[9px] leading-relaxed text-static/60">
          {elsewhere} run{elsewhere === 1 ? "" : "s"} on other tasks in this
          session have no plane here — the session summary below carries them.
        </p>
      )}

      <HowToRead>
        <StrategyNote axes={axes} />
        <p className="mt-1">
          Hollow marker is where the animal started, filled is where it ended;
          the path fades in along the way. Position is the rolling window, so
          it is the strategy running at that moment rather than the session
          average.
        </p>
      </HowToRead>
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

      {/* Fades in rather than drawing on. `pathLength` is unusable with
          `vector-effect="non-scaling-stroke"` on an upscaled chart — it
          *finishes* holding a dash covering ~28% of this plane's walk, so the
          trail settled as disconnected chunks (see `DrawOn`). The two fixes
          available elsewhere are both closed here: a left-to-right wipe would
          assert a chronology a 2D walk doesn't have, and a per-segment reveal
          is the hundred-elements-per-animal cost this component exists to
          avoid. Nothing is lost — the gradient already carries the direction
          of travel, which is what the draw-on was there to say. */}
      <motion.polyline
        key={revealKey}
        points={path}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={highlighted ? 1.6 : 0.9}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
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
