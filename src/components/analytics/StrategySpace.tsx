import { motion } from "framer-motion";
import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { HIGHLIGHT_DRAW } from "@/components/charts/reveal";
import { edgesWithGaps, segmentsWithGaps, type Point } from "@/components/charts/UnitChart";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import type { AnalyticsSummary, ProfileGroup, RunSummary } from "@/lib/analytics/types";
import { chronological, declaredMetrics, runsInProfile } from "@/lib/analytics/view";
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
 * Discrimination versus bias, **across sessions** (`data.md` §11.1).
 *
 * Both axes are "fraction correct for this condition", plotted **as authored**
 * — x is `liveMetrics[0]`, y is `liveMetrics[1]`. `strategyPlane.tsx` owns the
 * reference marks and what each region means, because the within-session panel
 * (§4.4) draws in the same plane and the two must not disagree.
 *
 * The textbook ROC framing was rejected because it needs to know that one
 * metric's `successCode` and the other's `alternateCode` are the same physical
 * port, and a Task Profile declares no such relationship (§4.2).
 *
 * Each animal's sessions connect chronologically with opacity ramping oldest
 * to newest, so the trail reads as a direction of travel: off the bias
 * diagonal and toward the corner, over weeks.
 *
 * **Across-session scope only.** Selecting one session replaces this panel with
 * `SessionStrategy`, rather than rendering both: a line here spans weeks and a
 * line there spans an hour, and nothing in the frame would tell them apart.
 */
export function StrategySpace({
  summary,
  profile,
  colors,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
}) {
  const trails = useMemo(() => buildTrails(summary, profile), [summary, profile]);
  const axes = declaredMetrics(profile);

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

  return (
    <StrategyPanel>
      <ChartFrame
        title={
          <span>
            Strategy space
            <span className="ml-2 text-static/70">one point per session</span>
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
          aria-label="Discrimination against side bias, per animal over sessions"
        >
          <PlaneReferences />
          {/* One component per animal — this is what keeps a hover from
              re-rendering every trail in the panel (§2.1). */}
          {trails.map((trail) => (
            <AnimalTrail
              key={trail.animalId}
              trail={trail}
              color={colors.get(trail.animalId) ?? "var(--color-series-1)"}
              sessions={summary.sessions}
            />
          ))}
        </svg>
      </ChartFrame>
      <StrategyNote xMetric={xMetric!} yMetric={yMetric!} />
    </StrategyPanel>
  );
}

interface Trail {
  animalId: string;
  name: string;
  runs: RunSummary[];
  points: Array<Point | null>;
}

function AnimalTrail({
  trail,
  color,
  sessions,
}: {
  trail: Trail;
  color: string;
  sessions: AnalyticsSummary["sessions"];
}) {
  const highlighted = useIsHighlighted(trail.animalId);
  const someoneHighlighted = useHasHighlight();
  // Dim the rest only when something is actually highlighted, so the resting
  // state is every animal at equal weight rather than everything faded.
  const dimmed = someoneHighlighted && !highlighted;

  const total = trail.points.length;
  const nodes = trail.points.flatMap((point, index) =>
    point === null ? [] : [{ point, index, run: trail.runs[index]! }],
  );

  return (
    // Keyed on the highlight so picking this animal remounts the trail and
    // replays the walk — hovering is the gesture that asks for it.
    <g key={highlighted ? "walk" : "rest"} opacity={dimmed ? 0.18 : 1}>
      {highlighted
        ? edgesWithGaps(trail.points).map((edge) => (
            <motion.polyline
              key={edge.index}
              points={`${px(edge.from.x)},${py(edge.from.y)} ${px(edge.to.x)},${py(edge.to.y)}`}
              fill="none"
              stroke={color}
              strokeWidth={1.6}
              strokeLinejoin="round"
              strokeDasharray={edge.dashed ? "2 2" : undefined}
              vectorEffect="non-scaling-stroke"
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.65 }}
              transition={{ duration: STEP, delay: walkDelay(edge.index, total) }}
            />
          ))
        : segmentsWithGaps(trail.points).map((segment, index) => (
            <polyline
              key={index}
              points={segment.points.map((p) => `${px(p.x)},${py(p.y)}`).join(" ")}
              fill="none"
              stroke={color}
              strokeWidth={0.9}
              strokeLinejoin="round"
              strokeDasharray={segment.dashed ? "2 2" : undefined}
              opacity={0.65}
              vectorEffect="non-scaling-stroke"
            />
          ))}
      {nodes.map(({ point, index, run }) => {
        const isLatest = index === total - 1;
        const lowConfidence = run.metrics.some((metric) => metric.lowConfidence);
        const shared = {
          cx: px(point.x),
          cy: py(point.y),
          r: isLatest ? 2.2 : 1.6,
          fill: lowConfidence ? "none" : color,
          stroke: lowConfidence ? color : "none",
          strokeWidth: lowConfidence ? 0.5 : 0,
          vectorEffect: "non-scaling-stroke" as const,
        };
        const settled = fade(index, total, 1);
        const title = <title>{describe(run, trail, sessionLabel(run, sessions))}</title>;
        return highlighted ? (
          <motion.circle
            key={run.runId}
            {...shared}
            initial={{ opacity: 0 }}
            animate={{ opacity: settled }}
            transition={{ duration: STEP, delay: walkDelay(index, total) }}
          >
            {title}
          </motion.circle>
        ) : (
          <circle key={run.runId} {...shared} opacity={settled}>
            {title}
          </circle>
        );
      })}
    </g>
  );
}

/** How long one hop takes to arrive, independent of how many there are. */
const STEP = 0.18;

/**
 * When the walk reaches a node, in seconds.
 *
 * Proportional to the node's **session ordinal** rather than to its position
 * among the points that exist, so a trail with sessions missing from the
 * middle pauses over the gap instead of closing it up — the same reason those
 * gaps are drawn dashed rather than interpolated. The last node lands at
 * `HIGHLIGHT_DRAW`, so every animal's walk takes the same time whatever its
 * length, and the trails read as comparable histories rather than as a race.
 */
function walkDelay(index: number, total: number): number {
  if (total <= 1) return 0;
  return (index / (total - 1)) * HIGHLIGHT_DRAW;
}

function describe(run: RunSummary, trail: Trail, label: string): string {
  const parts = run.metrics.map(
    (metric) =>
      `${metric.label}: ${
        metric.pSession === null ? "—" : metric.pSession.toFixed(2)
      } (n=${metric.counted})`,
  );
  if (run.metrics.some((m) => m.lowConfidence)) {
    parts.push("too few trials to read firmly");
  }
  return [`${trail.name} · ${label}`, ...parts].join("\n");
}

function buildTrails(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
): Trail[] {
  const axes = declaredMetrics(profile);
  if (!profile || axes.length !== 2) return [];
  const [xId, yId] = axes.map((metric) => metric.id);

  // Only runs sharing this profile's hash — a GRGL point and an EZ-variant
  // point on shared axes is a category error, even when both declare two
  // metrics (§4.3).
  const eligible = runsInProfile(summary.runs, profile);
  const byAnimal = new Map<string, RunSummary[]>();
  for (const run of eligible) {
    const bucket = byAnimal.get(run.animalId);
    if (bucket) bucket.push(run);
    else byAnimal.set(run.animalId, [run]);
  }

  const names = new Map(summary.animals.map((animal) => [animal.id, animal.name]));
  return [...byAnimal].map(([animalId, runs]) => {
    const ordered = chronological(runs, summary.sessions);
    return {
      animalId,
      name: names.get(animalId) ?? animalId,
      runs: ordered,
      points: ordered.map((run) => {
        const x = run.metrics.find((metric) => metric.id === xId)?.pSession;
        const y = run.metrics.find((metric) => metric.id === yId)?.pSession;
        // A session that scored nothing produces no point at all, and the
        // trail bridges the gap dashed rather than interpolating through
        // something that never happened (§3.6).
        return x === null || x === undefined || y === null || y === undefined
          ? null
          : { x, y };
      }),
    };
  });
}

function sessionLabel(run: RunSummary, sessions: AnalyticsSummary["sessions"]): string {
  const session = sessions.find((entry) => entry.id === run.sessionId);
  return session ? `${session.prefixName} ${session.sessionNumber} · ${session.date}` : "";
}

/** Older sessions fade, so the direction of travel is legible. */
function fade(index: number, total: number, ceiling: number): number {
  if (total <= 1) return ceiling;
  return (0.4 + 0.6 * (index / (total - 1))) * ceiling;
}
