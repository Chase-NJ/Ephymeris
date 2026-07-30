import { useInView } from "framer-motion";
import { useRef } from "react";

/**
 * Arms a panel's draw-on reveal by visibility (`data.md` §10.5).
 *
 * The reveal exists to be watched — a line that draws itself below the fold
 * plays to nobody, and the reader scrolls down to an already-finished chart.
 * So the animation holds at its initial state until the panel is actually on
 * screen, then plays once.
 *
 * The observation is one-shot: scrolling away and back must not replay a
 * reveal, only new data may (§2.7). Call sites get that by keying the
 * component that owns this hook on their `revealKey` — a cohort swap or a
 * rescan remounts it, and the fresh gate again waits to be seen.
 *
 * **Fails open.** Panels gate their *data* on this, not just their motion, so
 * a gate that can never arm would leave a chart permanently blank — a far
 * worse outcome than a chart that simply appears without drawing itself. With
 * no `IntersectionObserver` to ask, the answer is therefore "shown".
 */
/**
 * Seconds a **highlight** reveal takes — one animal's line tracing itself in
 * session order when its row is hovered.
 *
 * Deliberately slower than a panel's own arrival reveal. Those two animations
 * answer different questions. A panel reveal runs once when a dashboard opens,
 * against every animal at once, and its job is to say what the x axis means
 * before getting out of the way — dawdling there delays reading. A highlight
 * reveal is a deliberate act of inspection: the reader has picked one animal
 * and wants to follow its history session by session, which is something you
 * can only do at a pace that lets the eye keep up.
 */
export const HIGHLIGHT_DRAW = 1.6;

export function useRevealOnView() {
  const ref = useRef<HTMLDivElement | null>(null);
  const observable = typeof IntersectionObserver !== "undefined";
  // Armed by a margin, not by a visible *fraction*: a fraction is measured
  // against the panel's own height, so a tall one — a heatmap of twenty
  // animals — could need more of itself on screen than the viewport can hold
  // and would never arm. Pulling the viewport's bottom edge up instead means
  // "a strip of this panel has genuinely cleared the fold", whatever its size.
  const inView = useInView(ref, { once: true, margin: "0px 0px -80px 0px" });
  return { ref, seen: observable ? inView : true };
}
