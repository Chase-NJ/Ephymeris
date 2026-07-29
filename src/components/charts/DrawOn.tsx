import { motion } from "framer-motion";
import type { ReactNode } from "react";

/**
 * Reveals SVG children left to right by wiping a clip rectangle across them.
 *
 * **Use this instead of Framer Motion's `pathLength`**, which is quietly wrong
 * for every chart in this folder. Motion implements `pathLength` by setting
 * `pathLength="1"` and animating `stroke-dasharray`; the browser resolves that
 * dash against the path's length in *user* space, while
 * `vector-effect="non-scaling-stroke"` — which every chart here needs so a
 * stretched viewBox doesn't distort line weight — paints it in *screen* space.
 * Any chart scaled up therefore *finishes* its animation holding a dash far
 * shorter than the line it should cover, and settles as a row of disconnected
 * chunks with gaps that fall in arbitrary places rather than at the data's own
 * discontinuities.
 *
 * It is the upscaling that does it, not the non-uniformity: measured on the
 * real panels, the rewarded-accuracy trend renders at 8.2× horizontally and
 * its finished dash covers 18% of the line, and the strategy plane is broken
 * at a perfectly uniform 3.52×. Only the animal rail escaped, and only because
 * it is the one chart drawn *smaller* than its viewBox.
 *
 * A wipe has no such coupling — and on a time axis it reads better anyway. A
 * `pathLength` draw advances along arc length, so a jagged stretch crawls
 * while a flat one races and the line's progress never tracks x; a wipe
 * advances uniformly in x, which is what "lays its history down in order"
 * actually means when x is time. It is also what makes the marks line up: a
 * dot delayed by `x * duration` now surfaces exactly as the edge reaches it.
 *
 * And unlike `pathLength` it composes with `stroke-dasharray`, so dashed gap
 * bridges reveal on the same clock as the solid runs instead of needing a
 * separate opacity fade.
 */
export function DrawOn({
  viewBox,
  seen = true,
  duration = 0.9,
  delay = 0,
  children,
}: {
  /** The host SVG's viewBox, as `[minX, minY, width, height]`. */
  viewBox: [number, number, number, number];
  /** When false the wipe holds closed, waiting to be seen (`analytics.md` §2.7). */
  seen?: boolean;
  duration?: number;
  delay?: number;
  children: ReactNode;
}) {
  const [minX, minY, width, height] = viewBox;
  // Overscanned vertically so the moving right edge is the only thing that ever
  // cuts. Two jobs: a stroke sitting on y=0 or y=1 is half outside the viewBox
  // and a tight clip would shave it, and this rect is also what fixes the
  // reference box the percentages below resolve against — `clip-path` on an
  // SVG group measures the group's own bounding box, so without it the wipe
  // would span whatever the data happened to occupy rather than the full plot,
  // and the marks' `x * duration` delays would drift out of step with it.
  const pad = height;

  return (
    // A CSS `clip-path` on the group, rather than an SVG `<clipPath>` holding
    // an animated rect: Framer Motion drives that rect to about 4% of its
    // travel and stops, because nothing inside `<defs>` is rendered and it also
    // overwrites any `transform-origin` you set with its own `50% 50%`. This
    // animates an ordinary CSS property on an ordinary rendered element, which
    // has neither problem and needs no generated id.
    <motion.g
      initial={{ clipPath: "inset(0 100% 0 0)" }}
      animate={{ clipPath: seen ? "inset(0 0% 0 0)" : "inset(0 100% 0 0)" }}
      transition={{ duration, delay, ease: "easeOut" }}
    >
      <rect
        x={minX}
        y={minY - pad}
        width={width}
        height={height + pad * 2}
        fill="none"
        stroke="none"
        pointerEvents="none"
      />
      {children}
    </motion.g>
  );
}
