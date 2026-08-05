import { ChartFrame } from "@/components/charts/ChartFrame";
import { HowToRead } from "@/components/charts/HowToRead";
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
import type { AnalyticsSummary, RunSeries, RunSummary } from "@/lib/analytics/types";
import { chronological, pickMetric } from "@/lib/analytics/view";

/**
 * P(correct) over time (`data.md` §11.2).
 *
 * Two resolutions, chosen by the session selector — and two different
 * scopings, each decided by the panel rather than by a filter:
 *
 * - **Across sessions**: one chart, each animal's whole history at its
 *   pooled overall accuracy (§3.7) — every run, whatever task it was on,
 *   because "how is this animal doing" is a question about the animal, not
 *   about one task. Per-condition histories are the strategy space's job;
 *   here they would be one chart per task per condition, unreadable at
 *   cohort scale.
 * - **Within one session**: the rolling value per counted trial for each
 *   condition any of the session's runs declares, from the
 *   `analytics.series` reply the route fetches once. Conditions are the
 *   union across the session's runs — a mixed-task session grows charts
 *   rather than hiding runs.
 *
 * The x axis is **trial index / run ordinal, never time**. Timestamps are
 * elapsed since each animal's own start, animals in one session begin minutes
 * apart, and stream t=0 trails the recorded start by the handshake — so a
 * shared time axis would be quietly wrong.
 *
 * Each animal's band and curve draw in a per-animal `<CurveLayer>` inside the
 * chart rather than through `UnitChart`'s `series` prop, because the layer is
 * where the shared highlight lands (§2.1): the highlighted animal gains
 * stroke weight, the rest drop to a dim opacity, and only these small layers
 * re-render on hover.
 */
/** Fixed plot heights (the trends' `PLOT_PX` pattern) — deliberate, not
 *  aspect- or row-driven, so a neighbouring tile's disclosure opening can
 *  never stretch a curve. Two session-scope charts roughly match the
 *  strategy plane's height; the single cohort chart gets the sum. */
const SESSION_PLOT_PX = 168;
const COHORT_PLOT_PX = 300;

export function LearningCurves({
  summary,
  colors,
  sessionScope,
  sessionRuns,
  series,
}: {
  summary: AnalyticsSummary;
  colors: Map<string, string>;
  sessionScope: string;
  /** The selected session's runs — every one, whatever task (`session.ts`).
   *  Empty across sessions. */
  sessionRuns: RunSummary[];
  /** The selected session's trajectories. Empty across sessions, where the
   *  curves are built from the summary's per-session scalars instead. */
  series: RunSeries[];
}) {
  const withinSession = sessionScope !== ALL_SESSIONS;

  if (withinSession) {
    // One chart per condition any run in the session declares, in first-seen
    // authored order — the session table's union rule (`session.ts`).
    const conditions: Array<{ id: string; label: string }> = [];
    for (const run of sessionRuns) {
      for (const metric of run.metrics) {
        if (!conditions.some((entry) => entry.id === metric.id)) {
          conditions.push({ id: metric.id, label: metric.label });
        }
      }
    }

    if (conditions.length === 0) {
      return (
        <div className="surface rounded-md p-4">
          <p className="text-[12px] leading-relaxed text-static">
            No scored runs in this session — curves appear once a run with a
            task profile has been recorded.
          </p>
        </div>
      );
    }

    return (
      // Fixed plot heights, own tile height: the grid row is `items-start`,
      // so this tile neither stretches to the strategy plane's height (the
      // old dead surface) nor re-stretches its charts when the neighbour's
      // "how to read this" opens.
      <div className="surface flex flex-col gap-4 rounded-md p-4">
        {conditions.map((condition) => (
          <div key={condition.id}>
            <ChartFrame
              title={
                <span>
                  {condition.label}
                  <span className="ml-2 text-static/70">rolling, per trial</span>
                </span>
              }
              yTop="1.0"
              yBottom="0.0"
              xLeft="trial 1"
              xRight="last"
            >
              <div style={{ height: SESSION_PLOT_PX }}>
                <UnitChart
                  height={46}
                  className="h-full w-full"
                  references={[{ y: 0.5 }]}
                >
                  {withinSessionLayers(series, sessionRuns, condition.id, colors).map(
                    (layer) => (
                      <CurveLayer key={layer.key} layer={layer} height={46} />
                    ),
                  )}
                </UnitChart>
              </div>
            </ChartFrame>
          </div>
        ))}
        <HowToRead>
          <p>
            Each line is one animal&rsquo;s rolling P(hit) for this condition at
            the task&rsquo;s authored window, one point per counted trial.
          </p>
          <p className="mt-1">
            The x axis is trial index, never wall time: animals start minutes
            apart and each stream&rsquo;s clock starts at its own handshake, so
            a shared time axis would quietly misalign them.
          </p>
        </HowToRead>
      </div>
    );
  }

  const layers = acrossSessionLayers(summary, colors);
  if (layers.length === 0) {
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
      <div>
        <ChartFrame
          title={
            <span>
              Overall accuracy
              <span className="ml-2 text-static/70">
                whole session, per session · every task
              </span>
            </span>
          }
          yTop="1.0"
          yBottom="0.0"
          xLeft="first"
          xRight="latest"
        >
          <div style={{ height: COHORT_PLOT_PX }}>
            <UnitChart height={46} className="h-full w-full" references={[{ y: 0.5 }]}>
              {layers.map((layer) => (
                <CurveLayer key={layer.key} layer={layer} height={46} />
              ))}
            </UnitChart>
          </div>
        </ChartFrame>
      </div>
      <HowToRead>
        <p>
          One line per animal, one point per run, at the run&rsquo;s accuracy
          pooled across every condition — the only single number that can tell
          learning from a side bias (§9.7). Each run is scored at whatever task
          it ran that day; the task strip below marks where that changed.
        </p>
        <p className="mt-1">
          The ribbon behind a line is its 95% Wilson interval — wide where a
          session scored few trials, so thin evidence is drawn rather than
          hidden. The x axis is each animal&rsquo;s own run order, not calendar
          time; the session rail above is where a gap in days is real.
        </p>
      </HowToRead>
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
    // A series for a run outside this session (stale fetch) draws nothing.
    if (animalId === "") return [];
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

/** Every run, pooled overall per run (§3.7) — `pickMetric(run, null)`. */
function acrossSessionLayers(
  summary: AnalyticsSummary,
  colors: Map<string, string>,
): CurveLayerData[] {
  return summary.animals.flatMap((animal) => {
    const runs = chronological(
      summary.runs.filter((run) => run.animalId === animal.id),
      summary.sessions,
    );
    const points = runs.map((run, index) => {
      const value = pickMetric(run, null)?.pSession;
      return value === null || value === undefined
        ? null
        : { x: runs.length === 1 ? 0.5 : index / (runs.length - 1), y: value };
    });
    const segments =
      points.filter(Boolean).length >= 2 ? segmentsWithGaps(points) : [];

    const band: BandPoint[] = [];
    if (runs.length >= 2) {
      runs.forEach((run, index) => {
        const metric = pickMetric(run, null);
        if (!metric || metric.wilsonLow === null || metric.wilsonHigh === null) return;
        band.push({
          x: index / (runs.length - 1),
          low: metric.wilsonLow,
          high: metric.wilsonHigh,
        });
      });
    }

    if (segments.length === 0 && band.length < 2) return [];
    return [
      {
        key: animal.id,
        animalId: animal.id,
        color: colors.get(animal.id) ?? "var(--color-series-1)",
        segments,
        band: band.length >= 2 ? band : null,
      },
    ];
  });
}
