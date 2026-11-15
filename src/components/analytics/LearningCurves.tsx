import { Activity } from "lucide-react";
import { useMemo, useState } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { PanelTitle } from "@/components/charts/PanelTitle";
import { HowToRead } from "@/components/charts/HowToRead";
import { DrawOn } from "@/components/charts/DrawOn";
import { HIGHLIGHT_DRAW } from "@/components/charts/reveal";
import { UnitChart, unitX, unitY, type Segment } from "@/components/charts/UnitChart";
import { Segmented } from "@/components/common/controls";
import { useHasHighlight, useIsHighlighted } from "@/lib/analytics/context";
import { conditionName } from "@/lib/analytics/session";
import type { RunSeries, RunSummary } from "@/lib/analytics/types";

/**
 * Rolling P(correct) within one session (`DATA.md#learning-curves`): the
 * value per counted trial for each condition any of the session's runs
 * declares, from the `analytics.series` reply the route fetches once.
 * Conditions are the union across the session's runs — a mixed-task session
 * offers more choices rather than hiding runs.
 *
 * Session scope only. Across sessions, the accuracy trend and the strategy
 * plane answer "how is each animal doing" (`DATA.md#analytics-views`); a third
 * per-animal accuracy chart only repeated them at a lower resolution.
 *
 * The x axis is **trial index, never time**. Timestamps are elapsed since each
 * animal's own start, animals in one session begin minutes apart, and stream
 * t=0 trails the recorded start by the handshake — so a shared time axis would
 * be quietly wrong.
 *
 * Each animal's curve draws in a per-animal `<CurveLayer>` inside the chart
 * rather than through `UnitChart`'s `series` prop, because the layer is where
 * the shared highlight lands: the highlighted animal gains stroke weight, the
 * rest drop to a dim opacity, and only these small layers re-render on hover.
 */
export function LearningCurves({
  sessionRuns,
  series,
  colors,
}: {
  /** The selected session's runs — every one, whatever task (`session.ts`). */
  sessionRuns: RunSummary[];
  series: RunSeries[];
  colors: Map<string, string>;
}) {
  return <WithinSessionCurves sessionRuns={sessionRuns} series={series} colors={colors} />;
}

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
      <div className="telemetry p-4">
        <p className="text-[12px] leading-relaxed text-static">
          No scored runs in this session — curves appear once a run with a task
          profile has been recorded.
        </p>
      </div>
    );
  }

  const layers = withinSessionLayers(series, sessionRuns, condition.id, colors);

  return (
    <div className="telemetry flex flex-col gap-3 p-4">
      <ChartFrame
        icon={Activity}
        title={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <PanelTitle
              name="Rolling accuracy"
              note="per trial"
            />
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

/** A fixed plot height (the trends' `PLOT_PX` pattern) — deliberate, not
 *  row-driven, so a neighbouring tile's disclosure opening can never stretch
 *  a curve. Roughly the strategy plane's height beside it. */
const SOLO_PLOT_PX = 300;

interface CurveLayerData {
  key: string;
  animalId: string;
  color: string;
  segments: Segment[];
}

/**
 * One animal's ribbon and curve. One component instance per animal, so a
 * hover re-renders these layers and never the chart around them.
 * Weight, not colour alone, marks the highlight (`DATA.md#colour-palette`).
 *
 * Picking an animal also re-lays its curve down in order — left to right,
 * which on this panel's x axis, trial order, is chronological. The `key` is what
 * replays it: this layer is mounted whether or not it is highlighted, so
 * without it the wipe would have run once, on arrival, and never again.
 */
function CurveLayer({ layer, height }: { layer: CurveLayerData; height: number }) {
  const highlighted = useIsHighlighted(layer.animalId);
  const someoneHighlighted = useHasHighlight();
  const dimmed = someoneHighlighted && !highlighted;

  const body = (
    <>
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
      },
    ];
  });
}
