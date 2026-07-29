import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

import type { AnalyticsStore } from "./store";
import type { AnalyticsProgress, AnalyticsSummary, SessionListItem } from "./types";

export const AnalyticsContext = createContext<AnalyticsStore | null>(null);

export function useAnalyticsStore(): AnalyticsStore {
  const store = useContext(AnalyticsContext);
  if (!store) throw new Error("analytics hooks must be used inside <AnalyticsProvider>");
  return store;
}

export function useSelectedCohort(): string | null {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("cohort", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getCohortId());
}

export function useSessionList(cohortId: string | null): SessionListItem[] {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getSessions(cohortId));
}

export function useSummary(cohortId: string | null): AnalyticsSummary | null {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getSummary(cohortId));
}

export function useLoadState(cohortId: string | null) {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getState(cohortId));
}

export function useLoadError(cohortId: string | null): string | null {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getError(cohortId));
}

/**
 * A counter that changes whenever a cached summary is dropped.
 *
 * Belongs in a load effect's dependency list: without it an invalidation from
 * a rescan, a finished session, or a landing leaves a mounted dashboard with
 * no cache and no reason to go and get one.
 */
export function useDataVersion(): number {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getVersion());
}

export function useIndexProgress(): AnalyticsProgress | null {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("progress", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getProgress());
}

/** The selected session, or `"all"` for the whole-cohort scope. */
export function useSelectedSession(): string {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("selection", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getSessionId());
}

export function usePinnedAnimal(): string | null {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("selection", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getPinnedAnimal());
}

/**
 * Whether *this* animal is the highlighted one — deliberately not "which
 * animal is highlighted" (`analytics.md` §2.1).
 *
 * A hover change notifies every subscriber across all five panels, but
 * `useSyncExternalStore` compares the derived **boolean** with `Object.is`, so
 * only the two components whose value actually flipped re-render. Returning
 * the shared id instead would re-render every one of them on every hover.
 *
 * > This only works if each panel renders **one component instance per
 * > animal**. A panel that maps over animals inside a single component calling
 * > this hook once at the top loses the whole scheme, silently and with no
 * > type error.
 */
export function useIsHighlighted(animalId: string): boolean {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("highlight", cb), [store]);
  const snapshot = useCallback(
    () => store.getHighlightedAnimal() === animalId,
    [store, animalId],
  );
  return useSyncExternalStore(subscribe, snapshot);
}

/** True when *some* animal is highlighted — for dimming everything else. */
export function useHasHighlight(): boolean {
  const store = useAnalyticsStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("highlight", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getHighlightedAnimal() !== null);
}
