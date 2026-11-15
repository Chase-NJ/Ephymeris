import { useEffect, useRef, type ReactNode } from "react";

import { useSidecar } from "../ws/context";
import { HardwareContext } from "./context";
import { HardwareStore } from "./store";

// Mounted at app level (not per-view) so the store catches the on-connect state
// replay and keeps accumulating scrollback while the user is on other screens.
export function HardwareProvider({ children }: { children: ReactNode }) {
  const { client } = useSidecar();
  const storeRef = useRef<HardwareStore | null>(null);
  if (storeRef.current === null) storeRef.current = new HardwareStore();
  const store = storeRef.current;

  useEffect(() => store.attach(client), [client, store]);

  return <HardwareContext.Provider value={store}>{children}</HardwareContext.Provider>;
}
