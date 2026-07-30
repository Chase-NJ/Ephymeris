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
  REWARDED_ACCURACY,
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
 * Cohort mean **rewarded** accuracy across sessions (`data.md` §9.8).
 *
 * Deliberately a separate panel from the learning curves rather than another
 * line on them: those plot the declared metrics, which are
 * reward-*unconditional* — an animal that reaches the correct well and
 * releases before the hold still scores a hit there. This is the stricter
 * question, "how often did the cohort actually earn water", and the two
 * belong on separate axes or neither can be read honestly. The panel says
 * `fluid delivered` in the frame for exactly that reason.
 *
 * Pooled is still the resting state, but the shared highlight reaches here
 * too (§2.1): hovering an animal fades the cohort figure back and overlays
 * that animal's own rewarded line, in its identity colour — the same
 * question, asked of one animal.
 *
 * Across sessions only. Within one session there is a single pooled figure,
 * not a trend, and the session summary shows that per animal instead.
 *
 * The x slots come from `sessionOutcomePoints`, shared with the effort and
 * outcome-mix panels below, so one session sits above itself in all three. A
 * session that administered nothing keeps its slot and bridges dashed (§3.6).
 */

/** Below this many administered trials the point is drawn hollow (§3.5). */
const THIN = 30;

/** The viewBox's y extent. Only a coordinate space — `PLOT_PX` is what the
 *  chart actually occupies. */
const HEIGHT = 54;

/**
 * The plot's height in CSS pixels, fixed rather than left to the SVG's
 * intrinsic aspect ratio: this panel spans the full column, and an
 * aspect-driven height would make it ~500px tall — a trend line lost in a
 * field of empty plot. Fixed here, the panel keeps one shape at every window
 * width.
 */
const PLOT_PX = 132;

/** Total seconds the pooled line takes to lay its history down (§2.7). The
 *  marks key their delay off it, so a point surfaces exactly as the draw
 *  reaches its session — which holds because the wipe advances uniformly in x
 *  (see `DrawOn`). */
const DRAW = 0.9;

export function RewardedTrend(props: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen (§2.7). */
  revealKey: string;
}) {
  return <TrendBody key={props.revealKey} {...props} />;
}

function TrendBody({
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
    () => animalAccuracyLines(summary, points, REWARDED_ACCURACY, THIN),
    [summary, points],
  );

  if (points.length === 0) {
    return (
      <Panel>
        <p className="text-[12px] leading-relaxed text-static">
          No rewarded-trial data for this task. A task only reports it if its
          profile declares the reward vocabulary (§3.8).
        </p>
      </Panel>
    );
  }

  // A session that administered nothing holds its slot as a gap, so the line
  // bridges dashed rather than interpolating through it (§3.6).
  const line: Array<Point | null> = points.map((point, index) =>
    point.outcomes.pRewarded === null
      ? null
      : { x: sessionSlot(index, points.length), y: point.outcomes.pRewarded },
  );
  const segments = segmentsWithGaps(line);
  const bands = accuracyBand(points, REWARDED_ACCURACY);
  const dots: Dot[] = points.flatMap((point, index) =>
    point.outcomes.pRewarded === null
      ? []
      : [
          {
            x: sessionSlot(index, points.length),
            y: point.outcomes.pRewarded,
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
              Rewarded accuracy
              <span className="ml-2 text-static/70">
                fluid delivered · pooled across the cohort
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
              {overall.pRewarded !== null &&
                ` · ${pct(overall.pRewarded)} of ${overall.administered} administered earned fluid`}
              {" · band = 95% Wilson · hollow = <"}
              {THIN} administered
            </span>
          }
        >
          <div className="relative" style={{ height: PLOT_PX }}>
            {/* Band, line and marks share one reveal: the band settles in as
                the line lays the cohort's history down in order, and each
                mark surfaces as the draw reaches its session. All fade back
                together while an animal is highlighted, so the overlaid
                per-animal line reads against them, not through them. */}
            <PooledLayer>
              <UnitChart
                height={HEIGHT}
                className="h-full w-full"
                references={[{ y: 0.5 }]}
              >
                {/* Band, solid runs and dashed bridges all ride one wipe, so
                    the ribbon arrives with the curve it belongs to rather than
                    ahead of it — and a bridge reveals on the same clock as
                    everything else instead of needing its own fade. */}
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
              <AnimalRewardedLine
                key={entry.animalId}
                animalId={entry.animalId}
                color={colors.get(entry.animalId) ?? "var(--color-series-1)"}
                points={entry.points}
              />
            ))}
            {/* Invisible per-session hit targets, one column each, so the
                numbers behind a point are a hover away. Native titles rather
                than a styled tooltip — the same idiom as the heatmap cells. */}
            <svg
              viewBox={`0 0 100 ${HEIGHT}`}
              preserveAspectRatio="none"
              className="absolute inset-0 h-full w-full"
              aria-hidden
            >
              {points.map((point, index) => {
                const half =
                  points.length > 1 ? 100 / (points.length - 1) / 2 : 50;
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
 * Fades the pooled figure back while any animal is highlighted. A wrapper
 * component rather than a hook in the panel, so a hover re-renders this
 * `<div>` and the overlay layers — never the chart or the reveal animation
 * behind them (§2.1).
 */
function PooledLayer({ children }: { children: ReactNode }) {
  const dimmed = useHasHighlight();
  // `h-full`, not auto: the chart inside sizes itself with `h-full` too, and a
  // percentage height against an auto-height parent resolves to nothing — the
  // SVG would fall back to its viewBox aspect ratio and stand ~490px tall,
  // overflowing this panel onto the ones below it.
  return (
    <div className="relative h-full" style={{ opacity: dimmed ? 0.25 : 1 }}>
      {children}
    </div>
  );
}

/**
 * One animal's own rewarded line, visible only while that animal is
 * highlighted. Its x positions are the pooled line's session slots, so the
 * two are directly comparable; sessions the animal sat out bridge dashed.
 *
 * Its own overlay pair rather than a `<g>` in a shared one: at most one animal
 * is highlighted at a time, and this keeps the line's SVG and its HTML dots
 * mounting and unmounting together.
 *
 * It lays itself down in session order on every hover — mounting *is* the
 * gesture here, so no key is needed to replay it — and at the slower highlight
 * pace, because following one animal's history is the thing the reader just
 * asked to do.
 */
function AnimalRewardedLine({
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
  if (outcomes.pRewarded === null) {
    return `${head}\nno administered trials — ${outcomes.aborted} aborted`;
  }
  const parts = [
    `${pct(outcomes.pRewarded)} rewarded of ${outcomes.administered} administered`,
  ];
  if (outcomes.rewardedLow !== null && outcomes.rewardedHigh !== null) {
    parts.push(`95% band ${pct(outcomes.rewardedLow)}–${pct(outcomes.rewardedHigh)}`);
  }
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
