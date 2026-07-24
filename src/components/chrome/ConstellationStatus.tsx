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
import { useAllPortStatuses, useBoardPresence } from "@/lib/hardware/context";
import { useBoundBoxes } from "@/lib/settings/context";
import { useSidecar } from "@/lib/ws/context";
import { BOX_IDS, type PortStateName } from "@/lib/hardware/store";

/**
 * The signature element (ephymeris_v1.0.md §2.7).
 *
 * Six nodes in a fixed abstract layout with thin Pulsar lines between adjacent
 * boxes. A line dims when either endpoint is not connected-and-nominal; a node
 * goes Error red on fault. This is the at-a-glance system-health readout, not
 * decoration — which is why it lives at the bottom of the sidebar and is
 * visible from every section (§3.2).
 *
 * `<LiveConstellation>` below feeds it from the same two independent inputs
 * that drive the §3.4 badges: the out-of-band presence poll and the per-port
 * state machine.
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

/** The sidebar's live instance, fed from the shared hardware store. */
export function LiveConstellation() {
  const { status } = useSidecar();
  const boards = useBoardPresence();
  const ports = useAllPortStatuses();

  // A box earns a node once it's bound to a board — the same rule that decides
  // whether it gets a console panel in Debug Mode.
  const configured = useBoundBoxes();

  const health = useMemo(() => {
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

  return <ConstellationStatus health={health} boxes={configured} />;
}

/**
 * Fixed node positions in a 100×54 viewBox. Deliberately irregular rather than
 * a strict grid so it reads as a constellation.
 */
const NODES: ReadonlyArray<{ box: number; x: number; y: number }> = [
  { box: 1, x: 12, y: 14 },
  { box: 2, x: 47, y: 8 },
  { box: 3, x: 86, y: 18 },
  { box: 4, x: 16, y: 44 },
  { box: 5, x: 53, y: 38 },
  { box: 6, x: 88, y: 47 },
];

/**
 * Which pairs count as "adjacent". The spec says adjacent nodes are linked but
 * doesn't enumerate the pairs; this forms one closed constellation so no node
 * is ever orphaned. Logged as an open item.
 */
const EDGES: ReadonlyArray<readonly [number, number]> = [
  [1, 2],
  [2, 3],
  [4, 5],
  [5, 6],
  [1, 4],
  [3, 6],
];

const NODE_FILL: Record<BoxHealth, string> = {
  nominal: NODE_ACCENT,
  idle: NODE_PRIMARY,
  absent: "var(--color-halo)",
  fault: "var(--color-status-error)",
};

/** A link is live only when both endpoints are present and healthy. */
function isLinkLive(a: BoxHealth | undefined, b: BoxHealth | undefined): boolean {
  const ok = (h: BoxHealth | undefined) => h === "nominal" || h === "idle";
  return ok(a) && ok(b);
}

/** Aspect the widget always keeps, so the sidebar never reflows. */
const VIEW_ASPECT = 100 / 54;
const VIEW_PADDING = 9;

/**
 * Frame the view around whichever boxes exist.
 *
 * Node positions are pinned per box number — box 4 always sits where box 4
 * sits — so the picture is stable while you're watching it. Only the framing
 * changes, and only when boxes are added or removed, which is a deliberate
 * configuration act rather than something that happens mid-session.
 */
function frameFor(nodes: typeof NODES): { viewBox: string; scale: number } {
  if (nodes.length === 0) return { viewBox: "0 0 100 54", scale: 1 };

  let minX = Math.min(...nodes.map((n) => n.x)) - VIEW_PADDING;
  let maxX = Math.max(...nodes.map((n) => n.x)) + VIEW_PADDING;
  let minY = Math.min(...nodes.map((n) => n.y)) - VIEW_PADDING;
  let maxY = Math.max(...nodes.map((n) => n.y)) + VIEW_PADDING;

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
  boxes = null,
}: {
  health?: Partial<Record<number, BoxHealth>>;
  /** Configured box numbers. Null shows all six (the design-time default). */
  boxes?: number[] | null;
}) {
  const at = (box: number): BoxHealth => health[box] ?? "absent";

  // Only configured boxes get a node; an unclaimed slot isn't missing hardware.
  const nodes = boxes === null ? NODES : NODES.filter((n) => boxes.includes(n.box));
  const shown = new Set(nodes.map((n) => n.box));
  const edges = EDGES.filter(([a, b]) => shown.has(a) && shown.has(b));

  const connected = nodes.filter((n) => at(n.box) !== "absent").length;
  const caption =
    nodes.length === 0 ? "no boxes configured" : `${connected}/${nodes.length} boxes`;
  const { viewBox, scale } = frameFor(nodes);

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
          const from = NODES.find((n) => n.box === a);
          const to = NODES.find((n) => n.box === b);
          if (!from || !to) return null;
          const live = isLinkLive(at(a), at(b));
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
