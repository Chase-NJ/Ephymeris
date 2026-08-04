import { motion } from "framer-motion";
import { Fragment } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import { springPanel, springSnappy } from "@/lib/motion";

/**
 * The task wizard's guided progress rail.
 *
 * DELIBERATELY THE SAME OBJECT AS `SessionJourney`, because designing a task and
 * setting up a session are the same kind of thing to an operator: a short guided
 * walk with a known end, on the rig's own sky. Steps are constellation stars
 * joined by a path — completed lit Pulsar, current pulsing in Starlight (opacity
 * and a flat expanding ring, no blur, since the palette's no-glow rule holds),
 * upcoming as Halo outlines — with one hint line beneath naming the next action.
 *
 * WHAT IS NOT SHARED IS THE STEP LIST. The session flow's four steps are fixed;
 * this one's are six or seven depending on whether the paradigm asks anything,
 * so the labels arrive as a prop and the caller owns which of them exist. That
 * also keeps this file from having to know what a paradigm is.
 */

/**
 * Fixed, not `flex-1`.
 *
 * `SessionJourney` learned this the hard way across three hosts of different
 * widths: stretchy connectors made any change to the surrounding content box
 * redistribute across every gap at once, so a panel landing a beat after the
 * route did read as the bar resizing itself. Here there is one host, but the
 * step COUNT changes — six from scratch, seven from a paradigm that asks — and
 * a fixed connector means that difference moves the bar's width and nothing
 * else. 8 × 20 + 7 × 52 = 524px, inside the column with room to spare.
 */
const CONNECTOR = 52;

/** How much the rail shrinks once the walk is over. See `SessionJourney`. */
const COMPACT_SCALE = 0.84;

export function TaskJourney({
  labels,
  active,
  hint,
  settled = false,
}: {
  /** One per star, in order. The caller decides which steps exist. */
  labels: string[];
  /** 0-based index of the current star. */
  active: number;
  hint: string;
  /**
   * The walk is over — Review. The rail scales down toward its top centre, the
   * same "still present, no longer the subject" move the session flow makes on
   * arriving at Mission Control.
   */
  settled?: boolean;
}) {
  return (
    <motion.div layout transition={springPanel} className="mx-auto mb-7">
      <motion.div
        animate={{ scale: settled ? COMPACT_SCALE : 1 }}
        transition={springPanel}
        style={{ transformOrigin: "top center" }}
      >
        <div className="flex items-start justify-center">
          {labels.map((label, i) => (
            <Fragment key={label}>
              {i > 0 && (
                <motion.div
                  layout
                  transition={springPanel}
                  // `shrink-0` is what makes the fixed width fixed: a flex item
                  // with a width and no shrink guard still gives it up under
                  // pressure, which is the stretchiness this replaced wearing a
                  // different hat.
                  className="mt-[9px] h-px shrink-0"
                  style={{
                    width: CONNECTOR,
                    background: LINK_STROKE,
                    opacity: i <= active ? LINK_OPACITY_LIVE : LINK_OPACITY_DIM,
                  }}
                />
              )}
              <StepStar
                label={label}
                state={i < active ? "done" : i === active ? "active" : "ahead"}
              />
            </Fragment>
          ))}
        </div>

        {/* The hint reserves two lines' worth rather than taking the space when
            it has something to say. These are prose that gets edited, and a
            wrap that only shows up on one step would push the whole column
            down on arriving at it. Cheaper to hold the space. */}
        <div className="mt-8 min-h-[33px] text-center">
          {/*
           * ENTER-ONLY, and not the `AnimatePresence mode="wait"` crossfade
           * `SessionJourney` uses for the same line.
           *
           * `AnimatePresence` exits do not complete in this app — the child is
           * never unmounted, so in `wait` mode the incoming hint never mounts
           * and this line freezes on whatever it first rendered, and in sync
           * mode every past hint piles up in the DOM instead. Reproduced in a
           * production build, so it is not a StrictMode artifact; it is not
           * duplicate framer instances, reduced motion, or the spring config
           * either. `AppShell` already names the hazard in the abstract when it
           * explains why route transitions use `popLayout` and never `wait`.
           *
           * Keying on the text gives React a fresh node to fade in, which is
           * the whole visible effect, and depends on no exit lifecycle.
           */}
          <motion.p
            key={hint}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={springSnappy}
            className="text-[11px] text-static"
          >
            {hint}
          </motion.p>
        </div>
      </motion.div>
    </motion.div>
  );
}

function StepStar({
  state,
  label,
}: {
  state: "done" | "active" | "ahead";
  label: string;
}) {
  return (
    <div className="relative h-5 w-5 shrink-0">
      <svg viewBox="0 0 20 20" className="h-5 w-5" aria-hidden>
        {state === "done" && <circle cx={10} cy={10} r={3.5} fill={NODE_PRIMARY} />}
        {state === "active" && (
          <>
            <motion.circle
              cx={10}
              cy={10}
              fill="none"
              stroke="var(--color-starlight)"
              strokeWidth={1}
              initial={false}
              animate={{ r: [4, 9], opacity: [0.4, 0] }}
              transition={{ duration: 2.2, repeat: Infinity, ease: "easeOut" }}
            />
            <motion.circle
              cx={10}
              cy={10}
              r={3.5}
              fill="var(--color-starlight)"
              initial={false}
              animate={{ opacity: [1, 0.55, 1] }}
              transition={{ duration: 2.2, repeat: Infinity, ease: "easeInOut" }}
            />
          </>
        )}
        {state === "ahead" && (
          <circle
            cx={10}
            cy={10}
            r={3}
            fill="none"
            stroke="var(--color-halo)"
            strokeWidth={1.25}
          />
        )}
      </svg>
      <span
        className={`absolute left-1/2 top-[22px] -translate-x-1/2 whitespace-nowrap text-[10px] ${
          state === "active" ? "text-starlight" : "text-static"
        }`}
      >
        {label}
      </span>
    </div>
  );
}
