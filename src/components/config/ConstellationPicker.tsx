import { motion } from "framer-motion";

import { frameFor } from "@/components/chrome/ConstellationStatus";
import {
  LINK_OPACITY_DIM,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_RADIUS,
} from "@/components/chrome/constellationStyle";
import { ZODIAC, type ZodiacConstellation } from "@/lib/constellations/zodiac";
import { springSnappy } from "@/lib/motion";

/**
 * The zodiac catalogue picker (`ARCHITECTURE.md#status-constellation`).
 *
 * Star counts are shown honestly, and a constellation with fewer stars than
 * the rig has boxes is disabled rather than distorted — Aries genuinely
 * cannot hold six boxes.
 */

function ZodiacThumb({ constellation }: { constellation: ZodiacConstellation }) {
  const { viewBox, scale } = frameFor(constellation.stars);
  return (
    <svg viewBox={viewBox} className="w-full" preserveAspectRatio="xMidYMid meet" aria-hidden>
      {constellation.edges.map(([a, b]) => {
        const from = constellation.stars[a]!;
        const to = constellation.stars[b]!;
        return (
          <line
            key={`${a}-${b}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={LINK_STROKE}
            strokeWidth={LINK_WIDTH * scale}
            opacity={LINK_OPACITY_DIM * 2.4}
          />
        );
      })}
      {constellation.stars.map((s, i) => (
        <circle key={i} cx={s.x} cy={s.y} r={NODE_RADIUS * 0.7 * scale} fill="var(--color-static)" opacity={0.75} />
      ))}
    </svg>
  );
}

export function ConstellationPicker({
  selected,
  boxCount,
  onSelect,
}: {
  selected: string | null;
  /** Configured boxes — maps with fewer stars than this are disabled. */
  boxCount: number;
  onSelect: (id: string) => void;
}) {
  return (
    // Six across on anything wider than a phone: twelve signs in two rows, a
    // choice made once, not a gallery to browse.
    <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6">
      {ZODIAC.map((c) => {
        const tooSmall = c.stars.length < boxCount;
        const active = selected === c.id;
        return (
          <motion.button
            key={c.id}
            type="button"
            disabled={tooSmall}
            onClick={() => onSelect(c.id)}
            {...(tooSmall ? {} : { whileTap: { scale: 0.97 } })}
            transition={springSnappy}
            title={
              tooSmall
                ? `${c.name} has ${c.stars.length} stars — needs at least ${boxCount}`
                : c.name
            }
            className={`rounded-md border px-1.5 pb-1 pt-1.5 text-left transition-colors ${
              active
                ? "border-pulsar bg-pulsar/12"
                : "border-halo bg-nebula hover:border-static/40"
            } ${tooSmall ? "opacity-40" : ""}`}
          >
            <ZodiacThumb constellation={c} />
            <div className="mt-0.5 flex items-baseline justify-between gap-1">
              <span
                className={`truncate text-[11px] font-medium ${active ? "text-starlight" : "text-static"}`}
              >
                {c.name}
              </span>
              <span className="shrink-0 font-mono text-[9px] text-static/80">
                {c.stars.length}★
              </span>
            </div>
          </motion.button>
        );
      })}
    </div>
  );
}
