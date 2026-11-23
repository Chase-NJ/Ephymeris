import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";

import type { CohortStore } from "./store";
import type { CohortSummary } from "./types";

export const CohortContext = createContext<CohortStore | null>(null);

export function useCohortStore(): CohortStore {
  const store = useContext(CohortContext);
  if (!store) throw new Error("cohort hooks must be used inside <CohortsProvider>");
  return store;
}

/** Every cohort the sidecar knows about, archived included. */
export function useCohorts(): CohortSummary[] {
  const store = useCohortStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe(cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getAll());
}

/** False until the sidecar has answered — keeps empty states honest. */
export function useCohortsLoaded(): boolean {
  const store = useCohortStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe(cb), [store]);
  return useSyncExternalStore(subscribe, () => store.isLoaded());
}

/**
 * Active (non-archived) cohorts — what the browser shows by default (`ARCHITECTURE.md#cohort-browser`) and what
 * the dashboard counts.
 */
export function useActiveCohorts(): CohortSummary[] {
  const cohorts = useCohorts();
  return useMemo(() => cohorts.filter((c) => !c.archived), [cohorts]);
}
