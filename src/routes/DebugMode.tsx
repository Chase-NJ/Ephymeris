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
 * Two views under one route. The landing is the user's chosen constellation —
 * every bound box a nicknamed, clickable node whose animation *is* its status.
 * Selecting a node zooms into the detail view: the animated 3D star with the
 * box's identity beside it and every debugging utility beneath, grouped by
 * intent. Escape (or Back, or clicking through) returns to the sky.
 *
 * Selection is deliberately route-local state, not a URL segment: the zoom
 * transition is one continuous scene, and a reload landing on the overview is
 * the right recovery anyway.
 *
 * Mounting triggers a sketch rescan per `arduino-directory.md` §4, so newly
 * added sketches show up without an explicit refresh.
 */
export function DebugMode() {
  const { status } = useSidecar();
  const { settings, refreshSketches } = useSettings();
  const refreshedRef = useRef(false);
  const [selected, setSelected] = useState<number | null>(null);

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
        <AnimatePresence mode="wait" initial={false}>
          {selected === null ? (
            <motion.div
              key="sky"
              // The return leg of the zoom: the sky scales back down from
              // where the node view left it.
              initial={{ opacity: 0, scale: 1.06 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.06 }}
              transition={springPanel}
              className="mt-8"
            >
              <DebugConstellation onSelect={setSelected} />
              <p className="mt-4 text-center text-[11px] text-static">
                Select a box to inspect it.
              </p>
            </motion.div>
          ) : (
            <motion.div
              key={`node-${selected}`}
              // Arriving from the zoom: the detail scene settles in from
              // slightly small, as if the star grew into frame.
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={springPanel}
              className="mt-4"
            >
              <NodeDetail box={selected} onBack={() => setSelected(null)} />
            </motion.div>
          )}
        </AnimatePresence>
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
