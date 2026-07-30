import { useEffect, useMemo, useReducer } from "react";

import { useAnalyticsStore } from "@/lib/analytics/context";
import { useActiveCohorts } from "@/lib/cohorts/context";
import { lastRunsByAnimal, type ShipMember } from "@/lib/constellations/ships";
import { useSidecar } from "@/lib/ws/context";

/**
 * What Debug's constellation knows beyond hardware state: each box's earned
 * temperature, and every animal of every active cohort as a candidate
 * ship-crew member (`ships.ts`).
 */
export interface BoxStellar {
  /**
   * Mean pooled accuracy of the box's assigned animals across all scored
   * sessions, or null before anything has scored — which reads as the cool
   * end of the ramp, same as Mission Control's unscored stars.
   */
  accuracy: number | null;
}

export interface RigStellar {
  boxes: Partial<Record<number, BoxStellar>>;
  /**
   * Every animal across all active cohorts, ready for `assignShips` — home
   * cage, standing box assignment, and its most recent recorded run. The
   * caller layers live running state on top before assigning.
   */
  members: ShipMember[];
}

/**
 * Star temperatures and crews for the Debug constellation
 * (`ephymeris_v1.0.md` §4.3).
 *
 * A box's temperature is the **mean accuracy of the animals assigned to it**,
 * each animal's own accuracy pooled across *all* of its scored sessions —
 * hits over counted trials of the run-level `overall` metric, the pooled
 * accuracy that can tell learning from a side bias (`analytics.md` §3.7).
 * Assignment comes from the same summaries, so one fetch per active cohort
 * covers both facts, through the app-level analytics cache the Analytics view
 * shares — browsing the rig after checking a cohort costs nothing extra.
 *
 * Loading is quiet by design: stars render immediately on the cool end and
 * warm to their earned temperature as summaries arrive (`StellarSurface`
 * eases colour, so late data is an animation, not a pop).
 */
export function useBoxStellar(): RigStellar {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();
  const cohorts = useActiveCohorts();

  // Re-render when any summary lands or the cache is invalidated; the store
  // notifies "data" for both. A reducer beats useSyncExternalStore here
  // because the snapshot spans every cohort's summary at once.
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => store.subscribe("data", bump), [store]);

  useEffect(() => {
    if (status !== "connected") return;
    for (const cohort of cohorts) {
      void store.load(client, cohort.id).catch(() => {
        // A cohort whose archive can't be read keeps its boxes cool rather
        // than blocking the scene; the Analytics view is where the error
        // itself is surfaced.
      });
    }
    // `tick` re-runs this after an invalidation, which clears the cache
    // without changing any cohort id — the reload has to be asked for.
  }, [client, status, store, cohorts, tick]);

  return useMemo(() => {
    const sums = new Map<number, { total: number; n: number }>();
    const members: ShipMember[] = [];

    for (const cohort of cohorts) {
      const summary = store.getSummary(cohort.id);
      if (!summary) continue;

      // Each animal's accuracy, pooled across every scored run it has:
      // Σ hits / Σ counted, reconstructed from pSession × counted.
      const pooled = new Map<string, { hits: number; counted: number }>();
      for (const run of summary.runs) {
        const overall = run.overall;
        if (!overall || overall.pSession === null || overall.counted <= 0) continue;
        const acc = pooled.get(run.animalId) ?? { hits: 0, counted: 0 };
        acc.hits += overall.pSession * overall.counted;
        acc.counted += overall.counted;
        pooled.set(run.animalId, acc);
      }

      const lastRuns = lastRunsByAnimal(summary.runs);
      for (const animal of summary.animals) {
        const lastRun = lastRuns.get(animal.id);
        members.push({
          id: animal.id,
          name: animal.name,
          cage: animal.cage,
          box: animal.boxNumber,
          running: false,
          lastRunAt: lastRun?.at ?? null,
          lastRunBox: lastRun?.box ?? null,
        });
        if (animal.boxNumber === null) continue;

        const scored = pooled.get(animal.id);
        if (!scored || scored.counted <= 0) continue;
        const sum = sums.get(animal.boxNumber) ?? { total: 0, n: 0 };
        sum.total += scored.hits / scored.counted;
        sum.n += 1;
        sums.set(animal.boxNumber, sum);
      }
    }

    const boxes: Partial<Record<number, BoxStellar>> = {};
    for (const [box, sum] of sums) {
      boxes[box] = { accuracy: sum.n > 0 ? sum.total / sum.n : null };
    }
    return { boxes, members };
    // `tick` stands in for the summaries' contents, which the store mutates
    // behind a stable reference map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cohorts, store, tick]);
}
