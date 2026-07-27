import { motion } from "framer-motion";
import { useMemo, useRef, useState } from "react";

import {
  isLinkLive,
  NODE_FILL,
  frameFor,
  type BoxHealth,
} from "@/components/chrome/ConstellationStatus";
import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_RADIUS,
} from "@/components/chrome/constellationStyle";
import { assignStar, layoutFor } from "@/lib/constellations/slots";
import type { ZodiacConstellation } from "@/lib/constellations/zodiac";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";

/**
 * The large, interactive constellation (ephymeris_v1.0.md §4.6).
 *
 * Same layout, health semantics, and style tokens as the sidebar widget —
 * bigger, labelled, and editable. Dragging a box node snaps it to another
 * star (swapping with any occupant); unoccupied stars are faint markers and
 * valid drop targets. One settings write per completed drag, never per move.
 *
 * Drag is raw pointer events rather than framer-motion drag: snapping needs
 * viewBox-space hit-testing anyway, and pointer capture on the SVG keeps the
 * gesture alive outside the element.
 */

/** How close (in layout units) a drop must land to a star to snap. */
const SNAP_RADIUS = 11;

interface DragState {
  box: number;
  fromStar: number;
  x: number;
  y: number;
}

export function ConstellationBoard({
  constellation,
  slots,
  boxes,
  labels,
  health = {},
  onSlotsChange,
}: {
  constellation: ZodiacConstellation;
  slots: Record<string, number>;
  /** Configured box numbers (bound boxes). */
  boxes: number[];
  /** Box number → display label. */
  labels: Record<number, string>;
  health?: Partial<Record<number, BoxHealth>>;
  onSlotsChange: (next: Record<string, number>) => void;
}) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const reduceMotion = useReduceMotion();

  const layout = useMemo(
    () => layoutFor(constellation, slots, boxes),
    [constellation, slots, boxes],
  );
  const at = (box: number): BoxHealth => health[box] ?? "absent";

  const starAt = useMemo(() => {
    const map = new Map<number, { x: number; y: number; box: number | null }>();
    for (const s of layout.emptyStars) map.set(s.star, { x: s.x, y: s.y, box: null });
    for (const n of layout.nodes) map.set(n.star, { x: n.x, y: n.y, box: n.box });
    return map;
  }, [layout]);

  const { viewBox, scale } = frameFor(constellation.stars);

  /** Client coordinates → viewBox coordinates. */
  function toLocal(event: React.PointerEvent): { x: number; y: number } | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
    return { x: point.x, y: point.y };
  }

  function nearestStar(x: number, y: number): number | null {
    let best: number | null = null;
    let bestDistance = SNAP_RADIUS;
    constellation.stars.forEach((s, star) => {
      const distance = Math.hypot(s.x - x, s.y - y);
      if (distance < bestDistance) {
        best = star;
        bestDistance = distance;
      }
    });
    return best;
  }

  function beginDrag(event: React.PointerEvent, box: number, fromStar: number) {
    const local = toLocal(event);
    if (!local) return;
    (event.target as Element).setPointerCapture(event.pointerId);
    setDrag({ box, fromStar, ...local });
  }

  function moveDrag(event: React.PointerEvent) {
    if (!drag) return;
    const local = toLocal(event);
    if (local) setDrag({ ...drag, ...local });
  }

  function endDrag() {
    if (!drag) return;
    const target = nearestStar(drag.x, drag.y);
    if (target !== null && target !== drag.fromStar) {
      onSlotsChange(assignStar(slots, drag.box, target));
    }
    setDrag(null);
  }

  const dropTarget = drag ? nearestStar(drag.x, drag.y) : null;

  return (
    <svg
      ref={svgRef}
      viewBox={viewBox}
      className="w-full select-none"
      style={{ touchAction: "none" }}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={`${constellation.name} box layout`}
      onPointerMove={moveDrag}
      onPointerUp={endDrag}
      onPointerCancel={() => setDrag(null)}
    >
      {layout.edges.map(([a, b]) => {
        const from = starAt.get(a);
        const to = starAt.get(b);
        if (!from || !to) return null;
        const live =
          from.box !== null && to.box !== null && isLinkLive(at(from.box), at(to.box));
        return (
          <motion.line
            key={`${a}-${b}`}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={LINK_STROKE}
            strokeWidth={LINK_WIDTH * scale}
            animate={{ opacity: live ? LINK_OPACITY_LIVE : LINK_OPACITY_DIM }}
            transition={springSnappy}
          />
        );
      })}

      {/* Every star is a drop target; unoccupied ones are the faint markers. */}
      {constellation.stars.map((s, star) => {
        const occupied = starAt.get(star)?.box != null;
        const targeted = drag !== null && dropTarget === star;
        return (
          <g key={`star-${star}`}>
            {!occupied && (
              <circle
                cx={s.x}
                cy={s.y}
                r={NODE_RADIUS * 0.55 * scale}
                fill="var(--color-halo)"
                opacity={0.5}
              />
            )}
            {targeted && (
              <circle
                cx={s.x}
                cy={s.y}
                r={NODE_RADIUS * 1.7 * scale}
                fill="none"
                stroke="var(--color-pulsar)"
                strokeWidth={LINK_WIDTH * scale}
                opacity={0.8}
              />
            )}
          </g>
        );
      })}

      {layout.nodes.map((n) => {
        const dragging = drag?.box === n.box;
        const x = dragging ? drag.x : n.x;
        const y = dragging ? drag.y : n.y;
        return (
          <g key={n.box} className="cursor-grab" style={dragging ? { cursor: "grabbing" } : undefined}>
            {/* Transform-based motion, not cx/cy attributes — springs on
                transforms are dependable across framer-motion versions. */}
            <motion.g
              animate={{ x, y }}
              transition={dragging || reduceMotion ? { duration: 0 } : springSnappy}
            >
              {/* Oversized invisible hit area — a 3-unit dot is a mean target. */}
              <circle
                r={NODE_RADIUS * 2.6 * scale}
                fill="transparent"
                onPointerDown={(event) => beginDrag(event, n.box, n.star)}
              />
              <motion.circle
                r={NODE_RADIUS * scale}
                animate={{ fill: NODE_FILL[at(n.box)], opacity: dragging ? 0.75 : 1 }}
                transition={springSnappy}
                pointerEvents="none"
              />
              <text
                y={NODE_RADIUS * scale + 4.2 * scale}
                textAnchor="middle"
                pointerEvents="none"
                className="font-mono"
                style={{ fontSize: 3.4 * scale, fill: "var(--color-static)" }}
              >
                {labels[n.box] ?? `Box ${n.box}`}
              </text>
            </motion.g>
          </g>
        );
      })}
    </svg>
  );
}
