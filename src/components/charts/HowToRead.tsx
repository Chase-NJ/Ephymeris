import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useIsReport } from "@/components/analytics/report/context";
import { springSnappy } from "@/lib/motion";

/**
 * The graph-tile disclosure — "how to read this", folded away until asked.
 *
 * A chart's reading key is useful exactly once per reader and noise every
 * time after; the strategy plane's used to stand taller than the plane
 * itself. So the prose collapses behind one small labelled chevron
 * (`ConfigFields`' advanced-fields idiom), and the tile keeps its data-ink.
 * **Data disclosures stay outside**: "N runs on other tasks" is a fact about
 * what the reader is looking at, not an explanation of how to look, and
 * folding it away would hide data — this component is for education only.
 *
 * In a report sheet the prose renders open with the toggle hidden: paper
 * cannot be clicked, and a printed figure needs its key
 * (`AnimalCard`'s inert-for-export convention, worn the other way around).
 */
export function HowToRead({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const report = useIsReport();
  const expanded = report || open;

  return (
    <div className="mt-2 border-t border-halo pt-1.5">
      {!report && (
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          aria-expanded={expanded}
          className="flex w-fit items-center gap-1 font-mono text-[10px] text-static/70 transition-colors hover:text-starlight"
        >
          <motion.span
            animate={{ rotate: expanded ? 90 : 0 }}
            transition={springSnappy}
            className="flex"
            aria-hidden
          >
            <ChevronRight size={11} strokeWidth={1.75} />
          </motion.span>
          how to read this
        </button>
      )}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={springSnappy}
            className="overflow-hidden"
          >
            <div className="pt-1.5 text-[10px] leading-relaxed text-static/80">
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
