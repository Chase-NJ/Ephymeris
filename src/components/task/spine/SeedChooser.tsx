import { motion } from "framer-motion";
import { ArrowLeft, Compass } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/common/controls";
import { errorMessage } from "@/lib/cohorts/commands";
import { CASCADE, RISE, springPanel } from "@/lib/motion";
import { spinePalette } from "@/lib/taskdef/commands";
import { PHASE_LABEL } from "@/lib/taskdef/spineLabels";
import { seedShapeWords } from "@/lib/taskdef/spineWords";
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
  onGuide,
}: {
  onPick: (definition: TaskDocument) => void;
  onBack: () => void;
  /** Opens the guided first task instead (`SpineGuide`). */
  onGuide: () => void;
}) {
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
          Start from a paradigm. A seed brings the steps of a trial, what each answer means and one block
          of trials. You name each trial type, say which channel on this rig plays each role, then
          change whatever else differs.
        </p>
        <button
          type="button"
          onClick={onGuide}
          className="mt-3 flex items-center gap-1.5 text-[12px] text-pulsar transition-colors hover:text-starlight"
        >
          <Compass size={13} strokeWidth={1.75} />
          New to this? Build a first task step by step
        </button>
        <SeedGrid onPick={onPick} className="mt-6" />
      </section>
    </motion.div>
  );
}

/**
 * The palette's seeds as cards, each with its summary and its steps in words.
 * The seed chooser and the guide's first step both show it.
 */
export function SeedGrid({ onPick, className = "" }: { onPick: (definition: TaskDocument) => void; className?: string }) {
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
    <div className={className}>
        {error && <p className="mt-4 text-[11px] text-status-error">{error}</p>}
        {status !== "connected" && (
          <p className="mt-4 text-[12px] text-static">Waiting for the backend — the seeds come from it.</p>
        )}
        {seeds && (
          <motion.div variants={CASCADE} initial="hidden" animate="shown" className="grid grid-cols-2 gap-3">
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
                  <p className="text-[10px] leading-relaxed text-static/80">
                    <span className="text-static/60">Steps: </span>
                    {def.spine.map((p) => PHASE_LABEL[p.phase] ?? p.phase).join(" → ")}
                  </p>
                  <p className="font-mono text-[9px] tracking-wide text-static/60 uppercase">{seedShapeWords(def)}</p>
                </motion.button>
              );
            })}
          </motion.div>
        )}
    </div>
  );
}
