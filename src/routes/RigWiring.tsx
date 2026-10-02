import { motion } from "framer-motion";
import { ArrowLeft, CircuitBoard, ListOrdered } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";

import { SkyBackdrop } from "@/components/constellation3d/SkyBackdrop";
import { KindStrip } from "@/components/hardware/KindStrip";
import { Button } from "@/components/common/controls";
import { PinTable } from "@/components/hardware/PinTable";
import { RigWiringEditor } from "@/components/hardware/RigWiringEditor";
import { useRig } from "@/lib/hardware/useRig";
import { springPanel } from "@/lib/motion";

/**
 * Rig wiring — the channel→pin map, on its own page (`settings.md` §5.1).
 *
 * A subpage of Rig rather than a group on it: the editor is a workbench —
 * board map, inspector rail, problems, break preview — and as one section of a
 * scrolling form it fought four neighbours for width and attention. Behind the
 * landing's Wiring door it gets the room, and the landing reads as the HUD of
 * tiles it is. The route nests under `/config` because the subject is the
 * rig's (`App.tsx`).
 *
 * THE PAGE OWNS THE SESSION AND THE SELECTION, the editor and the table rent
 * them: both surfaces must read one document and agree about the selected
 * channel, or clicking a table row and clicking its pin would become two
 * different gestures. The editor's own rules: the map selects and moves, the
 * rail edits, and the save previews what it would break and asks (`RigWiringEditor`).
 */
export function RigWiring() {
  const navigate = useNavigate();
  const rig = useRig();
  const [selected, setSelected] = useState<string | null>(null);

  const doc = rig.doc;
  const channelCount = doc ? Object.keys(doc.channels).length : 0;
  const pinnedCount = doc
    ? Object.values(doc.pins).filter((p) => typeof p?.index === "number").length
    : 0;

  return (
    // Every route sits on the rig's sky — same shell as the Rig landing, so
    // the door and the room behind it read as one place (`SkyBackdrop`).
    <div className="relative h-full">
      <SkyBackdrop />

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        // Owns its own exit: the shell holds every page opaque on the way out
        // now, so anything that should fade has to say so (`AppShell`).
        exit={{ opacity: 0 }}
        transition={springPanel}
        className="scrollbar-none pointer-events-none absolute inset-0 overflow-y-auto"
      >
        {/* Wider than the landing (max-w-5xl): the board map is the point of
            this page, and every column it gains is label legibility. */}
        <section className="pointer-events-auto mx-auto max-w-6xl px-10 py-9">
          <Button variant="ghost" onClick={() => navigate("/config")}>
            <ArrowLeft size={13} strokeWidth={1.75} />
            Rig
          </Button>

          <div className="mt-3 flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
              <CircuitBoard size={18} strokeWidth={1.75} className="text-pulsar" />
            </span>
            <div className="min-w-0 flex-1">
              <h1 className="font-display text-[22px] text-starlight">Wiring</h1>
              <p className="font-mono text-[10px] text-static/70">
                every pin, and what it means — the map every task compiles
                against
              </p>
            </div>
          </div>

          {/* The same strip the landing's door carries, so the door and the
              room agree about what the wiring is made of. It reads the LIVE
              document, unsaved edits included — adding a channel grows its
              segment before the save. */}
          {doc !== null && (
            <div className="mt-4 max-w-[560px]">
              <KindStrip doc={doc} />
            </div>
          )}

          {/* The editor tile. The frosted material is the page's; the editor
              brings its own action strip, board, rail and problem lists. */}
          <div className="hud mt-6 overflow-hidden rounded-md">
            <RigWiringEditor rig={rig} selected={selected} onSelect={setSelected} />
          </div>

          {/* The listing tile — the same document, readable instead of
              spatial. Hidden while nothing is loaded; the editor already
              carries the loading and error states. */}
          {doc !== null && (
            // Mounts once the document lands — animated so the tile joins the
            // settled page instead of popping in under it.
            <motion.section
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={springPanel}
              className="hud mt-6 overflow-hidden rounded-md"
            >
              <div className="flex items-center gap-3 border-b border-halo px-4 py-3">
                <ListOrdered size={18} strokeWidth={1.75} className="shrink-0 text-pulsar" />
                <span className="text-[13px] font-medium text-starlight">
                  Configured pins
                </span>
                <span className="ml-auto shrink-0 font-mono text-[11px] text-static">
                  {channelCount} channel{channelCount === 1 ? "" : "s"} ·{" "}
                  {pinnedCount} pin{pinnedCount === 1 ? "" : "s"}
                </span>
              </div>
              <PinTable doc={doc} selected={selected} onSelect={setSelected} />
            </motion.section>
          )}
        </section>
      </motion.div>
    </div>
  );
}
