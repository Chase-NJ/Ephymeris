import { motion } from "framer-motion";
import type { ReactNode, Ref } from "react";

import { PANEL_TRAVEL, springPanel } from "@/lib/motion";

/**
 * The docked-glass shell both detail panes are built on — Debug's `NodeDetail`
 * and Mission Control's `StarPanel`. Shell and section chrome only: what goes
 * *inside* a panel is each view's own business, and the two deliberately do not
 * share content components.
 *
 * `.hud` is the one docked-over-sky material (`index.css`), and the enter/exit
 * is the shared `PANEL_TRAVEL` slide on `springPanel` — a panel and whatever it
 * replaces move the same distance on the same spring, so a star click reads as
 * one surface being swapped.
 *
 * Positioning and width are the caller's: `NodeDetail` docks itself absolutely
 * over the scene, `StarPanel` is a card in Mission Control's rail flow.
 */
export function HudPanel({
  ref,
  className = "",
  layout = false,
  children,
}: {
  /**
   * **Forwarded to the `motion.aside`, and load-bearing.** `StarPanel` sits
   * directly inside an `AnimatePresence mode="popLayout"`, which pins an
   * exiting child out of flow by cloning it with a ref — a shell that swallowed
   * the ref would silently break that exit (see the note on `StarPanel`'s
   * props). React 19 plain-prop ref, exactly as the panels already take it.
   */
  ref?: Ref<HTMLElement> | undefined;
  className?: string;
  /** Animate width/position changes (NodeDetail's wide toggle). */
  layout?: boolean;
  children: ReactNode;
}) {
  return (
    <motion.aside
      ref={ref}
      initial={{ opacity: 0, x: PANEL_TRAVEL }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: PANEL_TRAVEL }}
      transition={springPanel}
      layout={layout}
      className={`hud pointer-events-auto rounded-lg p-4 ${className}`}
    >
      {children}
    </motion.aside>
  );
}

/**
 * One titled section inside a `HudPanel` — the uppercase-header card idiom
 * `NodeDetail`'s groups established. Opaque `surface-inset`, never nested
 * `.hud`: stacking backdrop-filters is counterproductive (`index.css`).
 *
 * `headerRight` puts actions on the header line (copy/save buttons and the
 * like); a section with neither title nor actions renders no header at all,
 * for callers that own their own header row (the console's tab bar).
 */
export function HudSection({
  title,
  headerRight,
  className = "",
  children,
}: {
  title?: string;
  headerRight?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`surface-inset overflow-hidden rounded-md ${className}`}>
      {(title || headerRight) && (
        <div className="flex items-center border-b border-halo">
          {title && (
            <h3 className="px-3 py-2 text-[11px] font-medium tracking-[0.08em] text-static uppercase">
              {title}
            </h3>
          )}
          {headerRight && (
            <div className="ml-auto flex items-center gap-1 pr-2">{headerRight}</div>
          )}
        </div>
      )}
      {children}
    </section>
  );
}
