import { motion } from "framer-motion";
import { useState } from "react";

import { NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The "+ New Cohort" tile — `cohorts.md` §4.
 *
 * Always first in the grid and visually distinct rather than just another card:
 * a dashed Halo border instead of solid, and a single dim slowly-pulsing star
 * instead of a full generated system — a nebula that hasn't collapsed into a
 * star system yet. Hover brightens the pulse.
 */
export function NewCohortTile({ onClick }: { onClick: () => void }) {
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
      className="flex flex-col items-start gap-3 rounded-md border border-dashed border-halo bg-nebula/40 p-4 text-left"
    >
      <span className="flex size-[56px] items-center justify-center">
        <svg viewBox="0 0 100 100" width={56} height={56} aria-hidden>
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

      <span>
        <span className="block text-[13px] font-medium text-starlight">
          + New Cohort
        </span>
        {/* Sits in the same slot as the sibling cards' "N animals · N groups",
            so it has to read as an invitation rather than as this tile's own
            status — "nothing here yet" next to populated cohorts reads like a
            failed load. */}
        <span className="mt-0.5 block font-mono text-[11px] text-static">
          animals &amp; groups
        </span>
      </span>
    </motion.button>
  );
}
