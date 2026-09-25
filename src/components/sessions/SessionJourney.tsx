import { AnimatePresence, motion } from "framer-motion";
import { Fragment } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import { springPanel, springSnappy } from "@/lib/motion";

/**
 * The session flow's guided progress rail — always on, kept subtle.
 *
 * Steps drawn as constellation stars joined by a path: completed stars are lit
 * Pulsar, the current one pulses in Starlight (opacity + a flat expanding ring,
 * no blur — the palette's no-glow rule holds), upcoming ones are Halo outlines.
 * One short hint line beneath is the only text direction; it crossfades as the
 * flow's state changes so it always names the next action.
 */

export type JourneyStep = "configure" | "boxes" | "record" | "run" | "finish";

export interface JourneyGroup {
  name: string;
  /** Populated groups that have run in this session, the current one
   *  included — a count, not a position: groups run in whatever order the
   *  operator picks. */
  ran: number;
  count: number;
}

const STEPS: { id: JourneyStep; label: string }[] = [
  { id: "configure", label: "Configure" },
  { id: "boxes", label: "Boxes" },
  { id: "run", label: "Run" },
  { id: "finish", label: "Finish" },
];

/**
 * A recording session's rail: the same journey with one more star.
 *
 * After Boxes, not before, because the recording step assigns a headstage port
 * to each MAPPED box — it has nothing to ask until the mapping exists
 * (`recording.md` §4).
 */
const RECORDING_STEPS: { id: JourneyStep; label: string }[] = STEPS.flatMap((s) =>
  s.id === "run" ? [{ id: "record" as const, label: "Record" }, s] : [s],
);

/**
 * How much the bar shrinks once the flow reaches Mission Control.
 *
 * It moves from a 520px column in the middle of the page to a 344px HUD rail
 * down the left, where it is one item among several rather than the heading of
 * the screen. Shrinking says that: still present, no longer the subject.
 *
 * Applied as a transform on an inner wrapper rather than by rebuilding the bar
 * at smaller sizes — a scale is one animatable number, and the alternative is
 * four fonts and three gaps all interpolating separately and arriving at
 * slightly different times.
 */
const COMPACT_SCALE = 0.84;

export function SessionJourney({
  step,
  hint,
  group,
  compact = false,
  recording = false,
}: {
  step: JourneyStep;
  hint: string;
  group?: JourneyGroup | null;
  /** Mission Control's rail. See `COMPACT_SCALE`. */
  compact?: boolean;
  /** The session is also an Intan recording, so the rail has a Record star. */
  recording?: boolean;
}) {
  const steps = recording ? RECORDING_STEPS : STEPS;
  const active = steps.findIndex((s) => s.id === step);

  return (
    /*
     * **One bar that travels, not three that replace each other.**
     *
     * `layoutId` makes this a shared element across the route change: the
     * instance mounting in Mission Control's rail animates *from* the box the
     * mapping step's instance is vacating, so the bar slides and resizes into
     * its new home instead of vanishing from the middle of the page and
     * reappearing at the left edge. It works because `AppShell` transitions with
     * `popLayout`, which keeps the outgoing page mounted while it leaves — both
     * instances are alive at the moment of the swap, which is what framer needs
     * to match them.
     *
     * The id is a constant, not per-step: the whole point is that Configure,
     * Boxes and Run are the *same* bar in three places.
     */
    <motion.div
      layoutId="session-journey"
      transition={springPanel}
      className={`mx-auto max-w-[520px] ${compact ? "mb-4" : "mb-7"}`}
    >
      <motion.div
        animate={{ scale: compact ? COMPACT_SCALE : 1 }}
        transition={springPanel}
        // Top-centre, so the bar shrinks toward the corner it is heading for
        // rather than drifting out of the rail as it goes.
        style={{ transformOrigin: "top center" }}
      >
        {/* **Fixed connectors, centred — not `flex-1` across whatever box it
          landed in.** This bar has three hosts of two very different widths:
          the two setup steps give it a 520px column, Mission Control gives it a
          344px HUD rail. Stretchy connectors made it a different bar in each,
          and worse, made *any* change to the host's content box redistribute
          across all three gaps at once — so the rail growing a scrollbar, or
          simply the session snapshot landing a beat after the route did, read as
          the bar resizing itself on arrival. At a fixed width it is the same
          object everywhere and nothing downstream can resize it. */}
        <div className="flex items-start justify-center">
          {steps.map((s, i) => (
            <Fragment key={s.id}>
              {i > 0 && (
                <div
                  // `shrink-0` is what makes the fixed width fixed: a flex item
                  // with a width and no shrink guard still gives it up under
                  // pressure, which is the stretchiness this replaced wearing a
                  // different hat. 4×20 + 3×76 = 308px, inside the narrowest host
                  // (Mission Control's 344px rail) with room to spare. Five
                  // stars take shorter connectors to stay inside the same rail:
                  // 5×20 + 4×56 = 324px.
                  className={`mt-[9px] h-px shrink-0 ${recording ? "w-[56px]" : "w-[76px]"}`}
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

        {/* Both lines below reserve their space rather than taking it when they
          have something to say. Mission Control mounts this bar before either of
          its two round trips has landed, so `group` goes absent → present and
          `hint` changes length within the first second of arriving — and the
          rail is a flex column, so a line appearing or wrapping pushes every
          control under it down. Reserved, the bar simply fills in. */}
        <div className="mt-8 text-center">
          <div
            className={`font-mono text-[10px] text-static/80 ${group ? "" : "invisible"}`}
          >
            {group
              ? `${group.name} · ${group.ran}/${group.count} groups run`
              : " "}
          </div>
          {/* Two lines' worth at 11px (2 × 16.5px). Every hint currently written
            fits on one line even in the 344px rail, so this is deliberately
            reserving a line that is usually empty — the hints are prose that
            gets edited, and the failure mode is a wrap that only shows up on
            arrival, in one host, once the session snapshot lands. Cheaper to
            hold the space than to re-verify every hint against a width. */}
          <div className="mt-1 min-h-[33px]">
            <AnimatePresence mode="wait" initial={false}>
              <motion.p
                key={hint}
                initial={{ opacity: 0, y: 3 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -3 }}
                transition={springSnappy}
                className="text-[11px] text-static"
              >
                {hint}
              </motion.p>
            </AnimatePresence>
          </div>
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
        {state === "done" && (
          <circle cx={10} cy={10} r={3.5} fill={NODE_PRIMARY} />
        )}
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
              transition={{
                duration: 2.2,
                repeat: Infinity,
                ease: "easeInOut",
              }}
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
