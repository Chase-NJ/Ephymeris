import { motion } from "framer-motion";
import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { spinePalette } from "@/lib/taskdef/commands";
import { PHASE_LABEL } from "@/lib/taskdef/spineLabels";
import type { SpineDefinition } from "@/lib/taskdef/spine";
import type { TaskDocument } from "@/lib/taskdef/types";
import { useSidecar } from "@/lib/ws/context";
import type { TaskSeed } from "@/lib/ws/protocol";

/**
 * `/task/new`: a new task starts from one of the seed spines
 * (`TASKS.md#the-spine-editor`).
 *
 * The seeds are the sidecar's (`taskdef/seeds.py`, served by
 * `tasks.spinePalette`), the one source. Each carries phases and no names: its
 * rows are unnamed and bound to nothing, so the editor opens with a problem on
 * every row until the operator names it and binds it on this rig. Picking one
 * opens it unsaved, as Duplicate does; nothing is written until Save.
 */
export function SeedChooser({
  onPick,
  onBack,
}: {
  onPick: (definition: TaskDocument) => void;
  onBack: () => void;
}) {
  const { client, status } = useSidecar();
  const [seeds, setSeeds] = useState<TaskSeed[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status !== "connected") return;
    void spinePalette(client)
      .then((reply) => setSeeds(reply.seeds))
      .catch((err) => setError(errorMessage(err)));
  }, [client, status]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={springPanel}
      className="scrollbar-none absolute inset-0 overflow-y-auto"
    >
      <section className="mx-auto max-w-4xl px-10 py-9">
        <div className="flex items-center gap-3">
          <Button variant="ghost" onClick={onBack} title="Back to the task library">
            <ArrowLeft size={13} strokeWidth={1.75} />
          </Button>
          <h1 className="font-display text-[22px] text-starlight">New task</h1>
        </div>
        <p className="mt-3 max-w-prose text-[12px] leading-relaxed text-static">
          Start from the shape of a paradigm. A seed brings its phases, its maps and one block; you
          name each trial type and pick the channels it uses on this rig, then change whatever else
          differs.
        </p>
        {error && <p className="mt-4 text-[11px] text-status-error">{error}</p>}
        {status !== "connected" && (
          <p className="mt-4 text-[12px] text-static">Waiting for the backend — the seeds come from it.</p>
        )}
        {seeds && (
          <motion.div variants={CASCADE} initial="hidden" animate="shown" className="mt-6 grid grid-cols-2 gap-3">
            {seeds.map((seed) => {
              const def = seed.definition as SpineDefinition;
              return (
                <motion.button
                  key={seed.id}
                  variants={RISE}
                  type="button"
                  onClick={() => onPick(structuredClone(def))}
                  className="telemetry flex flex-col items-start gap-2 px-4 py-3 text-left transition-[border-color] hover:!border-pulsar/70"
                >
                  <h2 className="font-display text-[15px] text-starlight">{seed.label}</h2>
                  <p className="text-[12px] leading-relaxed text-static">{seed.summary}</p>
                  <p className="font-mono text-[10px] text-static/80">
                    {def.spine.map((p) => PHASE_LABEL[p.phase] ?? p.phase).join(" → ")}
                  </p>
                  <p className="font-mono text-[9px] tracking-wide text-static/60 uppercase">
                    {def.rows.length} row{def.rows.length === 1 ? "" : "s"} · {def.slots.length} slots
                  </p>
                </motion.button>
              );
            })}
          </motion.div>
        )}
      </section>
    </motion.div>
  );
}
