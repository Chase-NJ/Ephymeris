import { motion } from "framer-motion";
import { ArrowRight, Radio } from "lucide-react";

import { springSnappy } from "@/lib/motion";

/**
 * The Strobes door, on the Task landing.
 *
 * It was the Rig landing's second door until the vocabulary moved
 * (`TASKS.md#strobe-vocabulary`). The tile is unchanged, and deliberately: an
 * operator who learned this motif on the other page should recognise the same
 * door in its new room rather than hunt for a redesigned one.
 *
 * The destination is where this machine's codes are added, retired and
 * removed; the fact line stays off, and it carries a motif for parity with
 * its neighbour: a
 * strobe train, one pulse picking up the accent on hover. Matte, single accent,
 * movement only (`ARCHITECTURE.md#theme`), same as everything else on the
 * glass.
 */
export function StrobeDoor({ onOpen }: { onOpen: () => void }) {
  return (
    <motion.button
      type="button"
      onClick={onOpen}
      initial="idle"
      animate="idle"
      whileHover="hover"
      whileTap={{ scale: 0.995 }}
      variants={{ idle: { y: 0 }, hover: { y: -2 } }}
      transition={springSnappy}
      className="hud group relative flex h-full w-full items-center gap-4 overflow-hidden rounded-md py-3.5 pl-4 pr-0 text-left transition-colors hover:border-static/40"
    >
      <Radio size={18} strokeWidth={1.75} className="shrink-0 self-start text-pulsar" />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1 text-[13px] font-medium text-starlight">
          Strobes
          <ArrowRight
            size={11}
            strokeWidth={2}
            className="text-static transition-transform group-hover:translate-x-0.5"
          />
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-static">
          Every event a box can report, and the number it reports it with.
          Add and retire codes here — the recorded archive carries them.
        </span>
      </span>
      <span
        aria-hidden
        className="pointer-events-none -my-3.5 shrink-0 self-center opacity-70 transition-opacity group-hover:opacity-100"
      >
        <StrobeMotif />
      </span>
    </motion.button>
  );
}

/**
 * The Strobes door's motif: a strobe train — event ticks on a timeline, one of
 * them picking up the accent and announcing its number on hover. The same
 * grammar as the wiring trace: the gesture the room behind the door exists
 * for, at the corner of the eye.
 */
function StrobeMotif() {
  const ticks = [10, 22, 30, 44, 58, 66, 78];
  return (
    <svg width="104" height="62" viewBox="0 0 104 62" fill="none" aria-hidden>
      {/* The recording's baseline. */}
      <path d="M6 40 H98" stroke="var(--color-halo)" strokeWidth="1" />
      {ticks.map((x) => (
        <rect key={x} x={x} y={28} width="2" height="12" rx="1" fill="var(--color-halo)" />
      ))}
      {/* The one event being looked up. */}
      <motion.rect
        x={44}
        y={24}
        width="2.5"
        height="16"
        rx="1"
        variants={{
          idle: { fill: "var(--color-static)", opacity: 0.5 },
          hover: { fill: "var(--color-pulsar)", opacity: 1 },
        }}
        transition={springSnappy}
      />
      <motion.text
        x={45}
        y={16}
        textAnchor="middle"
        fontSize="8"
        fontFamily="JetBrains Mono, monospace"
        fill="var(--color-pulsar)"
        variants={{ idle: { opacity: 0, y: 3 }, hover: { opacity: 1, y: 0 } }}
        transition={springSnappy}
      >
        233
      </motion.text>
    </svg>
  );
}

