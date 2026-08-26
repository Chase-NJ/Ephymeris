import { useMemo, useState } from "react";

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
import { Segmented } from "@/components/common/controls";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import { conditionName } from "@/lib/analytics/session";
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
/**
 * One condition's rolling accuracy, in a tile the reader chooses.
 *
 * **A picker, not a stack.** This drew one chart per condition, which was fine
 * for the two-odor task it was written against and became a column of four
 * 168px plots the moment the lab ran four odors — each one a sixth of the tile,
 * none of them readable, and the tile itself taller than the panel beside it.
 * The conditions are mutually exclusive readings of the same axis, so they are
 * a *selection*, not a series: one at a time, at a size worth looking at.
 *
 * The picker names conditions by the operator's own words (`conditionName` —
 * the conditioning half of the metric label, which the task editor now requires
 * them to fill in), and the full metric sentence stays in the frame's title.
 */
function WithinSessionCurves({
  sessionRuns,
  series,
  colors,
}: {
  sessionRuns: RunSummary[];
  series: RunSeries[];
  colors: Map<string, string>;
}) {
  // The union of what any run in the session declares, in first-seen authored
  // order — the session table's rule (`session.ts`), so a mixed-task session
  // offers every condition rather than hiding the runs it can't merge.
  const conditions = useMemo(() => {
    const out: Array<{ id: string; label: string; short: string }> = [];
    for (const run of sessionRuns) {
      for (const metric of run.metrics) {
        if (!out.some((entry) => entry.id === metric.id)) {
          out.push({
            id: metric.id,
            label: metric.label,
            short: conditionName(metric.label),
          });
        }
      }
    }
    return out;
  }, [sessionRuns]);

  const [chosen, setChosen] = useState<string | null>(null);
  const condition = conditions.find((c) => c.id === chosen) ?? conditions[0] ?? null;

  if (!condition) {
    return (
      <div className="surface rounded-md p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No scored runs in this session — curves appear once a run with a task
          profile has been recorded.
        </p>
      </div>
    );
  }

  const layers = withinSessionLayers(series, sessionRuns, condition.id, colors);

  return (
    <div className="surface flex flex-col gap-3 rounded-md p-4">
      <ChartFrame
        title={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>
              Rolling accuracy
              <span className="ml-2 text-static/70">per trial</span>
            </span>
            {conditions.length > 1 && (
              <Segmented
                value={condition.id}
                onChange={setChosen}
                label="Condition on the curve"
                options={conditions.map((entry) => ({
                  value: entry.id,
                  label: entry.short,
                }))}
              />
            )}
          </span>
        }
        yTop="1.0"
        yBottom="0.0"
        xLeft="trial 1"
        xRight="last"
        footer={<span className="truncate text-static/70">{condition.label}</span>}
      >
        <div style={{ height: SOLO_PLOT_PX }}>
          <UnitChart height={46} className="h-full w-full" references={[{ y: 0.5 }]}>
            {layers.map((layer) => (
              <CurveLayer key={layer.key} layer={layer} height={46} />
            ))}
          </UnitChart>
        </div>
      </ChartFrame>
      {layers.length === 0 && (
        <p className="font-mono text-[9px] text-static/60">
          No animal scored this condition in this session.
        </p>
      )}
      <HowToRead>
        <p>
          Each line is one animal&rsquo;s rolling P(hit) for the selected
          condition at the task&rsquo;s authored window, one point per counted
          trial.
        </p>
        <p className="mt-1">
          The x axis is trial index, never wall time: animals start minutes apart
          and each stream&rsquo;s clock starts at its own handshake, so a shared
          time axis would quietly misalign them.
        </p>
      </HowToRead>
    </div>
  );
}

/** Fixed plot heights (the trends' `PLOT_PX` pattern) — deliberate, not
 *  aspect- or row-driven, so a neighbouring tile's disclosure opening can
 *  never stretch a curve. Two session-scope charts roughly match the
 *  strategy plane's height; the single cohort chart gets the sum. */
/** One chart instead of N, so it gets the room the stack used to divide. */
const SOLO_PLOT_PX = 300;
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
    return (
      <WithinSessionCurves
        sessionRuns={sessionRuns}
        series={series}
        colors={colors}
      />
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
