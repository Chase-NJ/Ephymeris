import { useEffect, useMemo, useState } from "react";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { UnitChart, segmentsWithGaps, type BandPoint } from "@/components/charts/UnitChart";
import { getSeries } from "@/lib/analytics/commands";
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
import { useSidecar } from "@/lib/ws/context";

/**
 * P(correct) over time (`analytics.md` §5).
 *
 * Two resolutions, chosen by the session selector: across sessions it is one
 * point per session at whole-session P; within one session it is the rolling
 * value per counted trial, fetched from `analytics.series`.
 *
 * The x axis is **trial index, never time**. Timestamps are elapsed since each
 * animal's own start, animals in one session begin minutes apart, and stream
 * t=0 trails the recorded start by the handshake — so a shared time axis would
 * be quietly wrong.
 */
export function LearningCurves({
  summary,
  profile,
  colors,
  sessionScope,
}: {
  summary: AnalyticsSummary;
  profile: ProfileGroup | null;
  colors: Map<string, string>;
  sessionScope: string;
}) {
  const withinSession = sessionScope !== ALL_SESSIONS;
  const runsInScope = useMemo(
    () =>
      withinSession
        ? runsInProfile(summary.runs, profile).filter((r) => r.sessionId === sessionScope)
        : [],
    [summary, profile, sessionScope, withinSession],
  );
  const series = useRunSeries(withinSession ? runsInScope : []);

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
          <UnitChart
            height={46}
            references={[{ y: 0.5 }]}
            bands={
              withinSession
                ? []
                : summary.animals
                    .map((animal) =>
                      acrossSessionBand(summary, profile, animal.id, metric.id, colors),
                    )
                    .filter((b): b is NonNullable<typeof b> => b !== null)
            }
            series={
              withinSession
                ? withinSessionLines(series, runsInScope, metric.id, colors)
                : acrossSessionLines(summary, profile, metric.id, colors)
            }
          />
        </ChartFrame>
      ))}
    </div>
  );
}

/** Fetches the rolling trajectories for the runs currently on screen. */
function useRunSeries(runs: RunSummary[]): RunSeries[] {
  const { client } = useSidecar();
  const [series, setSeries] = useState<RunSeries[]>([]);
  const ids = runs.map((run) => run.runId).join(",");

  useEffect(() => {
    if (!ids) {
      setSeries([]);
      return;
    }
    let live = true;
    void getSeries(client, ids.split(","))
      .then((result) => {
        if (live) setSeries(result.series);
      })
      .catch(() => {
        if (live) setSeries([]);
      });
    return () => {
      live = false;
    };
  }, [client, ids]);

  return series;
}

function withinSessionLines(
  series: RunSeries[],
  runs: RunSummary[],
  metricId: string,
  colors: Map<string, string>,
) {
  const animalOf = new Map(runs.map((run) => [run.runId, run.animalId]));
  return series.flatMap((run) => {
    const metric = run.metrics.find((m) => m.id === metricId);
    if (!metric || metric.values.length < 2) return [];
    const animalId = animalOf.get(run.runId);
    const points = metric.values.map((value, index) => ({
      x: index / (metric.values.length - 1),
      y: value,
    }));
    return [
      {
        segments: [{ points }],
        stroke: colors.get(animalId ?? "") ?? "var(--color-series-1)",
        strokeWidth: 1.5,
      },
    ];
  });
}

function acrossSessionLines(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  metricId: string,
  colors: Map<string, string>,
) {
  return summary.animals.flatMap((animal) => {
    const points = acrossSessionPoints(summary, profile, animal.id, metricId);
    if (points.filter(Boolean).length < 2) return [];
    return [
      {
        segments: segmentsWithGaps(points),
        stroke: colors.get(animal.id) ?? "var(--color-series-1)",
        strokeWidth: 1.5,
      },
    ];
  });
}

function acrossSessionBand(
  summary: AnalyticsSummary,
  profile: ProfileGroup | null,
  animalId: string,
  metricId: string,
  colors: Map<string, string>,
): { points: BandPoint[]; fill: string; opacity: number } | null {
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
  if (points.length < 2) return null;
  return {
    points,
    fill: colors.get(animalId) ?? "var(--color-series-1)",
    // Wide where n is small, so uncertainty is drawn rather than thresholded
    // away — kept faint so six overlapping bands stay readable (§3.5).
    opacity: 0.1,
  };
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
