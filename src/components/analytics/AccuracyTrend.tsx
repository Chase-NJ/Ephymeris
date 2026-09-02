import { Target } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import { ChartDots, type Dot } from "@/components/charts/ChartDots";
import { ChartFrame } from "@/components/charts/ChartFrame";
import { DrawOn } from "@/components/charts/DrawOn";
import { HowToRead } from "@/components/charts/HowToRead";
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
import type { AnalyticsSummary } from "@/lib/analytics/types";
import {
  OUTCOME_STYLE,
  REWARDED_ACCURACY,
  RESPONSE_ACCURACY,
  accuracyBand,
  animalAccuracyLines,
  describeTaskMix,
  poolOutcomes,
  sessionOutcomePoints,
  sessionSlot,
  taskChanges,
  taskLabels,
  type AnimalAccuracyPoint,
  type SessionOutcomePoint,
} from "@/lib/analytics/view";

/**
 * Cohort accuracy across sessions — **both strictnesses on one plot**
 * (`data.md` §11.5).
 *
 * The two figures are the same question asked of the *choice* and of the
 * *drop*: response accuracy counts a trial where the animal answered the
 * correct well whether or not it held long enough to earn fluid; rewarded
 * accuracy counts only the earned drop. They used to be two stacked panels
 * read by eye across a page seam; on one plot the reading is direct — the
 * response line is always the higher of the pair, and **the shaded gap
 * between them *is* the consummatory hold-failure rate**, filled in the same
 * colour the session cards give a hold failure so the behaviour keeps its
 * colour everywhere it appears.
 *
 * Line colours come from the summary's own vocabulary, not fresh ones:
 * rewarded is `OUTCOME_STYLE.rewarded` and response is Starlight — exactly
 * the pair the session summary header prints those two figures in.
 *
 * Pooled across **every task** (§10); the task strip above shares these x
 * slots and each dashed rule here marks where the dominant task changed.
 * Hovering an animal fades the cohort figure back and overlays that animal's
 * own pair of lines.
 */

/** Below this many administered trials the point is drawn hollow (§3.5). */
const THIN = 30;

/** The viewBox's y extent — a coordinate space, not a size. */
const HEIGHT = 54;

/** Taller than the old stacked pair's individual plots: this is now the
 *  page's headline figure and it carries two lines and a band. */
const PLOT_PX = 172;

/** Seconds the pooled figures take to lay their history down (§2.7). */
const DRAW = 0.9;

const RESPONSE_COLOR = "var(--color-starlight)";
const REWARDED_COLOR = OUTCOME_STYLE.rewarded.fill;
const GAP_COLOR = OUTCOME_STYLE.holdFailed.fill;

export function AccuracyTrend(props: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  /** Changes when the data does — remounts the body, so the reveal re-arms
   *  and again waits to be seen (§2.7). */
  revealKey: string;
}) {
  return <TrendBody key={props.revealKey} {...props} />;
}

function TrendBody({
  summary,
  colors,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
}) {
  const { ref, seen } = useRevealOnView();
  const points = useMemo(() => sessionOutcomePoints(summary), [summary]);
  const labels = useMemo(() => taskLabels(summary), [summary]);
  const animalLines = useMemo(
    () => ({
      response: animalAccuracyLines(summary, points, RESPONSE_ACCURACY, THIN),
      rewarded: animalAccuracyLines(summary, points, REWARDED_ACCURACY, THIN),
    }),
    [summary, points],
  );

  if (points.length === 0) {
    return (
      <Panel>
        <p className="text-[12px] leading-relaxed text-static">
          No accuracy data yet. A run only reports it if its task&rsquo;s
          profile declares the reward vocabulary (§3.8).
        </p>
      </Panel>
    );
  }

  const rewardedLine: Array<Point | null> = points.map((point, index) =>
    point.outcomes.pRewarded === null
      ? null
      : { x: sessionSlot(index, points.length), y: point.outcomes.pRewarded },
  );
  const responseLine: Array<Point | null> = points.map((point, index) =>
    point.outcomes.pSide === null
      ? null
      : { x: sessionSlot(index, points.length), y: point.outcomes.pSide },
  );
  const rewardedDots: Dot[] = points.flatMap((point, index) =>
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
  const responseDots: Dot[] = points.flatMap((point, index) =>
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
  // The band between the two lines — the hold-failure rate, drawn as area so
  // it reads as a quantity rather than as a distance to be estimated. Split
  // wherever either figure is missing, like the lines themselves (§3.6).
  const gapBands = holdGapBands(points);

  const overall = poolOutcomes(summary.runs);
  const changes = taskChanges(points).map((change) => ({
    from: { x: change.x, y: 0 },
    to: { x: change.x, y: 1 },
  }));

  return (
    <Panel>
      <div ref={ref}>
        <ChartFrame
          icon={Target}
          title={
            <span>
              Accuracy
              <span className="ml-2 text-static/70">
                response and rewarded · pooled across the cohort, every task
              </span>
            </span>
          }
          yTop="1.0"
          yBottom="0.0"
          xLeft={points[0]!.session.date}
          xRight={points[points.length - 1]!.session.date}
        >
          <div className="relative" style={{ height: PLOT_PX }}>
            <PooledLayer>
              <UnitChart
                height={HEIGHT}
                className="h-full w-full"
                references={[{ y: 0.5 }, ...changes]}
              >
                <DrawOn viewBox={[0, 0, 100, HEIGHT]} seen={seen} duration={DRAW}>
                  {/* The hold gap first, then the confidence ribbons, then the
                      lines — SVG paints in order and the area belongs behind
                      everything that outlines it. */}
                  {gapBands.map((band, index) => (
                    <polygon
                      key={`gap-${index}`}
                      points={ribbon(band, HEIGHT)}
                      fill={GAP_COLOR}
                      fillOpacity={0.16}
                      stroke="none"
                    />
                  ))}
                  {accuracyBand(points, RESPONSE_ACCURACY).map((band, index) => (
                    <polygon
                      key={`rband-${index}`}
                      points={ribbon(band, HEIGHT)}
                      fill={RESPONSE_COLOR}
                      fillOpacity={0.07}
                      stroke="none"
                    />
                  ))}
                  {accuracyBand(points, REWARDED_ACCURACY).map((band, index) => (
                    <polygon
                      key={`wband-${index}`}
                      points={ribbon(band, HEIGHT)}
                      fill={REWARDED_COLOR}
                      fillOpacity={0.09}
                      stroke="none"
                    />
                  ))}
                  {segmentsWithGaps(responseLine).map((segment, index) => (
                    <polyline
                      key={`resp-${index}`}
                      points={segment.points
                        .map((p) => `${unitX(p.x)},${unitY(p.y, HEIGHT)}`)
                        .join(" ")}
                      fill="none"
                      stroke={RESPONSE_COLOR}
                      strokeWidth={1.4}
                      strokeLinejoin="round"
                      strokeDasharray={segment.dashed ? "2 2" : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                  {segmentsWithGaps(rewardedLine).map((segment, index) => (
                    <polyline
                      key={`rew-${index}`}
                      points={segment.points
                        .map((p) => `${unitX(p.x)},${unitY(p.y, HEIGHT)}`)
                        .join(" ")}
                      fill="none"
                      stroke={REWARDED_COLOR}
                      strokeWidth={1.6}
                      strokeLinejoin="round"
                      strokeDasharray={segment.dashed ? "2 2" : undefined}
                      vectorEffect="non-scaling-stroke"
                    />
                  ))}
                </DrawOn>
              </UnitChart>
              <ChartDots dots={responseDots} color={RESPONSE_COLOR} seen={seen} spread={DRAW} />
              <ChartDots dots={rewardedDots} color={REWARDED_COLOR} seen={seen} spread={DRAW} />
            </PooledLayer>
            {animalLines.response.map((entry) => (
              <AnimalPairLines
                key={entry.animalId}
                animalId={entry.animalId}
                color={colors.get(entry.animalId) ?? "var(--color-series-1)"}
                response={entry.points}
                rewarded={
                  animalLines.rewarded.find((r) => r.animalId === entry.animalId)
                    ?.points ?? []
                }
              />
            ))}
            {/* Invisible per-session hit targets, one column each — the same
                idiom as the heatmap cells' native titles. */}
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
                    <title>{describePoint(point, labels)}</title>
                  </rect>
                );
              })}
            </svg>
          </div>
        </ChartFrame>

        {/* Legend and cohort totals in one row, `OutcomeMix`'s idiom: the
            swatch that names a colour carries the number it resolves to. */}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[9px] text-static/70">
          <span className="flex items-center gap-1">
            <span className="inline-block h-[3px] w-3 rounded-[1px]" style={{ background: RESPONSE_COLOR }} />
            response — correct well answered
            {overall.pSide !== null && (
              <span className="tabular-nums text-static">{pct(overall.pSide)}</span>
            )}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-[3px] w-3 rounded-[1px]" style={{ background: REWARDED_COLOR }} />
            rewarded — fluid delivered
            {overall.pRewarded !== null && (
              <span className="tabular-nums text-static">{pct(overall.pRewarded)}</span>
            )}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block size-2 rounded-[2px]" style={{ background: GAP_COLOR, opacity: 0.5 }} />
            gap — correct but lost to the hold
            {overall.pSide !== null && overall.pRewarded !== null && (
              <span className="tabular-nums text-static">
                {pct(overall.pSide - overall.pRewarded)}
              </span>
            )}
          </span>
          <span className="ml-auto tabular-nums">
            {points.length} session{points.length === 1 ? "" : "s"} ·{" "}
            {overall.administered} administered
          </span>
        </div>

        <HowToRead>
          <p>
            Both lines share one denominator — trials whose odor was sampled to
            completion. The response line scores the <em className="not-italic text-static">choice</em>:
            the correct well was answered, hold or not. The rewarded line
            scores the <em className="not-italic text-static">drop</em>: fluid actually delivered. Response is
            always the higher of the pair, and the shaded gap between them is
            the hold-failure rate — an animal learning the discrimination while
            still fumbling the hold shows as the gap widening, not as either
            line moving alone.
          </p>
          <p className="mt-1">
            Faint ribbons are 95% Wilson intervals; hollow dots mark sessions
            under {THIN} administered trials — read loosely. Dashed vertical
            rules are where the cohort&rsquo;s dominant task changed (the strip
            above names them): a cliff at one is a task change, not forgetting.
          </p>
        </HowToRead>
      </div>
    </Panel>
  );
}

/**
 * The area between the response and rewarded lines, split on missing data.
 * Built from the same points as the lines so the three can never disagree
 * about where a session sits or where a gap in the record is.
 */
function holdGapBands(
  points: SessionOutcomePoint[],
): Array<Array<{ x: number; low: number; high: number }>> {
  const out: Array<Array<{ x: number; low: number; high: number }>> = [];
  let current: Array<{ x: number; low: number; high: number }> = [];
  points.forEach((point, index) => {
    const low = point.outcomes.pRewarded;
    const high = point.outcomes.pSide;
    if (low === null || high === null) {
      if (current.length >= 2) out.push(current);
      current = [];
      return;
    }
    current.push({ x: sessionSlot(index, points.length), low, high });
  });
  if (current.length >= 2) out.push(current);
  return out;
}

/**
 * Fades the pooled figure back while any animal is highlighted. A wrapper
 * component rather than a hook in the panel, so a hover re-renders this
 * `<div>` and the overlay layers — never the chart or the reveal animation
 * behind them (§2.1).
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
 * One animal's own response/rewarded pair, visible only while highlighted.
 * Both lines wear the animal's identity colour — which line is which stays
 * readable because response is structurally the upper one — with the rewarded
 * line thinner, echoing the pooled pair's weighting.
 */
function AnimalPairLines({
  animalId,
  color,
  response,
  rewarded,
}: {
  animalId: string;
  color: string;
  response: Array<AnimalAccuracyPoint | null>;
  rewarded: Array<AnimalAccuracyPoint | null>;
}) {
  const highlighted = useIsHighlighted(animalId);
  if (!highlighted) return null;

  const dots: Dot[] = [...response, ...rewarded].flatMap((point) =>
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
          {[
            { line: response, width: 1.6 },
            { line: rewarded, width: 1.0 },
          ].map(({ line, width }, which) =>
            segmentsWithGaps(line).map((segment, index) =>
              segment.points.length < 2 ? null : (
                <polyline
                  key={`${which}-${index}`}
                  points={segment.points
                    .map((p) => `${unitX(p.x)},${unitY(p.y, HEIGHT)}`)
                    .join(" ")}
                  fill="none"
                  stroke={color}
                  strokeWidth={width}
                  strokeLinejoin="round"
                  strokeDasharray={segment.dashed ? "2 2" : undefined}
                  vectorEffect="non-scaling-stroke"
                />
              ),
            ),
          )}
        </DrawOn>
      </svg>
      <ChartDots dots={dots} color={color} spread={HIGHLIGHT_DRAW} />
    </>
  );
}

/** The hover title: which session, on what task(s), and both figures with
 *  the split between them spelled out. */
function describePoint(
  point: SessionOutcomePoint,
  labels: Map<string, string>,
): string {
  const { session, outcomes } = point;
  const head =
    `${session.prefixName}_${session.sessionNumber} · ${session.date}` +
    ` · ${describeTaskMix(point.tasks, labels)}`;
  if (outcomes.pSide === null || outcomes.pRewarded === null) {
    return `${head}\nno administered trials — ${outcomes.aborted} aborted`;
  }
  const parts = [
    `${outcomes.administered} administered`,
    `${pct(outcomes.pSide)} chose the correct well`,
    `${pct(outcomes.pRewarded)} earned fluid`,
    `${outcomes.holdFailed} lost to the hold`,
  ];
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
