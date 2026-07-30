import { useEffect, useMemo, useReducer } from "react";

import { useAnalyticsStore } from "./context";
import { lastRunsByAnimal } from "@/lib/constellations/ships";
import { useSidecar } from "@/lib/ws/context";

/**
 * Latest recorded run (when, and on which box) per animal, across the given
 * cohorts — what anchors a parked cage-ship to the box its most recently ran
 * crew member was on (`ships.ts`).
 *
 * Reads through the app-level analytics cache the Analytics view and the rig
 * view already share, so a cohort browsed anywhere costs nothing extra here.
 * Loading is quiet: ships fall back to standing assignments until summaries
 * arrive, then glide to their recorded box.
 */
export function useLastRuns(cohortIds: string[]): Map<string, { at: string; box: number }> {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();

  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => store.subscribe("data", bump), [store]);

  const idsKey = cohortIds.join("|");
  useEffect(() => {
    if (status !== "connected") return;
    for (const id of cohortIds) {
      void store.load(client, id).catch(() => {
        // An unreadable archive keeps its ships on the standing-assignment
        // fallback; Analytics is where the failure itself is reported.
      });
    }
    // `tick` re-runs this after an invalidation empties the cache in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, status, store, idsKey, tick]);

  return useMemo(() => {
    const merged = new Map<string, { at: string; box: number }>();
    for (const id of cohortIds) {
      const summary = store.getSummary(id);
      if (!summary) continue;
      for (const [animalId, run] of lastRunsByAnimal(summary.runs)) {
        merged.set(animalId, run);
      }
    }
    return merged;
    // `tick` stands in for the summaries' contents (the store mutates behind
    // stable references).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, idsKey, tick]);
}
