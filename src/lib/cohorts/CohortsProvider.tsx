import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { CohortContext } from "./context";
import { CohortStore } from "./store";

/**
 * Mounted at app level so the dashboard tile and the sidebar stay in sync with
 * the cohort list regardless of which screen is open — the same reasoning as
 * the hardware store.
 */
export function CohortsProvider({ children }: { children: ReactNode }) {
  const { client, status } = useSidecar();
  const storeRef = useRef<CohortStore | null>(null);
  if (storeRef.current === null) storeRef.current = new CohortStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  // Drop the roster when the connection goes: showing a stale cohort list
  // while the sidecar is unreachable would invite acting on it.
  useEffect(() => {
    if (status !== "connected") store.reset();
  }, [status, store]);

  return <CohortContext.Provider value={store}>{children}</CohortContext.Provider>;
}
