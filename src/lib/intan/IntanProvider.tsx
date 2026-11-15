import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { IntanContext } from "./context";
import { IntanStore } from "./store";

// App-level, like `HardwareProvider`: the Dashboard's Start Recording tile and
// Mission Control's REC pill both read it, and a scope window mounts one of its
// own over its own socket.
export function IntanProvider({ children }: { children: ReactNode }) {
  const { client } = useSidecar();
  const storeRef = useRef<IntanStore | null>(null);
  if (storeRef.current === null) storeRef.current = new IntanStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  return <IntanContext.Provider value={store}>{children}</IntanContext.Provider>;
}
