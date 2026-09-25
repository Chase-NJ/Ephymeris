import { motion } from "framer-motion";
import { useState } from "react";

import { NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The "+ New task" row — always first in the Task landing's list.
 *
 * One dim pulsing point where a saved row carries its glyph. The cohort browser
 * makes the same offer as an unformed world at the centre of its sky
 * (`CohortSky`'s protoplanetary disc) — same grammar, one dimension up: an
 * operator who has learned "the dim unresolved one makes a new thing" should
 * not have to learn it twice.
 *
 * A row rather than a toolbar button because "make another" belongs beside the
 * ones that exist, at their size.
 */
export function NewTaskRow({ onClick }: { onClick: () => void }) {
  const reduceMotion = useReduceMotion();
  const [hovered, setHovered] = useState(false);

  const base = hovered ? 0.85 : 0.45;

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className="flex w-full items-center gap-4 py-2.5 pl-4 pr-4 text-left transition-colors hover:bg-nebula/60"
    >
      <span className="flex size-[32px] shrink-0 items-center justify-center">
        <svg viewBox="0 0 100 100" width={32} height={32} aria-hidden>
          {/* One point and no ring: a task with no conditions and no ramp yet,
              drawn in the same grammar `TaskGlyph` uses for the finished
              thing. */}
          {reduceMotion ? (
            <circle cx={50} cy={50} r={6} fill={NODE_PRIMARY} opacity={base} />
          ) : (
            <motion.circle
              cx={50}
              cy={50}
              r={6}
              fill={NODE_PRIMARY}
              animate={{ opacity: [base, base * 0.35, base] }}
              transition={{
                duration: hovered ? 1.6 : 3.2,
                repeat: Infinity,
                ease: "easeInOut",
              }}
            />
          )}
        </svg>
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] font-medium text-starlight">+ New task</span>
        <span className="mt-0.5 block font-mono text-[9px] uppercase tracking-wide text-static/70">
          from scratch — or duplicate one below
        </span>
      </span>
    </button>
  );
}
