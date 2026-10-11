import { createContext, useContext } from "react";

import type { ConnectionStatus, SidecarPort } from "./port";

export interface SidecarContextValue {
  client: SidecarPort;
  status: ConnectionStatus;
}

export const SidecarContext = createContext<SidecarContextValue | null>(null);

export function useSidecar(): SidecarContextValue {
  const ctx = useContext(SidecarContext);
  if (!ctx) throw new Error("useSidecar must be used inside <SidecarProvider>");
  return ctx;
}
