import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

import type { SessionStore } from "./store";
import type { AnimalEnded, Prefix, TelemetryMetric } from "./types";

export const SessionContext = createContext<SessionStore | null>(null);

export function useSessionStore(): SessionStore {
  const store = useContext(SessionContext);
  if (!store) throw new Error("session hooks must be used inside <SessionsProvider>");
  return store;
}

export function usePrefixes(): Prefix[] {
  const store = useSessionStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("prefixes", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getPrefixes());
}

export function usePrefixesLoaded(): boolean {
  const store = useSessionStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("prefixes", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.prefixesAreLoaded());
}

/** One box's latest rolling live metrics (`session.telemetry`). */
export function useBoxTelemetry(box: number): TelemetryMetric[] {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`telemetry:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getTelemetry(box));
}

/** One metric's recent values for a box — what the live charts draw. */
export function useMetricHistory(box: number, metricId: string): number[] {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`telemetry:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getHistory(box, metricId));
}

/** The finished run for one box, once `session.animalEnded` arrives. */
export function useBoxEnded(box: number): AnimalEnded | null {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`ended:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getEnded(box));
}
