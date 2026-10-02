import { useCallback, useEffect, useSyncExternalStore } from "react";

/**
 * "This screen has unsaved work" — registered by an editor, read by the
 * sidebar (`USER-GUIDE.md#setting-up-a-cohort`).
 *
 * The cohort editor holds an entire roster in local component state and only
 * persists on Save. Every sidebar click is an unconditional immediate unmount,
 * so one mis-click discarded names, cages, boxes and groups with no warning and
 * nothing to recover from — `/cohorts/new` has no server copy to refetch.
 *
 * **Why this and not `useBlocker`.** React Router's navigation blocker requires
 * a *data* router (`createHashRouter` + `RouterProvider`); the app mounts
 * `<HashRouter><Routes>`, where the hook throws. Migrating the router to gain
 * one confirmation dialog is a much larger change than the problem warrants,
 * and it would put every route's transition through a different code path than
 * the one `AppShell` was built and tuned against.
 *
 * So this guards the door that is actually being reported: **sidebar clicks**.
 * Module state plus subscribers, the same shape as `viewMemory`'s rig
 * selection, because an editor deep in the tree has to tell persistent chrome
 * something and there is no shared provider between them.
 *
 * > [!NOTE]
 * > This does **not** cover the browser's own Back, an in-app `navigate()` from
 * > somewhere else, or closing the window. Those need the router migration
 * > above (or `beforeunload`), and none of them is how this loss actually
 * > happens — the report was a sidebar click, and the sidebar is on every
 * > screen.
 *
 * Keyed so a stale registration can't outlive its editor: an editor registers
 * under its own id and clears on unmount.
 */

const dirty = new Set<string>();
const subscribers = new Set<() => void>();

function notify(): void {
  for (const cb of subscribers) cb();
}

/** Mark (or clear) a screen as holding unsaved work. */
export function setUnsaved(id: string, isDirty: boolean): void {
  const had = dirty.has(id);
  if (isDirty === had) return;
  if (isDirty) dirty.add(id);
  else dirty.delete(id);
  notify();
}

export function hasUnsaved(): boolean {
  return dirty.size > 0;
}

function subscribe(cb: () => void): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

/** Whether anything on screen is holding unsaved work. */
export function useUnsaved(): boolean {
  return useSyncExternalStore(subscribe, hasUnsaved, () => false);
}

/**
 * Register this screen's dirty state for as long as it is mounted, clearing it
 * on unmount so a discarded editor can't leave the app permanently guarded.
 */
export function useRegisterUnsaved(id: string, isDirty: boolean): void {
  useEffect(() => {
    setUnsaved(id, isDirty);
  }, [id, isDirty]);

  const clear = useCallback(() => setUnsaved(id, false), [id]);
  useEffect(() => clear, [clear]);
}
