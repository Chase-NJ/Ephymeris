import { motion } from "framer-motion";
import { ChartLine } from "lucide-react";

import { CohortIcon } from "@/components/cohorts/CohortIcon";
import type { CohortSummary } from "@/lib/cohorts/types";
import { springPanel, springSnappy } from "@/lib/motion";

/**
 * The Analytics entry point (`analytics.md` §2).
 *
 * Deliberately the Cohorts view's card grid rather than a dropdown: picking
 * which cohort to study is the same act as picking one to manage, and the
 * procedural icon is how this lab already recognises a cohort at a glance
 * (`cohorts.md` §5). Reusing it means no new visual language, and no learning
 * a second way to say the same thing.
 *
 * It also gives the dashboard somewhere to come *from*. Auto-selecting the
 * most recent cohort meant the first thing on screen was an answer to a
 * question nobody had asked yet, and the selector that would have changed it
 * was a dropdown in the corner.
 */
export function CohortLanding({
  cohorts,
  onPick,
}: {
  cohorts: CohortSummary[];
  onPick: (cohortId: string) => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={springPanel}
    >
      <div className="flex items-center gap-3">
        <span className="flex size-9 items-center justify-center rounded-md border border-halo bg-nebula">
          <ChartLine size={18} strokeWidth={1.75} className="text-pulsar" />
        </span>
        <div>
          <h1 className="font-display text-[22px] text-starlight">Analytics</h1>
          <p className="mt-0.5 text-[12px] text-static">
            Pick a cohort to study its recorded sessions.
          </p>
        </div>
      </div>

      {cohorts.length === 0 ? (
        <p className="mt-6 max-w-prose text-[13px] leading-relaxed text-static">
          No cohorts yet. Analytics reads sessions that have already run, so
          there is nothing here until one has.
        </p>
      ) : (
        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {cohorts.map((cohort, index) => (
            <motion.button
              key={cohort.id}
              type="button"
              onClick={() => onPick(cohort.id)}
              // Cards arrive in sequence rather than all at once — the same
              // staggered reveal the data itself uses once one is chosen.
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ ...springPanel, delay: index * 0.04 }}
              whileHover={{ y: -3 }}
              whileTap={{ scale: 0.99 }}
              className="surface flex flex-col items-start gap-3 rounded-md border border-halo p-3 text-left transition-colors hover:border-pulsar"
            >
              <CohortIcon
                cohortId={cohort.id}
                animalCount={cohort.animalCount}
                size={48}
              />
              <span className="min-w-0 w-full">
                <span className="block truncate text-[13px] font-medium text-starlight">
                  {cohort.name}
                </span>
                <span className="font-mono text-[10px] text-static">
                  {cohort.animalCount} {cohort.animalCount === 1 ? "animal" : "animals"}
                </span>
              </span>
            </motion.button>
          ))}
        </div>
      )}
    </motion.div>
  );
}

/** The "back to the picker" control, sized to sit inline with the selectors. */
export function ChangeCohort({ name, onBack }: { name: string; onBack: () => void }) {
  return (
    <motion.button
      type="button"
      onClick={onBack}
      whileHover={{ x: -2 }}
      transition={springSnappy}
      className="flex items-center gap-1.5 text-[12px] text-static transition-colors hover:text-starlight"
      title="Choose a different cohort"
    >
      <span aria-hidden>←</span>
      <span className="max-w-[160px] truncate">{name}</span>
    </motion.button>
  );
}
