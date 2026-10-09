import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { NodeDetail, PANEL_WIDTH, PANEL_WIDTH_WIDE } from "@/components/debug/NodeDetail";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { springPanel } from "@/lib/motion";
import { setRigSelection, useRigSelection } from "@/lib/constellations/viewMemory";
import { useDeparture } from "@/lib/nav/departure";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Debug (`USER-GUIDE.md#checking-a-box`).
 *
 * One continuous scene, not two views — and **not a destination of its own**:
 * there is no nav entry, and the only way in is to select a box on the
 * Dashboard's sky. This route is that same sky with the camera flown in
 * and the box's utilities docked over it. Escape, Back, or clicking empty space
 * flies the camera back out, which means going back to the Dashboard: an
 * unselected Debug has none of the chrome the Dashboard puts around the sky,
 * and nobody can navigate to it on purpose.
 *
 * Selection lives in the shared rig view-memory, not a URL segment: the
 * Dashboard browses the same sky, so the two views must agree on what is
 * selected. Memory is per-sitting, so a reload arrives with nothing selected —
 * and lands on the Dashboard, which is the right recovery.
 *
 * **The layout is the Dashboard's, deliberately**: full-bleed sky with
 * the chrome floating over it. That is what makes the handoff between the two
 * seamless — see the scaffold note on the returned markup.
 *
 * Mounting triggers a sketch rescan per `TASKS.md#discovery`, so newly
 * added sketches show up without an explicit refresh.
 */

/** The sidebar's width in px — keep in sync with `--spacing-sidebar`. The
 *  scene canvas reaches under the sidebar's glass, so the visible strip of
 *  sky starts at its right edge. */
const SIDEBAR_PX = 200;
/** `NodeDetail`'s `right-4` inset — part of the chrome the panel occupies. */
const PANEL_INSET_PX = 16;

export function DebugMode() {
  const navigate = useNavigate();
  const { status } = useSidecar();
  const { refreshSketches } = useSettings();
  const refreshedRef = useRef(false);
  // Selection is the *rig's*, not this route's (`viewMemory.ts`): the
  // Dashboard browses the same sky, and a box selected there should still be
  // the subject here — that continuity is the point of sharing the scene.
  const selected = useRigSelection();
  const setSelected = setRigSelection;
  // Held here rather than inside `NodeDetail`, which is keyed by box and so
  // remounts on every selection: a utility sketch's controls need the wide
  // panel on box 2 for the same reason they needed it on box 1, and having to
  // re-widen it each time is the kind of small friction that reads as a bug.
  const [wide, setWide] = useState(false);

  useEffect(() => {
    if (status === "connected" && !refreshedRef.current) {
      refreshedRef.current = true;
      void refreshSketches();
    }
  }, [status, refreshSketches]);

  const boundBoxes = useBoundBoxes();

  // A box can be unbound on the Rig tab while its detail view is open elsewhere.
  useEffect(() => {
    if (selected !== null && !boundBoxes.includes(selected)) setSelected(null);
  }, [selected, boundBoxes]);

  /*
   * **With no box selected, this route is the Dashboard.** Debug has no nav
   * entry (`ARCHITECTURE.md#routes`) — it is the Dashboard's own sky with the camera flown in, and
   * the only way in is to select a box. So an unselected Debug is a page nobody
   * can mean to be on: it has a title and a hint and none of the things the
   * Dashboard puts around the same sky. Backing out used to land there, which
   * read as the app losing its chrome.
   *
   * One rule covers every exit — the panel's Back control, Escape, clicking
   * empty space, and a box being unbound out from under an open panel — because
   * all four already funnel through the shared rig selection.
   *
   * `replace`, so the emptied `/debug` entry doesn't stay in history for the
   * browser's own Back button to land on and bounce straight out of again.
   *
   * Guarded on still *being* on `/debug`: route transitions overlap mounts, so
   * this component is still alive while the next route is already showing. The
   * Dashboard clears the rig selection on arrival, which would otherwise fire
   * this redirect from an unmounting Debug and replace a history entry the
   * Dashboard had just taken. The redirect is for exits *from this route*.
   */
  const { pathname } = useLocation();
  useEffect(() => {
    if (selected === null && pathname === "/debug") navigate("/", { replace: true });
  }, [selected, pathname, navigate]);

  /*
   * **A sidebar click leaves the same way Back does** (`lib/nav/departure.ts`).
   *
   * Clearing the selection in the same commit as the navigation starts the
   * fly-out while this page is still on screen, so leaving a star reads as
   * flying out of it. Every exit this route already had does that; the sidebar
   * was the one door that didn't.
   *
   * The redirect above does not race this. Both the clear and the router's own
   * navigation happen in one click handler, so React batches them into a single
   * commit — and this component's `useLocation` reads live context even while it
   * is exiting, so `pathname` is already the destination and the guard is false.
   * That holds for a sidebar target of `/` too, where the two would otherwise
   * both try to land on the Dashboard.
   */
  useDeparture(useCallback(() => setRigSelection(null), []));

  return (
    // The same scaffold as the Dashboard, on purpose: the sky fills the whole
    // content area and everything else floats over it. Sharing the geometry is
    // what makes Dashboard → Debug seamless — the two views hand the one shared
    // canvas (`SharedCanvas.tsx`) a *pixel-identical* rectangle, so the handoff
    // needs no resize, no aspect change and no reflow. The previous layout (a
    // flex column sizing the canvas to the leftover height) gave it a different
    // rectangle in each view, and resizing the renderer mid-navigation was the
    // jitter this replaced.
    // No `overflow-hidden`: it would clip the shared canvas back out of the
    // strip it reaches under the sidebar (`Scene.tsx`).
    <div className="relative h-full">
      {/* The sky — outside the entrance animation, for the same reason the
          Dashboard's is: the shared canvas lives in this element, so fading the
          view in would fade the constellation the Dashboard just handed over.
          Only the chrome below animates. */}
      <div className="absolute inset-0">
        <DebugConstellation
          selected={selected}
          onSelect={setSelected}
          // Centre the focused star in the strip between the sidebar's glass
          // and the docked panel: half the difference between the right-docked
          // chrome (panel + inset) and the left chrome (sidebar). Follows the
          // wide toggle, so widening re-composes the frame on the same ease.
          frameShift={
            ((wide ? PANEL_WIDTH_WIDE : PANEL_WIDTH) + PANEL_INSET_PX - SIDEBAR_PX) / 2
          }
        />
      </div>

      {/* Header overlay, on the title grid the Dashboard and Mission Control
          share: 32px in, 28px down. Owns its own exit because the route stops
          fading the page between here and the Dashboard (`AppShell`). */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="pointer-events-none absolute left-8 right-4 top-7 flex items-start justify-between gap-4"
      >
        <div className="min-w-0">
          <h1 className="font-display text-[22px] text-starlight">Debug</h1>
        </div>
        <span className="pointer-events-auto shrink-0">
          <SidecarStatusPill status={status} />
        </span>
      </motion.div>

      {/* No empty state: an unselected Debug redirects to the Dashboard above,
          and an unbound rig can never have a selection to arrive with. The
          Dashboard's Rig tile is where a rig with nothing bound gets told so,
          and where it gets the Config link to fix it.

          `propagate`: a nested `AnimatePresence` starts its own presence scope,
          so without it leaving the route (by the sidebar, say) never ran the
          panel's `exit` — it sat opaque until the route's other exits settled,
          then vanished in one frame. */}
      <AnimatePresence propagate>
        {selected !== null && (
          <NodeDetail
            key={selected}
            box={selected}
            onBack={() => setSelected(null)}
            wide={wide}
            onToggleWide={() => setWide((current) => !current)}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
