import { AnimatePresence, motion } from "framer-motion";
import { Settings as SettingsIcon, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { NodeDetail } from "@/components/debug/NodeDetail";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { springPanel } from "@/lib/motion";
import { setRigSelection, useRigSelection } from "@/lib/constellations/viewMemory";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { zodiacById } from "@/lib/constellations/zodiac";
import { useSidecar } from "@/lib/ws/context";

/**
 * Debug (`hardware-interaction.md` §6.6, ephymeris_v1.0.md §4.3).
 *
 * One continuous scene, not two views. The landing is the user's chosen
 * constellation in 3D — every bound box a nicknamed star whose colour is its
 * health and whose animation *is* its status — browsed with the same camera,
 * controls and grammar as Mission Control's session view. Selecting a star
 * flies the camera to it and docks that box's utilities over the still-running
 * scene; Escape, Back, or clicking empty space flies back out.
 *
 * Selection lives in the shared rig view-memory, not a URL segment: the
 * Dashboard browses the same sky, so the two views must agree on what is
 * selected — and memory is per-sitting, so a reload landing on the overview
 * is still the right recovery.
 *
 * **The layout is the Dashboard's, deliberately** (§3.3): full-bleed sky with
 * the chrome floating over it. That is what makes the handoff between the two
 * seamless — see the scaffold note on the returned markup.
 *
 * Mounting triggers a sketch rescan per `arduino-directory.md` §4, so newly
 * added sketches show up without an explicit refresh.
 */
export function DebugMode() {
  const { status } = useSidecar();
  const { settings, refreshSketches } = useSettings();
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
  const constellation = zodiacById(settings.constellation);

  // A box can be unbound in Config while its detail view is open elsewhere.
  useEffect(() => {
    if (selected !== null && !boundBoxes.includes(selected)) setSelected(null);
  }, [selected, boundBoxes]);

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
          <div className="flex items-baseline gap-3">
            <h1 className="font-display text-[22px] text-starlight">Debug</h1>
            {selected === null && constellation && (
              <span className="font-mono text-[11px] text-static">{constellation.name}</span>
            )}
          </div>
          {/* A subtitle rather than the footer line it used to be — the footer
              was the last thing forcing the boxed-canvas layout. Kept in the
              flow (`invisible`, not unmounted) so the header never reflows as
              a selection comes and goes. */}
          {boundBoxes.length > 0 && (
            <p
              className={`mt-1 text-[11px] text-static ${
                selected === null ? "" : "invisible"
              }`}
            >
              Select a box to inspect it.
            </p>
          )}
        </div>
        <span className="pointer-events-auto shrink-0">
          <SidecarStatusPill status={status} />
        </span>
      </motion.div>

      {boundBoxes.length === 0 ? (
        // The sky stays up behind the notice — an unbound rig still shows its
        // chosen asterism as scenery, exactly as the Dashboard does, so the
        // page never collapses to a wall of text on a blank background.
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={springPanel}
          className="absolute left-8 top-24 w-[392px]"
        >
          <NoBoundBoxes configuredCount={settings.boxes.length} />
        </motion.div>
      ) : (
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
      )}
    </div>
  );
}

function NoBoundBoxes({ configuredCount }: { configuredCount: number }) {
  const navigate = useNavigate();

  return (
    // A HUD tile at the Dashboard's column width, not a bare paragraph — the
    // two views keep one visual grammar even in their empty states.
    <div className="hud flex flex-col items-start gap-3 rounded-md p-4">
      <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
        <Terminal size={18} strokeWidth={1.75} className="text-pulsar" />
      </span>
      <p className="text-[13px] leading-relaxed text-static">
        {configuredCount === 0
          ? "No boxes are set up yet. Add a box in Config and bind it to a connected board — its console appears here."
          : `${configuredCount === 1 ? "One box is" : `${configuredCount} boxes are`} configured but not bound to a board yet. Bind one in Config to get a console.`}
      </p>
      <Button onClick={() => navigate("/config")}>
        <SettingsIcon size={13} strokeWidth={1.75} />
        Open Config
      </Button>
    </div>
  );
}
