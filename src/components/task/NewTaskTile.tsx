import { motion } from "framer-motion";
import { useState } from "react";

import { NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The "+ New Task" tile — always first in the Task landing's grid.
 *
 * A dashed border and one dim pulsing point where a populated card carries its
 * glyph. The cohort browser makes the same offer as an unformed world at the
 * centre of its sky (`CohortSky`'s protoplanetary disc) — same grammar, one
 * dimension up: an operator who has learned "the dim unresolved one makes a
 * new thing" should not have to learn it twice.
 *
 * A tile rather than a toolbar button because it is one of the grid's cells —
 * "make another" belongs beside the ones that exist, at their size.
 */
export function NewTaskTile({ onClick }: { onClick: () => void }) {
  const reduceMotion = useReduceMotion();
  const [hovered, setHovered] = useState(false);

  const base = hovered ? 0.85 : 0.45;

  return (
    <motion.button
      type="button"
      onClick={onClick}
      onHoverStart={() => setHovered(true)}
      onHoverEnd={() => setHovered(false)}
      whileHover={{ y: -3, scale: 1.015 }}
      whileTap={{ scale: 0.995 }}
      transition={springSnappy}
      // The saved cards' proportions — glyph-sized header, hairline, a body —
      // on a dashed hairline instead of a solid one, so it sits in the grid
      // as one of them rather than as a different kind of tile.
      className="flex h-full flex-col rounded-md border border-dashed border-halo bg-nebula/40 text-left"
    >
      <span className="flex items-center gap-3 px-3.5 pb-2.5 pt-3">
        <span className="flex size-[44px] shrink-0 items-center justify-center">
        <svg viewBox="0 0 100 100" width={44} height={44} aria-hidden>
          {/* One point and no ring: a task with no conditions and no ramp yet,
              drawn in the same grammar `TaskGlyph` uses for the finished
              thing. */}
          {reduceMotion ? (
            <circle cx={50} cy={50} r={5} fill={NODE_PRIMARY} opacity={base} />
          ) : (
            <motion.circle
              cx={50}
              cy={50}
              r={5}
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
          <span className="block font-display text-[13px] font-medium text-starlight">
            + New Task
          </span>
          <span className="mt-0.5 block font-mono text-[9px] uppercase tracking-wide text-static/70">
            from scratch
          </span>
        </span>
      </span>
      {/* Same slot as a sibling card's fact line, so it has to read as an
          invitation rather than as this tile's own status. */}
      <span className="mt-auto block border-t border-dashed border-halo px-3.5 py-2.5 text-[11px] leading-snug text-static">
        Trial types, a ramp if you want one, and the numbers.
      </span>
    </motion.button>
  );
}
