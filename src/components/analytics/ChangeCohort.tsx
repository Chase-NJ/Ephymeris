import { motion } from "framer-motion";
import { ArrowLeft, Orbit } from "lucide-react";
import type { ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/**
 * The way back from a chosen cohort to the cohort list (`CohortManifest`),
 * which Analytics and Log open on.
 */

/**
 * The "back to the picker" control — a breadcrumb, not a caption.
 *
 * This used to render `← {cohort name}`, which named the wrong thing: an
 * arrow beside the *current* cohort's name reads as "you are here", and
 * nothing on screen said where clicking would go. An affordance is only as
 * good as the destination it names, so the clickable part now says
 * **All cohorts** — the same wording the cohort editor's back button uses —
 * with the orbit mark of the cohort list it returns to, and the current
 * cohort's name follows as plain text. `[◍ All cohorts] / The Remy's` is the
 * standard breadcrumb grammar: the link goes up, the label states where you
 * are.
 */
export function ChangeCohort({
  name,
  disc,
  onBack,
}: {
  name: string;
  /** The cohort's world, small — `PlanetDisc` at 16px — so the breadcrumb
   *  names the cohort the way the list it returns to does. */
  disc?: ReactNode;
  onBack: () => void;
}) {
  return (
    <span className="mt-1 flex items-center gap-2 text-[12px]">
      <motion.button
        type="button"
        onClick={onBack}
        whileHover={{ x: -2 }}
        whileTap={{ scale: 0.98 }}
        transition={springSnappy}
        // The group class carries the hover to the arrow: the chip brightens
        // and the arrow leans into the direction travel will happen.
        className="group flex items-center gap-1.5 rounded-sm border border-halo bg-nebula px-2 py-1 text-static transition-colors hover:border-static/70 hover:bg-halo/50 hover:text-starlight"
        title="Back to the cohort list"
      >
        <ArrowLeft
          size={12}
          strokeWidth={1.75}
          className="transition-transform group-hover:-translate-x-0.5"
        />
        <Orbit size={12} strokeWidth={1.75} />
        All cohorts
      </motion.button>
      <span aria-hidden className="text-static/50">
        /
      </span>
      {disc && <span className="flex shrink-0 items-center">{disc}</span>}
      <span className="max-w-[180px] truncate text-starlight">{name}</span>
    </span>
  );
}
