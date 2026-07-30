import { useCallback, useSyncExternalStore } from "react";

/**
 * Where the constellation browser was left — per subject, across views
 * (`ephymeris_v1.0.md` §3.3, §4.3).
 *
 * The 3D constellation now appears on more than one page (Dashboard and Debug
 * both browse the rig), and the illusion those views sell is that they are
 * windows onto *one* sky. A camera that snapped back to the overview on every
 * navigation would break that instantly — so the camera pose and the selected
 * star live here, keyed by what the scene is *of* ("rig", or a cohort id), and
 * every view showing that subject reads and writes the same entry.
 *
 * Module state, deliberately not persisted to disk: continuity is a property
 * of one sitting. A fresh app launch starting at the overview is correct — it
 * is the *within-session* snap-back that would read as a glitch.
 */

export interface SavedView {
  position: [number, number, number];
  target: [number, number, number];
  /** What was focused when the view was left — lets the scene skip the
   *  fly-to-overview a bare mount would otherwise perform. */
  focusedId: string | null;
}

const views = new Map<string, SavedView>();

export function saveView(key: string, view: SavedView): void {
  views.set(key, view);
}

export function loadView(key: string): SavedView | null {
  return views.get(key) ?? null;
}

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
