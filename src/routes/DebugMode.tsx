import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { NodeDetail } from "@/components/debug/NodeDetail";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { springPanel } from "@/lib/motion";
import { setRigSelection, useRigSelection } from "@/lib/constellations/viewMemory";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Debug (`dashboard.md` §4.2, dashboard.md §4).
 *
 * One continuous scene, not two views — and **not a destination of its own**:
 * there is no nav entry, and the only way in is to select a box on the
 * Dashboard's sky (§3.2). This route is that same sky with the camera flown in
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
 * **The layout is the Dashboard's, deliberately** (§3.3): full-bleed sky with
 * the chrome floating over it. That is what makes the handoff between the two
 * seamless — see the scaffold note on the returned markup.
 *
 * Mounting triggers a sketch rescan per `tasks.md` §2.3, so newly
 * added sketches show up without an explicit refresh.
 */
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

  // A box can be unbound in Config while its detail view is open elsewhere.
  useEffect(() => {
    if (selected !== null && !boundBoxes.includes(selected)) setSelected(null);
  }, [selected, boundBoxes]);

  /*
   * **With no box selected, this route is the Dashboard.** Debug has no nav
   * entry (§3.2) — it is the Dashboard's own sky with the camera flown in, and
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
   */
  useEffect(() => {
    if (selected === null) navigate("/", { replace: true });
  }, [selected, navigate]);

  return (
    // The same scaffold as the Dashboard, on purpose: the sky fills the whole
    // content area and everything else floats over it. Sharing the geometry is
    // what makes Dashboard → Debug seamless — the two views hand the one shared
    // canvas (`SharedCanvas.tsx`) a *pixel-identical* rectangle, so the handoff
    // needs no resize, no aspect change and no reflow. The previous layout (a
    // flex column sizing the canvas to the leftover height) gave it a different
    // rectangle in each view, and resizing the renderer mid-navigation was the
    // jitter this replaced.
    <div className="relative h-full overflow-hidden">
      {/* The sky — outside the entrance animation, for the same reason the
          Dashboard's is: the shared canvas lives in this element, so fading the
          view in would fade the constellation the Dashboard just handed over.
          Only the chrome below animates. */}
      <div className="absolute inset-0">
        <DebugConstellation selected={selected} onSelect={setSelected} />
      </div>

      {/* Header overlay, on the title grid the Dashboard and Mission Control
          share: 32px in, 28px down. */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
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
          and where it gets the Config link to fix it. */}
      <AnimatePresence>
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
