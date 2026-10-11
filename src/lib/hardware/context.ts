import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useSyncExternalStore,
} from "react";

import type {
  ConsoleLine,
  DetectedBoard,
  FlashBoxStatus,
  FlashedSketch,
  FlashQueueStatus,
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

/** The sketch the sidecar last flashed to a box's board, or null when that
 *  isn't known (`ARCHITECTURE.md#what-a-board-carries`). */
export function useFlashedSketch(box: number): FlashedSketch | null {
  const store = useHardwareStore();
  const subscribe = useCallback(
    (cb: () => void) => store.subscribe(`flashed:${box}`, cb),
    [store, box],
  );
  return useSyncExternalStore(subscribe, () => store.getFlashed(box));
}

/**
 * Boards the out-of-band poll can currently see (`ARCHITECTURE.md#board-discovery`).
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
 * The hardware utility baseline (`ARCHITECTURE.md#hardware-utility-baseline`) — which boxes
 * are back on the utility sketch, and whether one can be asked to point at
 * itself. Pushed, not polled: restores happen on the sidecar's own schedule.
 */
export function useUtilityStatus(): UtilityStatus {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("utility", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getUtility());
}

/**
 * The rig's one flash queue (`ARCHITECTURE.md#the-flash-queue`): what each box's
 * last flash is doing and what each board carries. Replayed on connect, so a
 * flash keeps reporting after the component that asked for it unmounts.
 */
export function useFlashQueue(): FlashQueueStatus {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("flashes", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getFlashes());
}

/** One box's row of the flash queue. */
export function useBoxFlash(box: number): FlashBoxStatus | null {
  const store = useHardwareStore();
  const subscribe = useCallback((cb: () => void) => store.subscribe("flashes", cb), [store]);
  return useSyncExternalStore(subscribe, () => store.getBoxFlash(box));
}

/**
 * Several boxes' scrollback at once — Debug's all-boxes view, which reads every
 * targeted box's `STATUS` lines and merges their consoles. A hook per box
 * cannot be called in a loop over a changing set, so this subscribes to each
 * box's key and re-reads them all on any change. Each array keeps its own
 * identity until its box's output moves, as `useBoxOutput`'s does.
 */
export function useBoxOutputs(boxes: readonly number[]): ReadonlyMap<number, ConsoleLine[]> {
  return useKeyed(boxes, "output", (store, box) => store.getLines(box));
}

/** What several boxes' boards carry — see `useBoxOutputs`. */
export function useFlashedSketches(
  boxes: readonly number[],
): ReadonlyMap<number, FlashedSketch | null> {
  return useKeyed(boxes, "flashed", (store, box) => store.getFlashed(box));
}

function useKeyed<T>(
  boxes: readonly number[],
  prefix: string,
  read: (store: HardwareStore, box: number) => T,
): ReadonlyMap<number, T> {
  const store = useHardwareStore();
  const [tick, bump] = useReducer((x: number) => x + 1, 0);
  const key = boxes.join(",");
  useEffect(() => {
    const offs = boxes.map((box) => store.subscribe(`${prefix}:${box}`, bump));
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store, key, prefix]);
  return useMemo(
    () => new Map(boxes.map((box) => [box, read(store, box)])),
    // `tick` stands in for the store's contents behind stable references.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [store, key, tick],
  );
}
