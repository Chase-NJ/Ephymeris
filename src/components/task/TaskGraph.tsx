import { motion } from "framer-motion";
import { useMemo } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_OPACITY_LIVE,
  LINK_STROKE,
  LINK_WIDTH,
  NODE_PRIMARY,
  NODE_RADIUS,
} from "@/components/chrome/constellationStyle";
import { OUTCOME_STYLE } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { TaskEdge, TaskGraphModel, TaskNode } from "@/lib/tasks/topology";

/**
 * The task's state machine, drawn (`dashboard.md` §2.x).
 *
 * A trial reads left to right — light, poke, odor, sample, choice, outcome —
 * with every branch the animal can take drawn as its own edge, and the returns
 * curving back to the top. The shape comes from `lib/tasks/topology.ts`, which
 * derives it from the sketch's own declared strobe vocabulary; nothing here
 * knows what a GRGL or a shaping task is.
 *
 * Visually it is the same object as the sidebar constellation and the session
 * journey rail — the same tokens, the same flat matte fills, no glow, no
 * gradients — because it is the same idea: nodes joined by thin Pulsar lines,
 * lit where something is happening.
 *
 * Two modes off one component:
 *   shape — the diagram alone
 *   live  — a token walking the graph from the running box's strobes
 *
 * There is deliberately no third "recorded" mode drawing per-edge counts onto
 * it; see the note at the top of `topology.ts` for why the model carries none.
 */

const ROW_HEIGHT = 10;
const CENTRE_Y = 30;
const PAD_X = 9;
/** Plus the `+3` label allowance below. Kept tight: the frame is much wider than
 *  it is tall, and generous vertical padding is what a height-capped card pays
 *  for — every unit of it shrinks the diagram itself. */
const PAD_Y = 5;
/** Text sizes in viewBox units. The frame is ~130 wide, so these are small
 *  numbers on purpose — 3+ reads as a headline at this scale. */
const NODE_TEXT = 2.6;
const EDGE_TEXT = 1.9;

/** Node fill by kind, with outcomes borrowing the analytics palette so the
 *  graph and `OutcomeMix` never disagree about what "rewarded" looks like.
 *  Exported for `TaskRail`, which is the same nodes in a strip and must not
 *  arrive at its own opinion about their colours. */
export function fillFor(node: TaskNode): string {
  if (node.kind === "abort") return "var(--color-halo)";
  if (node.kind !== "outcome") return NODE_PRIMARY;
  switch (node.id) {
    case "reward":
    case "withheld":
      return OUTCOME_STYLE.rewarded.fill;
    case "hold-fail":
      return OUTCOME_STYLE.holdFailed.fill;
    case "wrong-well":
      return OUTCOME_STYLE.wrongWell.fill;
    default:
      return OUTCOME_STYLE.noResponse.fill;
  }
}

/** Edge tint. Returns are deliberately the faintest thing on the canvas — they
 *  are structure, not behaviour, and drawing them boldly turns the diagram into
 *  a knot. */
function strokeFor(edge: TaskEdge): string {
  switch (edge.kind) {
    case "reward":
      return OUTCOME_STYLE.rewarded.fill;
    case "error":
      return OUTCOME_STYLE.wrongWell.fill;
    case "abort":
      return "var(--color-halo)";
    default:
      return LINK_STROKE;
  }
}

export function TaskGraph({
  model,
  liveNode,
  highlighted,
  onNodeClick,
  className = "",
}: {
  model: TaskGraphModel;
  /** Node the live token sits on; omit outside a running session. */
  liveNode?: string | null;
  /** Node ids to light — the parameter tile the operator is hovering. */
  highlighted?: ReadonlySet<string>;
  onNodeClick?: (node: TaskNode) => void;
  className?: string;
}) {
  const reduceMotion = useReduceMotion();

  const { positions, viewBox } = useMemo(() => {
    const at = new Map<string, { x: number; y: number }>();
    for (const node of model.nodes) {
      at.set(node.id, { x: node.column, y: CENTRE_Y + node.row * ROW_HEIGHT });
    }
    const xs = [...at.values()].map((p) => p.x);
    const ys = [...at.values()].map((p) => p.y);
    const minX = Math.min(...xs, 0) - PAD_X;
    const maxX = Math.max(...xs, 100) + PAD_X;
    const minY = Math.min(...ys, CENTRE_Y) - PAD_Y - 3;
    const maxY = Math.max(...ys, CENTRE_Y) + PAD_Y + 3;
    return {
      positions: at,
      viewBox: `${minX} ${minY} ${maxX - minX} ${maxY - minY}`,
    };
  }, [model]);

  if (!model.usable) return null;

  const someoneLit = (highlighted?.size ?? 0) > 0;

  return (
    <svg
      viewBox={viewBox}
      className={`w-full select-none ${className}`}
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Task state machine"
    >
      {model.edges.map((edge) => {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        if (!from || !to) return null;
        const lit =
          !someoneLit || highlighted!.has(edge.from) || highlighted!.has(edge.to);
        return <Edge key={edge.id} edge={edge} from={from} to={to} lit={lit} />;
      })}

      {model.nodes.map((node) => {
        const at = positions.get(node.id)!;
        const lit = !someoneLit || highlighted!.has(node.id);
        return (
          <g
            key={node.id}
            transform={`translate(${at.x} ${at.y})`}
            className={onNodeClick ? "cursor-pointer" : undefined}
            onClick={onNodeClick ? () => onNodeClick(node) : undefined}
          >
            <title>{node.detail ? `${node.label}\n${node.detail}` : node.label}</title>
            {/* Oversized invisible hit area — a 3-unit dot is a mean target.
                The same allowance ConstellationBoard makes for its stars. */}
            <circle r={NODE_RADIUS * 2.4} fill="transparent" />
            <NodeMark
              node={node}
              live={liveNode === node.id}
              lit={lit}
              reduceMotion={reduceMotion}
            />
            <text
              {...labelPlacement(node)}
              pointerEvents="none"
              style={{
                fontSize: NODE_TEXT,
                fill: lit ? "var(--color-starlight)" : "var(--color-static)",
                opacity: lit ? 1 : 0.45,
              }}
            >
              {node.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** Label geometry for a node's declared anchor (see `TaskNode.labelAnchor`). */
function labelPlacement(node: TaskNode) {
  switch (node.labelAnchor) {
    case "right":
      return { x: NODE_RADIUS + 1.6, y: NODE_TEXT * 0.36, textAnchor: "start" as const };
    case "above":
      return { y: -(NODE_RADIUS + 2.2), textAnchor: "middle" as const };
    default:
      return { y: NODE_RADIUS + 3.6, textAnchor: "middle" as const };
  }
}

/**
 * One node.
 *
 * The live treatment is `SessionJourney`'s `StepStar` generalised: a pulsing
 * Starlight dot inside an expanding flat ring — no blur, the palette's no-glow
 * rule holds. The ring is a `repeat: Infinity` keyframe, which `MotionConfig`'s
 * reduced-motion setting does NOT neutralise, so it is gated by hand.
 */
function NodeMark({
  node,
  live,
  lit,
  reduceMotion,
}: {
  node: TaskNode;
  live: boolean;
  lit: boolean;
  reduceMotion: boolean;
}) {
  const fill = fillFor(node);
  return (
    <>
      {live && !reduceMotion && (
        <motion.circle
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={0.5}
          initial={false}
          animate={{ r: [NODE_RADIUS, NODE_RADIUS * 2.6], opacity: [0.45, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
          pointerEvents="none"
        />
      )}
      {live && (
        <circle
          r={NODE_RADIUS * 1.8}
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={0.4}
          opacity={0.5}
          pointerEvents="none"
        />
      )}
      <motion.circle
        r={NODE_RADIUS}
        animate={{ fill: live ? "var(--color-starlight)" : fill, opacity: lit ? 1 : 0.3 }}
        transition={springSnappy}
        pointerEvents="none"
      />
    </>
  );
}

/**
 * One edge.
 *
 * Straight for the spine, curved for anything that leaves or rejoins it —
 * a return drawn straight would cut back across every node it passed.
 */
function Edge({
  edge,
  from,
  to,
  lit,
}: {
  edge: TaskEdge;
  from: { x: number; y: number };
  to: { x: number; y: number };
  lit: boolean;
}) {
  const isReturn = edge.kind === "return";

  const path = isReturn
    ? // Up and over the top of the diagram, back to the start.
      `M ${from.x} ${from.y} C ${from.x + 6} ${from.y - 26}, ${to.x - 10} ${to.y - 30}, ${to.x} ${to.y - NODE_RADIUS - 1}`
    : `M ${from.x} ${from.y} C ${(from.x + to.x) / 2} ${from.y}, ${(from.x + to.x) / 2} ${to.y}, ${to.x} ${to.y}`;

  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const baseOpacity = isReturn ? LINK_OPACITY_DIM : LINK_OPACITY_LIVE;

  return (
    <g>
      <motion.path
        d={path}
        fill="none"
        stroke={strokeFor(edge)}
        strokeWidth={LINK_WIDTH}
        strokeLinecap="round"
        animate={{ opacity: lit ? baseOpacity : LINK_OPACITY_DIM * 0.6 }}
        transition={springSnappy}
        pointerEvents="none"
      />
      {!isReturn && edge.label && (
        <text
          x={midX}
          y={midY - 1.4}
          textAnchor="middle"
          pointerEvents="none"
          className="font-mono"
          style={{
            fontSize: EDGE_TEXT,
            fill: "var(--color-static)",
            opacity: lit ? 0.85 : 0.3,
          }}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}
