import { motion } from "framer-motion";
import { useMemo } from "react";

import { springSnappy } from "@/lib/motion";
import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_ACCENT,
  NODE_PRIMARY,
  NODE_RADIUS,
} from "./constellationStyle";
import { layoutFor, type ConstellationLayout } from "@/lib/constellations/slots";
import { zodiacById } from "@/lib/constellations/zodiac";
import { useAllPortStatuses, useBoardPresence } from "@/lib/hardware/context";
import { useBoundBoxes, useSettings } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { BOX_IDS, type PortStateName } from "@/lib/hardware/store";

/**
 * The signature element (`ARCHITECTURE.md#status-constellation`).
 *
 * Box-status nodes joined by thin Pulsar lines. The layout is the user's
 * chosen zodiac constellation — boxes occupy stars, unoccupied stars
 * render as faint markers — or the legacy fixed six-node shape until one is
 * chosen. A line dims when either endpoint is not connected-and-nominal; a
 * node goes Error red on fault. This is the at-a-glance system-health readout,
 * not decoration — which is why it lives at the bottom of the sidebar and is
 * visible from every section.
 *
 * `<LiveConstellation>` below feeds it from the same two independent inputs
 * that drive the per-box state badges: the out-of-band presence poll and the
 * per-port state machine.
 */

export type BoxHealth = "nominal" | "idle" | "absent" | "fault";

/**
 * Collapse (presence, port state) into node health.
 *
 * `ERROR` wins even when the board has vanished — an unacknowledged fault is
 * exactly what this widget exists to surface. `FLASHING`/`RESETTING` read as
 * `idle` (present, mid-operation): the constellation is a health readout, and
 * a busy box is a healthy box.
 */
export function healthFor(detected: boolean, state: PortStateName): BoxHealth {
  if (state === "ERROR") return "fault";
  if (!detected) return "absent";
  if (state === "PASSTHROUGH" || state === "IN_SESSION") return "nominal";
  return "idle";
}

/** Live health for every box, from the shared hardware store. */
export function useBoxHealth(): Partial<Record<number, BoxHealth>> {
  const { status } = useSidecar();
  const boards = useBoardPresence();
  const ports = useAllPortStatuses();

  return useMemo(() => {
    // With the sidecar gone we don't *know* anything — showing stale green
    // would be a lie exactly where trust matters most. Everything reads absent.
    if (status !== "connected") return {};
    const map: Partial<Record<number, BoxHealth>> = {};
    for (const box of BOX_IDS) {
      const detected = boards.some((b) => b.boxId === box);
      map[box] = healthFor(detected, ports[box]?.state ?? "IDLE");
    }
    return map;
  }, [status, boards, ports]);
}

/** The sidebar's live instance. */
export function LiveConstellation() {
  const { settings } = useSettings();
  // A box earns a node once it's bound to a board — the same rule that decides
  // whether it gets a console panel in Debug Mode.
  const configured = useBoundBoxes();
  const health = useBoxHealth();

  const layout = useMemo(
    () => resolveLayout(settings.constellation, settings.constellationSlots, configured),
    [settings.constellation, settings.constellationSlots, configured],
  );

  return <ConstellationStatus health={health} layout={layout} />;
}

/** The chosen zodiac layout, or the legacy fixed shape when none is chosen. */
export function resolveLayout(
  constellationId: string | null,
  slots: Record<string, number>,
  boxes: number[],
): ConstellationLayout {
  const constellation = zodiacById(constellationId);
  return constellation ? layoutFor(constellation, slots, boxes) : legacyLayout(boxes);
}

/**
 * The pre-zodiac fixed layout — positions pinned per box number, in a 100×54
 * frame, deliberately irregular so it reads as a constellation. Kept as the
 * fallback so an install that never ran box setup looks exactly as it did.
 */
const LEGACY_NODES: ReadonlyArray<{ box: number; x: number; y: number }> = [
  { box: 1, x: 12, y: 14 },
  { box: 2, x: 47, y: 8 },
  { box: 3, x: 86, y: 18 },
  { box: 4, x: 16, y: 44 },
  { box: 5, x: 53, y: 38 },
  { box: 6, x: 88, y: 47 },
];

/** Legacy adjacency — one closed shape so no node is ever orphaned. */
const LEGACY_EDGES: ReadonlyArray<readonly [number, number]> = [
  [1, 2],
  [2, 3],
  [4, 5],
  [5, 6],
  [1, 4],
  [3, 6],
];

export function legacyLayout(boxes: number[]): ConstellationLayout {
  const shown = new Set(boxes);
  const nodes = LEGACY_NODES.filter((n) => shown.has(n.box)).map((n) => ({
    box: n.box,
    star: n.box - 1,
    x: n.x,
    y: n.y,
  }));
  // Edges between unconfigured boxes are dropped entirely (not dimmed): in the
  // legacy shape an unclaimed slot isn't missing hardware, so nothing marks it.
  const edges = LEGACY_EDGES.filter(([a, b]) => shown.has(a) && shown.has(b)).map(
    ([a, b]) => [a - 1, b - 1] as const,
  );
  return { nodes, edges, emptyStars: [] };
}

export const NODE_FILL: Record<BoxHealth, string> = {
  nominal: NODE_ACCENT,
  idle: NODE_PRIMARY,
  absent: "var(--color-halo)",
  fault: "var(--color-status-error)",
};

/** A link is live only when both endpoints are present and healthy. */
export function isLinkLive(a: BoxHealth | undefined, b: BoxHealth | undefined): boolean {
  const ok = (h: BoxHealth | undefined) => h === "nominal" || h === "idle";
  return ok(a) && ok(b);
}

/** Aspect the widget always keeps, so the sidebar never reflows. */
const VIEW_ASPECT = 100 / 54;
const VIEW_PADDING = 9;

/**
 * Frame the view around the given points.
 *
 * In zodiac mode this runs over **all** stars, occupied or not — the asterism
 * is the point of the feature and must not warp as boxes come and go. In the
 * legacy layout it frames only configured boxes, as it always has. Either way
 * the framing changes only on configuration acts, never mid-session.
 */
export function frameFor(points: ReadonlyArray<{ x: number; y: number }>): {
  viewBox: string;
  scale: number;
} {
  if (points.length === 0) return { viewBox: "0 0 100 54", scale: 1 };

  let minX = Math.min(...points.map((n) => n.x)) - VIEW_PADDING;
  let maxX = Math.max(...points.map((n) => n.x)) + VIEW_PADDING;
  let minY = Math.min(...points.map((n) => n.y)) - VIEW_PADDING;
  let maxY = Math.max(...points.map((n) => n.y)) + VIEW_PADDING;

  // Grow the short side to hold the aspect, so one box doesn't render as a
  // single enormous dot and the sidebar height never jumps.
  let width = maxX - minX;
  let height = maxY - minY;
  if (width / height < VIEW_ASPECT) {
    const target = height * VIEW_ASPECT;
    const cx = (minX + maxX) / 2;
    minX = cx - target / 2;
    width = target;
  } else {
    const target = width / VIEW_ASPECT;
    const cy = (minY + maxY) / 2;
    minY = cy - target / 2;
    height = target;
  }

  // Zooming spreads the *spacing*, not the marks. Node radius and line width
  // scale with the frame so a two-box rig doesn't render as giant blobs —
  // dots stay the same apparent size however many boxes exist.
  return { viewBox: `${minX} ${minY} ${width} ${height}`, scale: width / 100 };
}

export function ConstellationStatus({
  health = {},
  layout,
}: {
  health?: Partial<Record<number, BoxHealth>>;
  layout: ConstellationLayout;
}) {
  const at = (box: number): BoxHealth => health[box] ?? "absent";
  const { nodes, edges, emptyStars } = layout;

  // Star index → position + occupant, for edge endpoints.
  const starAt = new Map<number, { x: number; y: number; box: number | null }>();
  for (const s of emptyStars) starAt.set(s.star, { x: s.x, y: s.y, box: null });
  for (const n of nodes) starAt.set(n.star, { x: n.x, y: n.y, box: n.box });

  const connected = nodes.filter((n) => at(n.box) !== "absent").length;
  const caption =
    nodes.length === 0 ? "no boxes configured" : `${connected}/${nodes.length} boxes`;
  const { viewBox, scale } = frameFor([...nodes, ...emptyStars]);

  return (
    <div className="px-2 pb-1">
      {/* No nodes means no map to draw — an empty frame would just be dead
          space above the caption. */}
      <svg
        viewBox={viewBox}
        className={`w-full ${nodes.length === 0 ? "hidden" : ""}`}
        preserveAspectRatio="xMidYMid meet"
        aria-hidden
      >
        {edges.map(([a, b]) => {
          const from = starAt.get(a);
          const to = starAt.get(b);
          if (!from || !to) return null;
          // An edge is live only when both endpoint stars are occupied by
          // healthy boxes; one touching an empty star draws dim.
          const live =
            from.box !== null &&
            to.box !== null &&
            isLinkLive(at(from.box), at(to.box));
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

        {/* Unoccupied stars: faint markers, distinct from an `absent` box
            (which keeps full radius). No stroke, no glow
            (`ARCHITECTURE.md#theme`). */}
        {emptyStars.map((s) => (
          <circle
            key={`empty-${s.star}`}
            cx={s.x}
            cy={s.y}
            r={NODE_RADIUS * 0.55 * scale}
            fill="var(--color-halo)"
            opacity={0.4}
          />
        ))}

        {nodes.map((n) => (
          <motion.circle
            key={n.box}
            cx={n.x}
            cy={n.y}
            r={NODE_RADIUS * scale}
            animate={{ fill: NODE_FILL[at(n.box)] }}
            transition={springSnappy}
          />
        ))}
      </svg>

      <p className="mt-1 text-center font-mono text-[10px] text-static">{caption}</p>
    </div>
  );
}
