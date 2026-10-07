import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

import type { LogbookEntry, LogbookStore } from "./store";

export const LogbookContext = createContext<LogbookStore | null>(null);

export function useLogbookStore(): LogbookStore {
  const store = useContext(LogbookContext);
  if (!store) throw new Error("logbook hooks must be used inside <LogbookProvider>");
  return store;
}

export function useLogbook(cohortId: string | null): LogbookEntry {
  const store = useLogbookStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("data", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getEntry(cohortId));
}

export function useLogCohort(): string | null {
  const store = useLogbookStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("selection", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getCohortId());
}

export function useLogSession(): string | null {
  const store = useLogbookStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("selection", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getSessionId());
}
