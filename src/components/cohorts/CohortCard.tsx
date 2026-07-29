import { motion } from "framer-motion";
import { CircleAlert } from "lucide-react";
import { useState } from "react";

import { useBoxAvailability } from "@/lib/cohorts/boxAvailability";
import { springSnappy } from "@/lib/motion";
import type { CohortSummary } from "@/lib/cohorts/types";
import { CohortIcon } from "./CohortIcon";

/**
 * A cohort in the browser grid — `cohorts.md` §4.
 *
 * Nebula surface + Halo hairline + `md` radius, consistent with every other
 * elevated surface. Name in Inter (Space Grotesk stays confined to section
 * headers per the typography rule), stat line in JetBrains Mono since that's
 * the app's convention for compact data readouts.
 *
 * Carries a quiet warning when one of the cohort's boxes isn't available on
 * this machine — the grid is where someone looks before starting a session,
 * so it's the last useful moment to find out before the mapping step.
 */
export function CohortCard({
  cohort,
  onOpen,
}: {
  cohort: CohortSummary;
  onOpen: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const { statusOf } = useBoxAvailability();
  const unavailable = cohort.assignedBoxes.filter((b) => statusOf(b) !== "available");

  return (
    <motion.button
      type="button"
      onClick={onOpen}
      onHoverStart={() => setHovered(true)}
      onHoverEnd={() => setHovered(false)}
      whileHover={{ y: -3, scale: 1.015 }}
      whileTap={{ scale: 0.995 }}
      transition={springSnappy}
      className="surface flex flex-col items-start gap-3 rounded-md p-4 text-left"
    >
      {/* Shared element with the editor header — the icon flies into place
          rather than the view simply cutting. */}
      <motion.span layoutId={`cohort-icon-${cohort.id}`} transition={springSnappy}>
        <CohortIcon
          cohortId={cohort.id}
          animalCount={cohort.animalCount}
          size={56}
          lively={hovered}
        />
      </motion.span>

      <span className="min-w-0 w-full">
        <span className="block truncate text-[13px] font-medium text-starlight">
          {cohort.name}
        </span>
        <span className="mt-0.5 block font-mono text-[11px] text-static">
          {cohort.animalCount} {cohort.animalCount === 1 ? "animal" : "animals"}
          {cohort.groupCount > 1 && ` · ${cohort.groupCount} groups`}
        </span>
        {unavailable.length > 0 && (
          <span
            className="mt-1 flex items-center gap-1 text-[11px]"
            style={{ color: "var(--color-status-warning)" }}
            title={`Assigned to ${
              unavailable.length === 1 ? "a box" : "boxes"
            } this machine can't reach: ${unavailable.join(", ")}`}
          >
            <CircleAlert size={11} strokeWidth={2} className="shrink-0" />
            <span className="font-mono">
              box {unavailable.join(", ")} unavailable
            </span>
          </span>
        )}
      </span>
    </motion.button>
  );
}
