import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

import type { SessionStore } from "./store";
import type {
  ActiveSessions,
  AnimalEnded,
  Prefix,
  SessionSnapshot,
  TelemetryMetric,
} from "./types";

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

/** The global "what is running?" answer — null until the first load. */
export function useActiveSessions(): ActiveSessions | null {
  const store = useSessionStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("active", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getActive());
}

/** Distinguishes "nothing is running" from "haven't heard back yet". */
export function useActiveLoaded(): boolean {
  const store = useSessionStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("active", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.activeIsLoaded());
}

/** The runner-held session, or null — what the sidebar dot and hero CTA read. */
export function useRunningSession(): SessionSnapshot | null {
  const store = useSessionStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("active", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getActive()?.running ?? null);
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

/** A task started by hand from Debug Mode is still running on this box. */
export function useDebugRunning(box: number): boolean {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`debug:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.isDebugRunning(box));
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

/** The latest session-file write failure for one box, or null. */
export function useBoxWriteError(box: number): string | null {
  const store = useSessionStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`writeError:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getWriteError(box));
}
