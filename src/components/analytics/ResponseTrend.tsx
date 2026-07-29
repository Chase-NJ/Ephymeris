import { useMemo, type ReactNode } from "react";

import { ChartDots, type Dot } from "@/components/charts/ChartDots";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { DrawOn } from "@/components/charts/DrawOn";
import { HIGHLIGHT_DRAW, useRevealOnView } from "@/components/charts/reveal";
import {
  UnitChart,
  ribbon,
  segmentsWithGaps,
  unitX,
  unitY,
  type Point,
} from "@/components/charts/UnitChart";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import type { AnalyticsSummary, ProfileGroup } from "@/lib/analytics/types";
import {
  RESPONSE_ACCURACY,
  accuracyBand,
  animalAccuracyLines,
  poolOutcomes,
  runsInProfile,
  sessionOutcomePoints,
  sessionSlot,
  type AnimalAccuracyPoint,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * Cohort mean **response** accuracy across sessions (`analytics.md` §6.5).
 *
 * The same question as the rewarded-accuracy panel above, asked of the
 * *choice* instead of the *drop*: a trial where the animal answered the
 * correct well counts here whether or not it held long enough to earn fluid.
 * `derive.py` calls this figure `pSide`, and the tally it comes from
 * (`analytics.md` §3.8) exists precisely to keep the two apart — the declared
 * live metrics are reward-unconditional, so scoring them against fluid
 * delivery would quietly answer neither question.
 *
 * **Read it against the panel above, not on its own.** Same x slots, same
 * denominator, same hollow-mark rule, and this line is always the higher of
 * the two — so the vertical gap between them *is* the consummatory hold
 * failure rate. An animal learning the discrimination while still fumbling
 * the hold shows as this line climbing away from the rewarded one; a cohort
 * that has learned both shows the two converging. Either reading is
 * unavailable from a single panel, which is why there are two.
 *
 * Drawn in the same accent as the rewarded line on purpose. They are the same
 * kind of figure and the comparison is vertical — giving one its own colour
 * would imply they measure different things rather than the same thing at two
 * strictnesses.
 */

/** Below this many administered trials the point is drawn hollow (§3.5). */
const THIN = 30;

/** The viewBox's y extent — a coordinate space, not a size. */
const HEIGHT = 54;

/** Matches the rewarded panel exactly, so the pair reads as one stacked band
 *  and a session sits directly above itself. */
const PLOT_PX = 132;

/** Seconds the pooled line takes to lay its history down (§2.7). */
const DRAW = 0.9;

export function ResponseTrend(props: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen (§2.7). */
  revealKey: string;
}) {
  return <ResponseBody key={props.revealKey} {...props} />;
}

function ResponseBody({
  summary,
  profile,
  colors,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
}) {
  const { ref, seen } = useRevealOnView();
  const points = useMemo(() => sessionOutcomePoints(summary, profile), [summary, profile]);
  const animalLines = useMemo(
    () => animalAccuracyLines(summary, points, RESPONSE_ACCURACY, THIN),
    [summary, points],
  );

  // Silent rather than explanatory when there is nothing to draw: the panel
  // above says the same thing about the same missing vocabulary, and saying it
  // twice reads as two faults rather than one.
  if (points.length === 0) return null;

  // A session that administered nothing holds its slot as a gap, so the line
  // bridges dashed rather than interpolating through it (§3.6).
  const line: Array<Point | null> = points.map((point, index) =>
    point.outcomes.pSide === null
      ? null
      : { x: sessionSlot(index, points.length), y: point.outcomes.pSide },
  );
  const segments = segmentsWithGaps(line);
  const bands = accuracyBand(points, RESPONSE_ACCURACY);
  const dots: Dot[] = points.flatMap((point, index) =>
    point.outcomes.pSide === null
      ? []
      : [
          {
            x: sessionSlot(index, points.length),
            y: point.outcomes.pSide,
            hollow: point.outcomes.administered < THIN,
          },
        ],
  );

  const overall = poolOutcomes(runsInProfile(summary.runs, profile));

  return (
    <Panel>
      <div ref={ref}>
        <ChartFrame
          title={
            <span>
              Response accuracy
              <span className="ml-2 text-static/70">
                correct well answered · pooled across the cohort
              </span>
            </span>
          }
          yTop="1.0"
          yBottom="0.0"
          xLeft={points[0]!.session.date}
          xRight={points[points.length - 1]!.session.date}
          footer={
            <span className="truncate text-static/70">
              {points.length} session{points.length === 1 ? "" : "s"}
              {overall.pSide !== null &&
                ` · ${pct(overall.pSide)} of ${overall.administered} administered chose the correct well`}
              {overall.pSide !== null &&
                overall.pRewarded !== null &&
                ` · ${pct(overall.pSide - overall.pRewarded)} lost to the hold`}
              {" · band = 95% Wilson · hollow = <"}
              {THIN} administered
            </span>
          }
        >
          <div className="relative" style={{ height: PLOT_PX }}>
            <PooledLayer>
              <UnitChart
                height={HEIGHT}
                className="h-full w-full"
                references={[{ y: 0.5 }]}
              >
                <DrawOn viewBox={[0, 0, 100, HEIGHT]} seen={seen} duration={DRAW}>
                  {bands.map((band, index) => (
                    <polygon
                      key={`band-${index}`}
                      points={ribbon(band, HEIGHT)}
                      fill="var(--color-pulsar)"
                      fillOpacity={0.14}
                      stroke="none"
                    />
                  ))}
                  {segments.map((segment, index) => (
                    <polyline
                      key={`seg-${index}`}
                      points={segment.points
                        .map((p) => `${unitX(p.x)},${unitY(p.y, HEIGHT)}`)
                        .join(" ")}
                      fill="none"
                      stroke="var(--color-pulsar)"
                      strokeWidth={1.6}
                      strokeLinejoin="round"
                      strokeDasharray={segment.dashed ? "2 2" : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </DrawOn>
              </UnitChart>
              <ChartDots
                dots={dots}
                color="var(--color-pulsar)"
                seen={seen}
                spread={DRAW}
              />
            </PooledLayer>
            {animalLines.map((entry) => (
              <AnimalResponseLine
                key={entry.animalId}
                animalId={entry.animalId}
                color={colors.get(entry.animalId) ?? "var(--color-series-1)"}
                points={entry.points}
              />
            ))}
            {/* Invisible per-session hit targets, one column each, so the
                numbers behind a point are a hover away. */}
            <svg
              viewBox={`0 0 100 ${HEIGHT}`}
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full"
              aria-hidden
            >
              {points.map((point, index) => {
                const half = points.length > 1 ? 100 / (points.length - 1) / 2 : 50;
                const centre = sessionSlot(index, points.length) * 100;
                const left = Math.max(0, centre - half);
                return (
                  <rect
                    key={point.session.id}
                    x={left}
                    y={0}
                    width={Math.min(100, centre + half) - left}
                    height={HEIGHT}
                    fill="transparent"
                  >
                    <title>{describePoint(point)}</title>
                  </rect>
                );
              })}
            </svg>
          </div>
        </ChartFrame>
      </div>
    </Panel>
  );
}

/**
 * Fades the pooled figure back while any animal is highlighted, so the
 * overlaid per-animal line reads against it rather than through it (§2.1).
 */
function PooledLayer({ children }: { children: ReactNode }) {
  const dimmed = useHasHighlight();
  return (
    <div className="relative h-full" style={{ opacity: dimmed ? 0.25 : 1 }}>
      {children}
    </div>
  );
}

/**
 * One animal's own response line, visible only while that animal is
 * highlighted, laid down in session order at the slower highlight pace (§2.7).
 */
function AnimalResponseLine({
  animalId,
  color,
  points,
}: {
  animalId: string;
  color: string;
  points: Array<AnimalAccuracyPoint | null>;
}) {
  const highlighted = useIsHighlighted(animalId);
  if (!highlighted) return null;

  const segments = segmentsWithGaps(points);
  const dots: Dot[] = points.flatMap((point) =>
    point === null ? [] : [{ x: point.x, y: point.y, hollow: point.thin }],
  );
  return (
    <>
      <svg
        viewBox={`0 0 100 ${HEIGHT}`}
        preserveAspectRatio="none"
        className="pointer-events-none absolute inset-0 h-full w-full"
        aria-hidden
      >
        <DrawOn viewBox={[0, 0, 100, HEIGHT]} duration={HIGHLIGHT_DRAW}>
          {segments.map((segment, index) =>
            segment.points.length < 2 ? null : (
              <polyline
                key={index}
                points={segment.points
                  .map((p) => `${unitX(p.x)},${unitY(p.y, HEIGHT)}`)
                  .join(" ")}
                fill="none"
                stroke={color}
                strokeWidth={1.6}
                strokeLinejoin="round"
                strokeDasharray={segment.dashed ? "2 2" : undefined}
                vectorEffect="non-scaling-stroke"
              />
            ),
          )}
        </DrawOn>
      </svg>
      <ChartDots dots={dots} color={color} spread={HIGHLIGHT_DRAW} />
    </>
  );
}

/** The hover title: which session, and the numbers behind its point. */
function describePoint(point: SessionOutcomePoint): string {
  const { session, outcomes } = point;
  const head = `${session.prefixName}_${session.sessionNumber} · ${session.date}`;
  if (outcomes.pSide === null) {
    return `${head}\nno administered trials — ${outcomes.aborted} aborted`;
  }
  const parts = [
    `${pct(outcomes.pSide)} correct well of ${outcomes.administered} administered`,
  ];
  if (outcomes.sideLow !== null && outcomes.sideHigh !== null) {
    parts.push(`95% band ${pct(outcomes.sideLow)}–${pct(outcomes.sideHigh)}`);
  }
  // The split behind the number: how many of those correct choices earned
  // fluid and how many lost it at the hold. This is the reason the panel
  // exists, so it belongs in the tooltip and not only in the eye's comparison
  // with the panel above.
  parts.push(`${outcomes.rewarded} rewarded · ${outcomes.holdFailed} no hold`);
  if (outcomes.administered < THIN) {
    parts.push(`fewer than ${THIN} administered — read loosely`);
  }
  return `${head}\n${parts.join(" · ")}`;
}

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function Panel({ children }: { children: ReactNode }) {
  return <div className="surface rounded-md p-4">{children}</div>;
}
