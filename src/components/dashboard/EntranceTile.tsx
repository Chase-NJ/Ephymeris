import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { springSnappy } from "@/lib/motion";

/**
 * A door, in the Dashboard's HUD vocabulary.
 *
 * The overview column is three `SummaryCard` readouts — *how is the rig, how
 * are the cohorts, how is the learning going*. Two of the app's tabs answer a
 * different kind of question — *how is this rig wired*, *what is the animal
 * asked to do* — and had no presence here at all: the only way to either was
 * the sidebar. These are that presence, and they are deliberately **not**
 * `SummaryCard`s: a card whose body is a list of rows promises a readout, and
 * these have nothing to read out. They are the entrance.
 *
 * So the shape is different on purpose — squarer, paired, a motif instead of
 * rows — while the material is the same `.hud` glass every tile on this page
 * floats in, because they sit in the same column over the same sky.
 *
 * Three things happen on hover, on one spring: the tile lifts, its rule
 * brightens, and the **motif animates**. The motif is where the visual interest
 * lives and it earns its place by being about the destination — the rig's is a
 * pin header with a trace being run, the task's is a trial advancing through a
 * four-node flow. Nothing glows and nothing gradients: the palette is matte and
 * Pulsar in particular is protected from both (`ARCHITECTURE.md#theme`), so
 * movement and a single accent stroke are the whole vocabulary.
 *
 * `footer` is a sibling of the main button rather than a child, and that is
 * structural rather than stylistic: a button inside a button is invalid, and
 * the Task tile's shortcut to the sketch library has to be its own control.
 */
export function EntranceTile({
  icon: Icon,
  label,
  caption,
  status,
  motif,
  onOpen,
  footer,
}: {
  icon: LucideIcon;
  label: string;
  /** The question the destination answers, in the destination's own words. */
  caption: string;
  /** One live fact, when there is a cheap one. Omitted rather than invented. */
  status?: string;
  /** Reads the `idle` / `hover` variants this tile animates between. */
  motif: ReactNode;
  onOpen: () => void;
  footer?: ReactNode;
}) {
  return (
    <motion.div
      className="hud group relative flex flex-col overflow-hidden rounded-md transition-colors hover:border-static/40"
      initial="idle"
      animate="idle"
      whileHover="hover"
      variants={{ idle: { y: 0 }, hover: { y: -2 } }}
      transition={springSnappy}
    >
      <button
        type="button"
        onClick={onOpen}
        className="relative flex flex-1 flex-col items-start px-3.5 pb-3 pt-3 text-left"
      >
        {/* The icon and the motif share the top band, and the band's height is
            the motif's — which is what keeps the two tiles' labels on one
            baseline even though one carries a status line and the other a
            footer. Bottom-aligning the text instead put them 17px apart.
            The motif bleeds off the right edge and the tile clips it: a texture
            at the corner of the eye, not a picture competing for the middle. */}
        <span className="flex w-full items-start justify-between gap-2">
          <Icon size={17} strokeWidth={1.75} className="shrink-0 text-pulsar" />
          <span
            aria-hidden
            className="pointer-events-none -mr-3.5 -mt-1 shrink-0 opacity-70 transition-opacity group-hover:opacity-100"
          >
            {motif}
          </span>
        </span>

        <span className="mt-1.5 min-w-0">
          <span className="flex items-center gap-1 text-[13px] font-medium text-starlight">
            {label}
            <ArrowRight
              size={11}
              strokeWidth={2}
              className="text-static transition-transform group-hover:translate-x-0.5"
            />
          </span>
          <span className="mt-0.5 block text-[11px] leading-snug text-static">
            {caption}
          </span>
          {status && (
            <span className="mt-1 block font-mono text-[10px] text-static/70">
              {status}
            </span>
          )}
        </span>
      </button>

      {footer && (
        <div className="relative border-t border-halo px-3.5 py-1.5">{footer}</div>
      )}
    </motion.div>
  );
}

/**
 * The rig's motif: a pin header with one trace run to a box.
 *
 * Wiring, because that is what the screen behind it is for — and specifically
 * *not* box health, which the Boxes readout two tiles down already carries at
 * full detail. A glyph that repeated it would make the column say the same
 * thing twice in two visual languages.
 *
 * On hover the trace draws itself from the pad to the box and the pad it leaves
 * from lights: one channel being wired, which is the gesture the screen exists
 * for. `pathLength` is animated rather than a dash offset so the length is
 * resolution-independent.
 */
export function RigMotif() {
  return (
    <svg width="84" height="46" viewBox="0 0 84 46" fill="none" aria-hidden>
      {/* Two rows of pads — a pin header, seen from above. */}
      {[0, 1].map((row) =>
        [0, 1, 2, 3, 4, 5].map((col) => (
          <rect
            key={`${row}-${col}`}
            x={6 + col * 10}
            y={7 + row * 10}
            width="4.5"
            height="4.5"
            rx="1"
            fill="var(--color-halo)"
          />
        )),
      )}
      {/* The pad the trace leaves from. */}
      <motion.rect
        x={26}
        y={17}
        width="4.5"
        height="4.5"
        rx="1"
        variants={{
          idle: { fill: "var(--color-static)", opacity: 0.5 },
          hover: { fill: "var(--color-pulsar)", opacity: 1 },
        }}
        transition={springSnappy}
      />
      {/* The trace: down, right, down — orthogonal, like a routed track. */}
      <motion.path
        d="M28.25 22 V31 H56 V34"
        stroke="var(--color-pulsar)"
        strokeWidth="1.25"
        strokeLinecap="round"
        variants={{
          idle: { pathLength: 0, opacity: 0.35 },
          hover: { pathLength: 1, opacity: 1 },
        }}
        transition={{ duration: 0.45, ease: "easeOut" }}
      />
      {/* The box the trace lands on. */}
      <rect
        x={47}
        y={34}
        width="18"
        height="10"
        rx="2"
        stroke="var(--color-static)"
        strokeOpacity="0.45"
        strokeWidth="1"
      />
    </svg>
  );
}

/**
 * The task's motif: one trial advancing through a four-node flow.
 *
 * Four nodes and three edges are the four epochs a trial passes through
 * (`TASKS.md#derived-state-machine`) — so the glyph is a diagram of the
 * thing behind the tile rather than an arbitrary decoration. On hover the edges
 * draw left to right and the last node lights: a trial completing.
 */
export function TaskMotif() {
  const nodes = [10, 31, 52, 73];
  return (
    <svg width="84" height="46" viewBox="0 0 84 46" fill="none" aria-hidden>
      {nodes.slice(0, -1).map((x, i) => (
        <motion.line
          key={x}
          x1={x + 5}
          y1={23}
          x2={nodes[i + 1]! - 5}
          y2={23}
          stroke="var(--color-static)"
          strokeWidth="1"
          strokeLinecap="round"
          variants={{
            idle: { pathLength: 0.001, opacity: 0.3 },
            hover: { pathLength: 1, opacity: 0.8 },
          }}
          transition={{ duration: 0.22, delay: i * 0.1, ease: "easeOut" }}
        />
      ))}
      {nodes.map((x, i) => {
        const last = i === nodes.length - 1;
        return (
          <motion.circle
            key={x}
            cx={x}
            cy={23}
            r={last ? 4.5 : 3.5}
            variants={{
              idle: {
                fill: last ? "var(--color-halo)" : "var(--color-static)",
                opacity: last ? 1 : 0.45,
              },
              hover: {
                fill: last ? "var(--color-pulsar)" : "var(--color-static)",
                opacity: last ? 1 : 0.7,
              },
            }}
            transition={{ ...springSnappy, delay: last ? 0.3 : 0 }}
          />
        );
      })}
    </svg>
  );
}
