import { useEffect, useMemo, useReducer } from "react";

import { useAnalyticsStore } from "./context";
import { useSidecar } from "@/lib/ws/context";

export interface CohortSessionStats {
  sessions: number;
  /** The latest session's calendar day (`YYYY-MM-DD`), or null for none. */
  lastDate: string | null;
  /** Its start instant, for ordering — never the name (`DATA.md#directory-layout-and-naming`). */
  lastStartedAt: number | null;
}

/**
 * Session count and latest session per cohort — what the cohort list on the
 * Analytics and Log landings prints beside each roster.
 *
 * Reads through the same app-level analytics cache as `useLastRuns`, so a
 * cohort already browsed (or drawn on the rig) costs nothing. Loading is quiet:
 * a cohort is absent from the map until its summary arrives, and the row shows
 * a dash rather than a spinner.
 */
export function useCohortSessionStats(cohortIds: string[]): Map<string, CohortSessionStats> {
  const { client, status } = useSidecar();
  const store = useAnalyticsStore();

  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  useEffect(() => store.subscribe("data", bump), [store]);

  const idsKey = cohortIds.join("|");
  useEffect(() => {
    if (status !== "connected") return;
    for (const id of cohortIds) {
      void store.load(client, id).catch(() => {
        // An unreadable archive keeps its dash; Analytics reports the failure
        // once the cohort is opened.
      });
    }
    // `tick` re-runs this after an invalidation empties the cache in place.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, status, store, idsKey, tick]);

  return useMemo(() => {
    const out = new Map<string, CohortSessionStats>();
    for (const id of cohortIds) {
      const summary = store.getSummary(id);
      if (!summary) continue;
      let lastDate: string | null = null;
      let lastStartedAt: number | null = null;
      for (const session of summary.sessions) {
        const at = Date.parse(session.clockStartedAt || session.startedAt);
        if (Number.isNaN(at)) continue;
        if (lastStartedAt === null || at > lastStartedAt) {
          lastStartedAt = at;
          lastDate = session.date;
        }
      }
      out.set(id, { sessions: summary.sessions.length, lastDate, lastStartedAt });
    }
    return out;
    // `tick` stands in for the summaries' contents (the store mutates behind
    // stable references).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, idsKey, tick]);
}
