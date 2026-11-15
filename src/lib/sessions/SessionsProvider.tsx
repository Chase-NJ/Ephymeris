import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { SessionContext } from "./context";
import { SessionStore } from "./store";

/**
 * App-level so the prefix list is warm before the session flow opens, and so
 * telemetry keeps accumulating if the user navigates away from Mission Control
 * mid-run.
 */
export function SessionsProvider({ children }: { children: ReactNode }) {
  const { client } = useSidecar();
  const storeRef = useRef<SessionStore | null>(null);
  if (storeRef.current === null) storeRef.current = new SessionStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  return <SessionContext.Provider value={store}>{children}</SessionContext.Provider>;
}
