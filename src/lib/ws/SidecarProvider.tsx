import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { SidecarClient, type ConnectionStatus } from "./client";
import { SidecarContext } from "./context";

// Component-only module: the hook lives in `context.ts` so Fast Refresh can
// keep this file hot without invalidating consumers.
export function SidecarProvider({ children }: { children: ReactNode }) {
  const clientRef = useRef<SidecarClient | null>(null);
  if (clientRef.current === null) clientRef.current = new SidecarClient();
  const client = clientRef.current;

  const [status, setStatus] = useState<ConnectionStatus>(client.getStatus());

  useEffect(() => {
    const unsubscribe = client.onStatus(setStatus);
    void client.start();
    return () => {
      unsubscribe();
      client.dispose();
    };
  }, [client]);

  const value = useMemo(() => ({ client, status }), [client, status]);
  return <SidecarContext.Provider value={value}>{children}</SidecarContext.Provider>;
}
