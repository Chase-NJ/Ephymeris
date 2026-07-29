import { createContext, useCallback, useContext, useSyncExternalStore } from "react";

import type {
  ConsoleLine,
  DetectedBoard,
  FlashedSketch,
  HardwareStore,
  PortStatus,
  UtilityStatus,
} from "./store";

export const HardwareContext = createContext<HardwareStore | null>(null);

export function useHardwareStore(): HardwareStore {
  const store = useContext(HardwareContext);
  if (!store) throw new Error("hardware hooks must be used inside <HardwareProvider>");
  return store;
}

/** The sidecar-reported state of one box's port. */
export function usePortStatus(box: number): PortStatus {
  const store = useHardwareStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`state:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getStatus(box));
}

/** All six boxes' states at once — feeds the constellation widget. */
export function useAllPortStatuses(): Readonly<Record<number, PortStatus>> {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("state:*", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getAllStatuses());
}

/** One box's console scrollback (batched by the sidecar at 20Hz). */
export function useBoxOutput(box: number): ConsoleLine[] {
  const store = useHardwareStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`output:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getLines(box));
}

/** The sketch most recently flashed to a box this session, or null. */
export function useFlashedSketch(box: number): FlashedSketch | null {
  const store = useHardwareStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`flashed:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getFlashed(box));
}

/**
 * Boards the out-of-band poll can currently see (`hardware-interaction.md` §7).
 * Feeds the Settings binding table, the console panels, and the constellation
 * widget from the same cache — including the on-connect replay, so a component
 * mounting between polls still sees the current picture.
 */
export function useBoardPresence(): DetectedBoard[] {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("presence", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getBoards());
}

/**
 * The hardware utility baseline (`hardware-interaction.md` §8) — which boxes
 * are back on the utility sketch, and whether one can be asked to point at
 * itself. Pushed, not polled: restores happen on the sidecar's own schedule.
 */
export function useUtilityStatus(): UtilityStatus {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("utility", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getUtility());
}
