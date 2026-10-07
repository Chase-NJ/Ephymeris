import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { LogbookContext } from "./context";
import { LogbookStore } from "./store";

/**
 * App-level, beside `AnalyticsProvider`: Mission Control's quick note, the
 * wrap-up and Step 1's open flags all read the same cache the Log tab does.
 */
export function LogbookProvider({ children }: { children: ReactNode }) {
  const { client } = useSidecar();
  const storeRef = useRef<LogbookStore | null>(null);
  if (storeRef.current === null) storeRef.current = new LogbookStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  return <LogbookContext.Provider value={store}>{children}</LogbookContext.Provider>;
}
