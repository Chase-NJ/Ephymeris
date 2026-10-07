import { Compass } from "lucide-react";
import { useMemo } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { PanelTitle } from "@/components/charts/PanelTitle";
import { HowToRead } from "@/components/charts/HowToRead";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import type { AnalyticsSummary, RunSummary } from "@/lib/analytics/types";
import { SIDE_AXES, recentSessions, sideAccuracy } from "@/lib/analytics/view";
import {
  NoPlane,
  PLANE_VIEWBOX,
  PlaneReferences,
  StrategyNote,
  StrategyPanel,
  px,
  py,
} from "./strategyPlane";

/** How many sessions the plane shows — the most recent, cohort-wide. */
export const STRATEGY_SESSIONS = 30;

/**
 * Discrimination versus bias, **across sessions** (`DATA.md#strategy-plane`).
 *
 * One point per animal per session, for the cohort's 30 most recent sessions:
 * x is the fraction correct at the LEFT well, y at the RIGHT well, each pooled
 * over integers across every condition answered there (`sideAccuracy`).
 * `strategyPlane.tsx` owns the reference marks and what each region means,
 * because the within-session panel draws in the same plane and the two must not
 * disagree.
 *
 * **Task-agnostic on purpose.** The plane used to scope itself to one task
 * profile at a time, behind a picker, because two tasks' CONDITIONS are not
 * comparable. Their SIDES are: a well is a physical place, and "how often was
 * this animal right when the answer was left" means the same thing on a shaping
 * day and a four-odor day. Reading each run's own `answerSide` rather than a
 * profile group's axes is what lets every recent session share one frame, and
 * what fixes the orientation — left is always x, whichever condition a profile
 * happened to declare first.
 *
 * **Points, not trails.** Every session of every animal joined into polylines
 * was the clutter: the history ran back to the cohort's first day and the
 * lines crossed into a mat. The window is capped at the recent sessions, older
 * points fade, and the latest is drawn larger, so direction of travel still
 * reads without a line to follow. Hovering an animal lifts its points and dims
 * the rest.
 *
 * **Across-session scope only.** Selecting one session replaces this panel with
 * `SessionStrategy`, rather than rendering both: a point here is a session and
 * a point there is a trial, and nothing in the frame would tell them apart.
 */
export function StrategySpace({
  summary,
  colors,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
}) {
  const plot = useMemo(() => buildPoints(summary), [summary]);

  if (plot.animals.length === 0) {
    return (
      <NoPlane
        hasRuns={summary.runs.length > 0}
        reason={
          summary.runs.length > 0
            ? "no recent run answered at both the left and the right well"
            : null
        }
      />
    );
  }

  return (
    <StrategyPanel>
      <ChartFrame
        icon={Compass}
        title={
          <PanelTitle
            name="Strategy space"
            note={`${
              plot.sessionCount < STRATEGY_SESSIONS
                ? `${plot.sessionCount} session${plot.sessionCount === 1 ? "" : "s"}`
                : `last ${STRATEGY_SESSIONS} sessions`
            } · one point per animal per session`}
          />
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft="0.0"
        xRight="1.0"
        footer={
          <span className="truncate text-static/70">
            ↑ right well · → left well · P(correct), pooled over conditions
          </span>
        }
      >
        <svg
          viewBox={PLANE_VIEWBOX}
          className="w-full"
          preserveAspectRatio="xMidYMid meet"
          role="img"
          aria-label="Left-well against right-well accuracy, one point per animal per recent session"
        >
          <PlaneReferences />
          {/* One component per animal — this is what keeps a hover from
              re-rendering every point in the panel. */}
          {plot.animals.map((animal) => (
            <AnimalPoints
              key={animal.animalId}
              animal={animal}
              color={colors.get(animal.animalId) ?? "var(--color-series-1)"}
              sessionCount={plot.sessionCount}
            />
          ))}
        </svg>
      </ChartFrame>
      {/* A data disclosure, not education — stays outside the fold. */}
      {plot.skipped > 0 && (
        <p className="mt-1 font-mono text-[9px] leading-relaxed text-static/60">
          {plot.skipped} run{plot.skipped === 1 ? "" : "s"} in these sessions had no
          answers at one of the wells, so there is no point to place.
        </p>
      )}
      <HowToRead>
        <StrategyNote axes={SIDE_AXES} />
      </HowToRead>
    </StrategyPanel>
  );
}

interface PlanePoint {
  run: RunSummary;
  x: number;
  y: number;
  /** 0-based position of the run's session within the plotted window. */
  slot: number;
  label: string;
  lowConfidence: boolean;
}

interface AnimalPlot {
  animalId: string;
  name: string;
  points: PlanePoint[];
}

function AnimalPoints({
  animal,
  color,
  sessionCount,
}: {
  animal: AnimalPlot;
  color: string;
  sessionCount: number;
}) {
  const highlighted = useIsHighlighted(animal.animalId);
  const someoneHighlighted = useHasHighlight();
  // Dim the rest only when something is actually highlighted, so the resting
  // state is every animal at equal weight rather than everything faded.
  const dimmed = someoneHighlighted && !highlighted;
  return (
    <g opacity={dimmed ? 0.18 : 1}>
      {animal.points.map((point) => {
        const latest = point.slot === sessionCount - 1;
        return (
          <circle
            key={point.run.runId}
            cx={px(point.x)}
            cy={py(point.y)}
            r={latest ? 2.2 : highlighted ? 1.8 : 1.5}
            fill={point.lowConfidence ? "none" : color}
            stroke={point.lowConfidence ? color : "none"}
            strokeWidth={point.lowConfidence ? 0.5 : 0}
            vectorEffect="non-scaling-stroke"
            opacity={fade(point.slot, sessionCount)}
          >
            <title>{describe(point, animal.name)}</title>
          </circle>
        );
      })}
    </g>
  );
}

function describe(point: PlanePoint, name: string): string {
  const left = sideAccuracy(point.run, "left");
  const right = sideAccuracy(point.run, "right");
  const parts = [
    `${name} · ${point.label}`,
    `left well: ${point.x.toFixed(2)} (n=${left.counted})`,
    `right well: ${point.y.toFixed(2)} (n=${right.counted})`,
  ];
  if (point.lowConfidence) parts.push("too few trials to read firmly");
  return parts.join("\n");
}

function buildPoints(summary: AnalyticsSummary): {
  animals: AnimalPlot[];
  sessionCount: number;
  skipped: number;
} {
  const sessions = recentSessions(summary, STRATEGY_SESSIONS);
  const slotOf = new Map(sessions.map((session, index) => [session.id, index]));
  const labelOf = new Map(
    sessions.map((s) => [s.id, `${s.prefixName} ${s.sessionNumber} · ${s.date}`]),
  );
  const names = new Map(summary.animals.map((animal) => [animal.id, animal.name]));
  const byAnimal = new Map<string, PlanePoint[]>();
  let skipped = 0;
  for (const run of summary.runs) {
    const slot = slotOf.get(run.sessionId);
    if (slot === undefined || run.status !== "ok") continue;
    const x = sideAccuracy(run, "left").p;
    const y = sideAccuracy(run, "right").p;
    // A run that answered nothing at one well has no position on this plane,
    // and one is not invented for it (`DATA.md#edge-cases`).
    if (x === null || y === null) {
      skipped += 1;
      continue;
    }
    const point: PlanePoint = {
      run,
      x,
      y,
      slot,
      label: labelOf.get(run.sessionId) ?? "",
      lowConfidence: run.metrics.some(
        (m) => (m.answerSide === "left" || m.answerSide === "right") && m.lowConfidence,
      ),
    };
    const bucket = byAnimal.get(run.animalId);
    if (bucket) bucket.push(point);
    else byAnimal.set(run.animalId, [point]);
  }
  return {
    animals: [...byAnimal].map(([animalId, points]) => ({
      animalId,
      name: names.get(animalId) ?? animalId,
      // Oldest first, so the newest points paint on top.
      points: points.sort((a, b) => a.slot - b.slot),
    })),
    sessionCount: sessions.length,
    skipped,
  };
}

/** Older sessions fade, so the direction of travel is legible without a line. */
function fade(slot: number, total: number): number {
  if (total <= 1) return 1;
  return 0.3 + 0.7 * (slot / (total - 1));
}
