import { useEffect } from "react";

/**
 * "Before you take me off this screen, let me start leaving" — registered by a
 * view, run by the sidebar.
 *
 * This exists for exactly one thing: the constellation views' fly-out. Clearing
 * the focus **in the same commit as the navigation** starts the eased move while
 * the page is still on screen, so leaving a star reads as flying out of it
 * rather than as arriving somewhere else already pulled back. Debug's own Back
 * control gets that for free, because clearing the selection *is* how it
 * navigates; a sidebar click gets nothing, since `NavLink` navigates
 * synchronously with no state change at all.
 *
 * So a view registers what it would do if the user had pressed its own Back,
 * and the sidebar presses it on the way past. Module state plus a single slot,
 * the same shape as `unsavedGuard` beside it, because a view deep in the tree
 * has to tell persistent chrome something and there is no shared provider
 * between them.
 *
 * **Last writer wins, and the unregister is guarded on still holding the slot.**
 * Route transitions overlap mounts, so an outgoing view's cleanup routinely runs
 * *after* the incoming view has already registered. An unconditional clear there
 * would leave the new view's departure unregistered for as long as it is on
 * screen.
 *
 * > [!NOTE]
 * > This is **not** a general navigation-coordination mechanism, and it should
 * > not grow into one. It is synchronous and fire-and-forget: there is no way
 * > to defer a navigation, no async path, and no ordering guarantee beyond
 * > "runs before the router does". A view that needs to *stop* a navigation
 * > wants `unsavedGuard`; a view that needs to await something wants neither.
 */

let departure: (() => void) | null = null;

/** Register `fn` as the current screen's departure, returning its unregister. */
export function setDeparture(fn: () => void): () => void {
  departure = fn;
  return () => {
    // Only if we still hold the slot — a view that took over from us owns it.
    if (departure === fn) departure = null;
  };
}

/** Run the current screen's departure, if it registered one. */
export function runDeparture(): void {
  departure?.();
}

/**
 * Register a departure for as long as this component is mounted.
 *
 * `fn` is read through the effect's dependency, so pass a stable callback (a
 * `useCallback`, or a bare setter) rather than an inline closure over changing
 * state — otherwise every render re-registers, which is harmless but pointless.
 */
export function useDeparture(fn: () => void): void {
  useEffect(() => setDeparture(fn), [fn]);
}
