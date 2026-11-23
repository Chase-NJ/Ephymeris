import { useCallback, useSyncExternalStore } from "react";

/**
 * What the rig has selected, shared across the views that browse it
 * (`ARCHITECTURE.md#one-sky`).
 *
 * > [!NOTE]
 * > **This used to hold the camera pose as well**, keyed by what the scene was
 * > *of*, so an arriving view could restore where the last one left off. It
 * > doesn't any more, and the field should not come back: the camera is a single
 * > permanent object that no view mounts or unmounts
 * > (`constellation3d/Scene.tsx`), so there is nothing to save and nothing to
 * > restore. It simply stays where it was.
 *
 * Module state, deliberately not persisted to disk: continuity is a property
 * of one sitting.
 */

/**
 * The rig's selected box — shared by every view that browses the rig, so a
 * box selected in Debug is still the subject when the Dashboard's scene shows
 * the same sky (and vice versa).
 */
let rigSelection: number | null = null;
const rigSubs = new Set<() => void>();

export function setRigSelection(box: number | null): void {
  if (rigSelection === box) return;
  rigSelection = box;
  for (const cb of rigSubs) cb();
}

export function getRigSelection(): number | null {
  return rigSelection;
}

export function useRigSelection(): number | null {
  const subscribe = useCallback((cb: () => void) => {
    rigSubs.add(cb);
    return () => {
      rigSubs.delete(cb);
    };
  }, []);
  return useSyncExternalStore(subscribe, getRigSelection);
}
