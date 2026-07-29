import { ChartFrame } from "@/components/charts/ChartFrame";
import { DrawOn } from "@/components/charts/DrawOn";
import { HIGHLIGHT_DRAW } from "@/components/charts/reveal";
import {
  UnitChart,
  ribbon,
  segmentsWithGaps,
  unitX,
  unitY,
  type BandPoint,
  type Segment,
} from "@/components/charts/UnitChart";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import { ALL_SESSIONS } from "@/lib/analytics/store";
import type {
  AnalyticsSummary,
  ProfileGroup,
  RunSeries,
  RunSummary,
} from "@/lib/analytics/types";
import {
  chronological,
  declaredMetrics,
  pickMetric,
  runsInProfile,
} from "@/lib/analytics/view";

/**
 * P(correct) over time (`analytics.md` §5).
 *
 * Two resolutions, chosen by the session selector: across sessions it is one
 * point per session at whole-session P; within one session it is the rolling
 * value per counted trial, from the `analytics.series` reply the route fetches
 * once for every panel that needs it.
 *
 * The x axis is **trial index, never time**. Timestamps are elapsed since each
 * animal's own start, animals in one session begin minutes apart, and stream
 * t=0 trails the recorded start by the handshake — so a shared time axis would
 * be quietly wrong.
 *
 * Each animal's band and curve draw in a per-animal `<CurveLayer>` inside the
 * chart rather than through `UnitChart`'s `series` prop, because the layer is
 * where the shared highlight lands (§2.1): the highlighted animal gains
 * stroke weight, the rest drop to a dim opacity, and only these small layers
 * re-render on hover.
 */
export function LearningCurves({
  summary,
  profile,
  colors,
  sessionScope,
  series,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  sessionScope: string;
  /** The selected session's trajectories. Empty across sessions, where the
   *  curves are built from the summary's per-session scalars instead. */
  series: RunSeries[];
}) {
  const withinSession = sessionScope !== ALL_SESSIONS;
  const runsInScope = withinSession
    ? runsInProfile(summary.runs, profile).filter((r) => r.sessionId === sessionScope)
    : [];

  // Within a session the pooled figure has no series: `analytics.series`
  // replays each declared condition separately, and pooling interleaved trials
  // into one rolling window would need a different accumulator than the one
  // the live path uses. Rather than render an empty chart, the pooled view is
  // simply a session-level summary and appears only across sessions.
  const charts = withinSession ? declaredMetrics(profile) : (profile?.metrics ?? []);

  if (!profile || charts.length === 0) {
    return (
      <div className="surface rounded-md p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No scored runs yet — curves appear once a session with a task profile
          has been recorded.
        </p>
      </div>
    );
  }

  return (
    <div className="surface flex flex-col gap-4 rounded-md p-4">
      {charts.map((metric) => (
        <ChartFrame
          key={metric.id}
          title={
            <span>
              {metric.label}
              <span className="ml-2 text-static/70">
                {withinSession ? "rolling, per trial" : "whole session, per session"}
              </span>
            </span>
          }
          yTop="1.0"
          yBottom="0.0"
          xLeft={withinSession ? "trial 1" : "first"}
          xRight={withinSession ? "last" : "latest"}
        >
          <UnitChart height={46} references={[{ y: 0.5 }]}>
            {(withinSession
              ? withinSessionLayers(series, runsInScope, metric.id, colors)
              : acrossSessionLayers(summary, profile, metric.id, colors)
            ).map((layer) => (
              <CurveLayer key={layer.key} layer={layer} height={46} />
            ))}
          </UnitChart>
        </ChartFrame>
      ))}
    </div>
  );
}

interface CurveLayerData {
  key: string;
  animalId: string;
  color: string;
  segments: Segment[];
  /** The Wilson ribbon behind the curve — across-session scope only. */
  band: BandPoint[] | null;
}

/**
 * One animal's ribbon and curve. One component instance per animal, so a
 * hover re-renders these layers and never the chart around them (§2.1).
 * Weight, not colour alone, marks the highlight (§7.1).
 *
 * Picking an animal also re-lays its curve down in order — left to right,
 * which on both of this panel's x axes is chronological. The `key` is what
 * replays it: this layer is mounted whether or not it is highlighted, so
 * without it the wipe would have run once, on arrival, and never again.
 */
function CurveLayer({ layer, height }: { layer: CurveLayerData; height: number }) {
  const highlighted = useIsHighlighted(layer.animalId);
  const someoneHighlighted = useHasHighlight();
  const dimmed = someoneHighlighted && !highlighted;

  const body = (
    <>
      {/* Band before curve: SVG paints in document order, and the ribbon
          belongs behind its own line. Wide where n is small, so uncertainty
          is drawn rather than thresholded away — kept faint so six
          overlapping bands stay readable (§3.5). */}
      {layer.band && layer.band.length >= 2 && (
        <polygon
          points={ribbon(layer.band, height)}
          fill={layer.color}
          fillOpacity={highlighted ? 0.18 : 0.1}
          stroke="none"
        />
      )}
      {layer.segments.map((segment, index) =>
        segment.points.length < 2 ? null : (
          <polyline
            key={index}
            points={segment.points
              .map((p) => `${unitX(p.x)},${unitY(p.y, height)}`)
              .join(" ")}
            fill="none"
            stroke={layer.color}
            strokeWidth={highlighted ? 2.1 : 1.5}
            strokeLinejoin="round"
            strokeDasharray={segment.dashed ? "2 2" : undefined}
            vectorEffect="non-scaling-stroke"
          />
        ),
      )}
    </>
  );

  return (
    <g opacity={dimmed ? 0.18 : 1}>
      {highlighted ? (
        <DrawOn key="walk" viewBox={[0, 0, 100, height]} duration={HIGHLIGHT_DRAW}>
          {body}
        </DrawOn>
      ) : (
        body
      )}
    </g>
  );
}

function withinSessionLayers(
  series: RunSeries[],
  runs: RunSummary[],
  metricId: string,
  colors: Map<string, string>,
): CurveLayerData[] {
  const animalOf = new Map(runs.map((run) => [run.runId, run.animalId]));
  return series.flatMap((run) => {
    const metric = run.metrics.find((m) => m.id === metricId);
    if (!metric || metric.values.length < 2) return [];
    const animalId = animalOf.get(run.runId) ?? "";
    const points = metric.values.map((value, index) => ({
      x: index / (metric.values.length - 1),
      y: value,
    }));
    return [
      {
        key: run.runId,
        animalId,
        color: colors.get(animalId) ?? "var(--color-series-1)",
        segments: [{ points }],
        band: null,
      },
    ];
  });
}

function acrossSessionLayers(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  metricId: string,
  colors: Map<string, string>,
): CurveLayerData[] {
  return summary.animals.flatMap((animal) => {
    const points = acrossSessionPoints(summary, profile, animal.id, metricId);
    const segments =
      points.filter(Boolean).length >= 2 ? segmentsWithGaps(points) : [];
    const band = acrossSessionBand(summary, profile, animal.id, metricId);
    if (segments.length === 0 && band === null) return [];
    return [
      {
        key: animal.id,
        animalId: animal.id,
        color: colors.get(animal.id) ?? "var(--color-series-1)",
        segments,
        band,
      },
    ];
  });
}

function acrossSessionBand(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  animalId: string,
  metricId: string,
): BandPoint[] | null {
  const runs = chronological(
    runsInProfile(summary.runs, profile).filter((r) => r.animalId === animalId),
    summary.sessions,
  );
  if (runs.length < 2) return null;
  const points: BandPoint[] = [];
  runs.forEach((run, index) => {
    const metric = pickMetric(run, metricId);
    if (!metric || metric.wilsonLow === null || metric.wilsonHigh === null) return;
    points.push({
      x: index / (runs.length - 1),
      low: metric.wilsonLow,
      high: metric.wilsonHigh,
    });
  });
  return points.length < 2 ? null : points;
}

function acrossSessionPoints(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  animalId: string,
  metricId: string,
) {
  const runs = chronological(
    runsInProfile(summary.runs, profile).filter((r) => r.animalId === animalId),
    summary.sessions,
  );
  return runs.map((run, index) => {
    const value = pickMetric(run, metricId)?.pSession;
    return value === null || value === undefined
      ? null
      : { x: runs.length === 1 ? 0.5 : index / (runs.length - 1), y: value };
  });
}
