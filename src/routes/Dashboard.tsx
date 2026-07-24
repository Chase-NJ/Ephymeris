import { motion } from "framer-motion";
import { ArrowRight, ChartLine, Terminal, Users } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { LucideIcon } from "lucide-react";

import { springPanel, springSnappy } from "@/lib/motion";
import { useCohortCount } from "@/lib/cohorts/context";
import { useBoundBoxes } from "@/lib/settings/context";

/**
 * Dashboard / landing view (ephymeris_v1.0.md §3.3).
 *
 * Hero CTA over a three-tile row. Settings is intentionally not a tile — it
 * lives in one fixed, always-reachable place in the sidebar rather than as
 * browsable content (§3.2).
 */
export function Dashboard() {
  const navigate = useNavigate();
  const cohortCount = useCohortCount();
  const boundBoxes = useBoundBoxes();

  // §4.1: starting a session requires an existing cohort — now a live check
  // against the real cohort count rather than a hardcoded always-zero.
  //
  // Deliberately still only an *existence* check. "Ready to run" is now defined
  // (`starting-a-session.md` §1) but is a per-cohort property, and the CTA isn't
  // scoped to a cohort yet — Step 1 is where a cohort gets picked, so that's
  // where the readiness check belongs and where it lives.
  const hasCohorts = cohortCount > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={springPanel}
      className="mx-auto max-w-4xl px-10 py-9"
    >
      <h1 className="font-display text-[22px] text-starlight">Dashboard</h1>

      <motion.button
        type="button"
        whileHover={{ y: -2 }}
        whileTap={{ scale: 0.995 }}
        transition={springSnappy}
        onClick={() => navigate(hasCohorts ? "/session/new" : "/cohorts")}
        className="mt-6 flex w-full items-center justify-between rounded-lg bg-pulsar px-6 py-5 text-left"
      >
        <span>
          <span className="block font-display text-lg font-semibold text-void">
            {hasCohorts ? "Start a Session" : "Create a cohort to get started"}
          </span>
          <span className="mt-0.5 block text-[12px] text-void/70">
            {hasCohorts
              ? "Configure boxes and begin data collection"
              : "Sessions run against a cohort — you'll need one first"}
          </span>
        </span>
        <ArrowRight size={20} strokeWidth={2} className="shrink-0 text-void" />
      </motion.button>

      <div className="mt-5 grid grid-cols-3 gap-3">
        <Tile
          icon={Users}
          label="Cohorts"
          status={`${cohortCount} active`}
          onClick={() => navigate("/cohorts")}
        />
        <Tile
          icon={ChartLine}
          label="Analytics"
          status="view"
          onClick={() => navigate("/analytics")}
        />
        <Tile
          icon={Terminal}
          label="Debug Mode"
          status={
            boundBoxes.length === 0
              ? "no boxes"
              : `${boundBoxes.length} ${boundBoxes.length === 1 ? "box" : "boxes"}`
          }
          onClick={() => navigate("/debug")}
        />
      </div>
    </motion.div>
  );
}

function Tile({
  icon: Icon,
  label,
  status,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  status: string;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.99 }}
      transition={springSnappy}
      className="surface group flex flex-col items-start gap-3 rounded-md p-4 text-left"
    >
      <Icon size={18} strokeWidth={1.75} className="text-pulsar" />
      <span>
        <span className="block text-[13px] font-medium text-starlight">{label}</span>
        <span className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-static">
          {status}
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </span>
    </motion.button>
  );
}
