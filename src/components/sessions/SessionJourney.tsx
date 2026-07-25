import { AnimatePresence, motion } from "framer-motion";
import { Fragment } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import { springSnappy } from "@/lib/motion";

/**
 * The session flow's guided progress rail — always on, kept subtle.
 *
 * Steps drawn as constellation stars joined by a path: completed stars are lit
 * Pulsar, the current one pulses in Starlight (opacity + a flat expanding ring,
 * no blur — the palette's no-glow rule holds), upcoming ones are Halo outlines.
 * One short hint line beneath is the only text direction; it crossfades as the
 * flow's state changes so it always names the next action.
 */

export type JourneyStep = "configure" | "boxes" | "run" | "finish";

export interface JourneyGroup {
  /** 1-based position of the running group among populated groups. */
  index: number;
  count: number;
  name: string;
}

const STEPS: { id: JourneyStep; label: string }[] = [
  { id: "configure", label: "Configure" },
  { id: "boxes", label: "Boxes" },
  { id: "run", label: "Run" },
  { id: "finish", label: "Finish" },
];

export function SessionJourney({
  step,
  hint,
  group,
}: {
  step: JourneyStep;
  hint: string;
  group?: JourneyGroup | null;
}) {
  const active = STEPS.findIndex((s) => s.id === step);

  return (
    <div className="mx-auto mb-7 max-w-[520px]">
      <div className="flex items-start px-10">
        {STEPS.map((s, i) => (
          <Fragment key={s.id}>
            {i > 0 && (
              <div
                className="mt-[9px] h-px flex-1"
                style={{
                  background: LINK_STROKE,
                  opacity: i <= active ? LINK_OPACITY_LIVE : LINK_OPACITY_DIM,
                }}
              />
            )}
            <StepStar
              label={s.label}
              state={i < active ? "done" : i === active ? "active" : "ahead"}
            />
          </Fragment>
        ))}
      </div>

      <div className="mt-8 text-center">
        {group && (
          <div className="font-mono text-[10px] text-static/80">
            group {group.index}/{group.count} · {group.name}
          </div>
        )}
        <AnimatePresence mode="wait" initial={false}>
          <motion.p
            key={hint}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -3 }}
            transition={springSnappy}
            className="mt-1 text-[11px] text-static"
          >
            {hint}
          </motion.p>
        </AnimatePresence>
      </div>
    </div>
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
