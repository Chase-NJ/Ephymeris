/**
 * The within-session trajectories for a set of runs (`data.md` §11.2, §4.4).
 *
 * One hook rather than one per panel: selecting a session puts the learning
 * curves, the strategy walk and the summary tile on screen together, and every
 * one of them wants the same `analytics.series` reply. Fetched once at the
 * route and passed down, so the reply is shared rather than requested three
 * times for the same run ids.
 *
 * Keyed on the joined run ids so the effect is stable across the re-renders a
 * hover causes — a dependency on the array itself would refetch on every
 * pointer move.
 */

import { useEffect, useState } from "react";

import { getSeries } from "./commands";
import type { RunSeries, RunSummary } from "./types";
import type { SidecarClient } from "../ws/client";

const NONE: RunSeries[] = [];

export function useRunSeries(client: SidecarClient, runs: RunSummary[]): RunSeries[] {
  const [series, setSeries] = useState<RunSeries[]>(NONE);
  // The sidecar rejects the whole request past MAX_SERIES_RUNS (24), not the
  // excess. A session normally holds ≤6 runs, but restarts and duplicate
  // adoptions can pile on — better a few missing trajectories than none.
  const ids = runs
    .slice(0, 24)
    .map((run) => run.runId)
    .join(",");

  useEffect(() => {
    if (!ids) {
      setSeries(NONE);
      return;
    }
    let live = true;
    void getSeries(client, ids.split(","))
      .then((result) => {
        if (live) setSeries(result.series);
      })
      .catch(() => {
        // A failed series read leaves the trajectories blank rather than
        // blanking the panels: every scalar on screen came from the summary
        // call and is still true.
        if (live) setSeries(NONE);
      });
    return () => {
      live = false;
    };
  }, [client, ids]);

  return series;
}
