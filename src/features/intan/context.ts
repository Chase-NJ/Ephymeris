import { createContext, useContext, useSyncExternalStore } from "react";

import type { IntanStore } from "./store";
import type { IntanStatus } from "./types";

export const IntanContext = createContext<IntanStore | null>(null);

export function useIntanStore(): IntanStore {
  const store = useContext(IntanContext);
  if (!store) throw new Error("intan hooks must be used inside <IntanProvider>");
  return store;
}

/** The sidecar's last word on RHX and the recording. */
export function useIntanStatus(): IntanStatus {
  const store = useIntanStore();
  return useSyncExternalStore(store.subscribe, store.getStatus);
}
