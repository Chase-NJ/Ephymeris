import { motion } from "framer-motion";
import { Settings as SettingsIcon, Terminal } from "lucide-react";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/common/controls";
import { ConsolePanel } from "@/components/debug/ConsolePanel";
import { SidecarStatusPill } from "@/components/common/SidecarStatusPill";
import { springPanel } from "@/lib/motion";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";

/**
 * Debug Mode (`hardware-interaction.md` §6.6, ephymeris_v1.0.md §4.3): a
 * console panel per bound box.
 *
 * Only boxes bound to a board get a panel. "Bound" means *configured with a
 * hardware id*, not *currently detected* — a box whose board is unplugged keeps
 * its panel, since that's exactly where its scrollback and any ERROR state need
 * to stay visible.
 *
 * Mounting triggers a sketch rescan per `arduino-directory.md` §4, so newly
 * added sketches show up without an explicit refresh.
 */
export function DebugMode() {
  const { status } = useSidecar();
  const { settings, refreshSketches } = useSettings();
  const refreshedRef = useRef(false);

  useEffect(() => {
    if (status === "connected" && !refreshedRef.current) {
      refreshedRef.current = true;
      void refreshSketches();
    }
  }, [status, refreshSketches]);

  const boundBoxes = useBoundBoxes();

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="px-8 py-8"
    >
      <div className="flex items-center justify-between">
        <h1 className="font-display text-[22px] text-starlight">Debug Mode</h1>
        <SidecarStatusPill status={status} />
      </div>

      {boundBoxes.length === 0 ? (
        <NoBoundBoxes configuredCount={settings.boxes.length} />
      ) : (
        <div className="mt-5 grid grid-cols-1 gap-3 xl:grid-cols-2">
          {boundBoxes.map((box) => (
            <ConsolePanel key={box} box={box} />
          ))}
        </div>
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
          ? "No boxes are set up yet. Add a box in Settings and bind it to a connected board — its console appears here."
          : `${configuredCount === 1 ? "One box is" : `${configuredCount} boxes are`} configured but not bound to a board yet. Bind one in Settings to get a console.`}
      </p>
      <Button onClick={() => navigate("/settings")}>
        <SettingsIcon size={13} strokeWidth={1.75} />
        Open Settings
      </Button>
    </div>
  );
}
