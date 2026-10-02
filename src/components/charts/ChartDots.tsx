import { motion } from "framer-motion";

/**
 * Round point markers for a `UnitChart`, drawn in **HTML over** the SVG.
 *
 * The same rule that keeps text out of that viewBox (see `UnitChart`'s header)
 * applies to circles: `preserveAspectRatio="none"` scales x and y by different
 * factors, and a chart twice as wide as it is tall turns every `<circle>` into
 * a lozenge. Strokes escape that through `vector-effect`, glyphs escape it by
 * living outside the SVG — and a marker has no third option, so it goes where
 * the glyphs went.
 *
 * Positioned in percentages against the chart's own box, so the dots track the
 * plot at any width while keeping a fixed pixel size.
 */

export interface Dot {
  /** 0–1, left to right. */
  x: number;
  /** 0–1, bottom to top — flipped here, like `unitY`. */
  y: number;
  /** Drawn as a ring: the value is real but rests on too little data
   * (`DATA.md#uncertainty`). */
  hollow?: boolean;
}

export function ChartDots({
  dots,
  color,
  size = 6,
  /** When false the dots hold at zero opacity, waiting to be seen. */
  seen = true,
  /** Seconds from the first dot to the last, so they surface in step with a
   *  line drawing itself left to right. */
  spread = 0,
}: {
  dots: Dot[];
  color: string;
  size?: number;
  seen?: boolean;
  spread?: number;
}) {
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {dots.map((dot, index) => (
        <motion.span
          key={index}
          className="absolute rounded-full"
          style={{
            left: `${dot.x * 100}%`,
            top: `${(1 - dot.y) * 100}%`,
            width: size,
            height: size,
            marginLeft: -size / 2,
            marginTop: -size / 2,
            background: dot.hollow ? "transparent" : color,
            boxShadow: dot.hollow ? `inset 0 0 0 1.5px ${color}` : undefined,
          }}
          initial={{ opacity: 0 }}
          animate={{ opacity: seen ? 1 : 0 }}
          transition={{ duration: 0.2, delay: dot.x * spread }}
        />
      ))}
    </div>
  );
}
