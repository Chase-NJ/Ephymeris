import { AnimatePresence, motion } from "framer-motion";
import { Settings as SettingsIcon, Terminal } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import { Button } from "@/components/common/controls";
import { DebugConstellation } from "@/components/debug/DebugConstellation";
import { NodeDetail } from "@/components/debug/NodeDetail";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { springPanel } from "@/lib/motion";
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
 * Selection is deliberately route-local state, not a URL segment: the flight is
 * one continuous move, and a reload landing on the overview is the right
 * recovery anyway.
 *
 * Mounting triggers a sketch rescan per `arduino-directory.md` §4, so newly
 * added sketches show up without an explicit refresh.
 */
export function DebugMode() {
  const { status } = useSidecar();
  const { settings, refreshSketches } = useSettings();
  const refreshedRef = useRef(false);
  const [selected, setSelected] = useState<number | null>(null);
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
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="px-8 py-8"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="font-display text-[22px] text-starlight">Debug</h1>
          {selected === null && constellation && (
            <span className="font-mono text-[11px] text-static">{constellation.name}</span>
          )}
        </div>
        <SidecarStatusPill status={status} />
      </div>

      {boundBoxes.length === 0 ? (
        <NoBoundBoxes configuredCount={settings.boxes.length} />
      ) : (
        <>
          {/* Sized like Mission Control's, and for the same reason: the
              constellation is the view's subject rather than a thumbnail above
              the real controls. Viewport-relative so a large lab monitor gets a
              genuinely cinematic scene, with a floor that keeps it usable on a
              laptop. Unframed like Mission Control's too: the transparent,
              edge-faded canvas (Scene.tsx) joins the page background, and a
              border would put the tile wall back. */}
          <div className="relative mt-5 h-[min(70vh,760px)] min-h-[480px] overflow-hidden">
            <DebugConstellation selected={selected} onSelect={setSelected} />
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
          {selected === null && (
            <p className="mt-3 text-[11px] text-static">
              Select a box to inspect it.
            </p>
          )}
        </>
      )}
    </motion.section>
  );
}

function NoBoundBoxes({ configuredCount }: { configuredCount: number }) {
  const navigate = useNavigate();

  return (
    <div className="mt-6 flex max-w-xl flex-col items-start gap-3">
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
