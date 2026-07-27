import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { AnalyticsContext } from "./context";
import { AnalyticsStore } from "./store";

/**
 * Mounted at app level, not inside the route: a cold summary can be an index
 * of an entire archive, and navigating away to check a cohort and back should
 * not pay that cost twice.
 */
export function AnalyticsProvider({ children }: { children: ReactNode }) {
  const { client } = useSidecar();
  const storeRef = useRef<AnalyticsStore | null>(null);
  if (storeRef.current === null) storeRef.current = new AnalyticsStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  return <AnalyticsContext.Provider value={store}>{children}</AnalyticsContext.Provider>;
}
