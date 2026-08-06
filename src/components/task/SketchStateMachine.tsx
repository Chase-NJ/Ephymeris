import { motion } from "framer-motion";
import { useMemo, useState, type ReactNode } from "react";

import { fillFor } from "@/components/task/TaskGraph";
import { OUTCOME_STYLE } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import type { TaskProfile } from "@/lib/sessions/types";
import type {
  TaskEdge,
  TaskGraphModel,
  TaskNode,
} from "@/lib/tasks/topology";

/**
 * The sketch's state machine, as the page's centrepiece tile.
 *
 * This replaced `TaskGraph` + `TaskRail` on the sketch viewer (the old pair
 * survives only in Mission Control's live panel, where the token needs it).
 * What changed is not the model — the nodes and edges still come verbatim from
 * `taskGraph()`, the derived-never-declared machine (`tasks.md` §4) — but what
 * the drawing is *for*: the old diagram showed the trial and mentioned
 * parameters; this one is built around the mapping between them.
 *
 * **Every tunable group is pinned to the state it governs.** Each node carries
 * subtle mono chips naming the parameter groups that tune it (`governedBy`,
 * condensed: the six ramp groups collapse to one `holds` chip — six chips
 * saying "stage n" on every node was noise pretending to be information).
 * Chips are the map legend and the navigation: hovering one lights its group's
 * whole territory, clicking one jumps to the group's tile below.
 *
 * **The highlight dims the world instead of decorating the target.** Hovering
 * a parameter tile (or chip) drops everything the group does not govern to
 * near-invisible and rings what it does; hovering a state does the reverse —
 * the page lights the tiles that tune it — and the caption strip at the foot
 * says the relationship in words. One relationship, readable from either end,
 * stated three ways (geometry, colour, sentence).
 *
 * Outcome colours come from `fillFor`, the same mapping `OutcomeMix` and the
 * live panel use — "rewarded" is one colour everywhere in this app.
 */
export function SketchStateMachine({
  model,
  profile,
  hoverGroup,
  onHoverGroup,
  onHoverNode,
  onNodeClick,
  onSelectGroup,
  maxHeight = "60vh",
}: {
  model: TaskGraphModel;
  profile: TaskProfile | null;
  /** The group under the pointer — a parameter tile's or a chip's. */
  hoverGroup: string | null;
  onHoverGroup: (group: string | null) => void;
  /** Reports the hovered state so the page can light its tiles. */
  onHoverNode: (node: TaskNode | null) => void;
  /** A state click selects the first group that tunes it. */
  onNodeClick: (node: TaskNode) => void;
  /** A chip click selects exactly the group it names. */
  onSelectGroup: (group: string) => void;
  /** Rendered height cap. The HUD layout gives the machine the column, so the
      default suits a centrepiece; pass less where it shares a scroll. */
  maxHeight?: string;
}) {
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);

  /** Groups this profile actually declares — a chip must never name a tile
   *  that doesn't exist below. */
  const declared = useMemo(() => {
    const out = new Set<string>();
    for (const field of profile?.config ?? []) {
      if (field.group) out.add(field.group);
    }
    return out;
  }, [profile]);

  const chipsByNode = useMemo(() => {
    const out = new Map<string, Chip[]>();
    for (const node of model.nodes) out.set(node.id, chipsFor(node, declared));
    return out;
  }, [model, declared]);

  /** The one hover, whichever end it came from. */
  const litNodes = useMemo(() => {
    if (hoverGroup) {
      return new Set(
        model.nodes.filter((n) => n.governedBy.includes(hoverGroup)).map((n) => n.id),
      );
    }
    if (hoverNode) return new Set([hoverNode.id]);
    return null; // rest — nothing dimmed
  }, [model, hoverGroup, hoverNode]);

  const frame = useMemo(() => frameFor(model), [model]);

  function enterNode(node: TaskNode) {
    setHoverNode(node);
    onHoverNode(node);
  }
  function leaveNode() {
    setHoverNode(null);
    onHoverNode(null);
  }

  return (
    <div>
      <svg
        viewBox={frame.viewBox}
        className="w-full"
        style={{ maxHeight }}
        role="img"
        aria-label="The task's state machine, derived from its strobe vocabulary"
      >
        {/* Edges first, under the nodes. */}
        {model.edges.map((edge) => (
          <EdgePath
            key={edge.id}
            edge={edge}
            model={model}
            lit={litNodes}
            frame={frame}
          />
        ))}
        {model.nodes.map((node) => (
          <NodeGlyph
            key={node.id}
            node={node}
            chips={chipsByNode.get(node.id) ?? []}
            lit={litNodes === null ? null : litNodes.has(node.id)}
            hoverGroup={hoverGroup}
            frame={frame}
            onEnter={() => enterNode(node)}
            onLeave={leaveNode}
            onClick={() => onNodeClick(node)}
            onChipEnter={onHoverGroup}
            onChipLeave={() => onHoverGroup(null)}
            onChipClick={onSelectGroup}
          />
        ))}
      </svg>

      {/* The caption strip: the hovered relationship, in words. A fixed slot
          rather than a tooltip so the eye learns one place to read and the
          diagram never reflows under the pointer. */}
      <p className="mt-2 min-h-[2.25em] border-t border-halo/60 pt-2 font-mono text-[11px] leading-snug text-static">
        {hoverNode ? (
          <>
            <span className="text-starlight">{hoverNode.label}</span>
            {hoverNode.detail && <> — {hoverNode.detail}</>}
            {tunedByLine(hoverNode, declared)}
          </>
        ) : hoverGroup ? (
          <>
            <span className="text-starlight">{hoverGroup}</span> tunes{" "}
            {model.nodes
              .filter((n) => n.governedBy.includes(hoverGroup))
              .map((n) => n.label)
              .join(" · ") || "nothing on this task"}
          </>
        ) : (
          <span className="text-static/60">
            Hover a state or a parameter group — each lights the other. Click
            either to jump to the parameters.
          </span>
        )}
      </p>
    </div>
  );
}

// --- the parameter chips ----------------------------------------------------

interface Chip {
  /** What the label says — short, mono, lower-case. */
  short: string;
  /** The declared group a hover/click resolves to. */
  group: string;
  /** Every declared group the chip stands for — lights when any is hovered. */
  covers: string[];
}

/** The ramp is six groups that always travel together; one chip carries them.
 *  Everything else maps one group to one short word. */
const RAMP = ["Holds & windows", "Stage 0", "Stage 1", "Stage 2", "Stage 3", "Stage 4"];
const SHORT: Record<string, string> = {
  Session: "session",
  "Trial pool": "pool",
  "Trial timing": "timing",
  "Correction trials": "correction",
  "Abstention penalty": "penalty",
  "Reward volume": "volume",
  "Anti-bias selection": "anti-bias",
};

function chipsFor(node: TaskNode, declared: Set<string>): Chip[] {
  const chips: Chip[] = [];
  const governed = node.governedBy.filter((g) => declared.has(g));
  const ramp = governed.filter((g) => RAMP.includes(g));
  if (ramp.length > 0) {
    chips.push({ short: "holds", group: ramp[0]!, covers: ramp });
  }
  for (const group of governed) {
    if (RAMP.includes(group)) continue;
    chips.push({
      short: SHORT[group] ?? group.toLowerCase(),
      group,
      covers: [group],
    });
  }
  return chips;
}

function tunedByLine(node: TaskNode, declared: Set<string>): ReactNode {
  const chips = chipsFor(node, declared);
  if (chips.length === 0) return null;
  return (
    <span className="text-static/70">
      {" "}
      · tuned by {chips.map((c) => c.short).join(", ")}
    </span>
  );
}

// --- geometry ---------------------------------------------------------------

/** Row → y. Wider than the model's unit rows so labels and chips breathe. */
const ROW_H = 15;
/** Node radius, in frame units. */
const R = 3.1;

interface Frame {
  viewBox: string;
  x: (n: TaskNode) => number;
  y: (n: TaskNode) => number;
}

function frameFor(model: TaskGraphModel): Frame {
  const xs = model.nodes.map((n) => n.column);
  const ys = model.nodes.map((n) => n.row * ROW_H);
  const minX = Math.min(...xs, 0) - 10;
  const maxX = Math.max(...xs, 100) + 12;
  const minY = Math.min(...ys, 0) - 14;
  // The bottom pad covers the return arcs, which dip RETURN_DEPTH below the
  // lowest node — sizing off the nodes alone clipped the ITI→Light sweep.
  const maxY = Math.max(...ys, 0) + RETURN_DEPTH + 6;
  return {
    viewBox: `${minX} ${minY} ${maxX - minX} ${maxY - minY}`,
    x: (n) => n.column,
    y: (n) => n.row * ROW_H,
  };
}

/** How far the deepest return arc sweeps below the lowest node. */
const RETURN_DEPTH = 26;

// --- edges ------------------------------------------------------------------

/** Return edges arc under everything; the rest are lateral beziers. */
function pathFor(edge: TaskEdge, model: TaskGraphModel, frame: Frame): string {
  const from = model.nodes.find((n) => n.id === edge.from);
  const to = model.nodes.find((n) => n.id === edge.to);
  if (!from || !to) return "";
  const x1 = frame.x(from);
  const y1 = frame.y(from);
  const x2 = frame.x(to);
  const y2 = frame.y(to);

  if (edge.kind === "return") {
    // Sweep beneath the whole machine, back to the start — the two returns
    // nest at different depths instead of overlapping. Both stay inside the
    // frame because `frameFor` pads by RETURN_DEPTH.
    const low = Math.max(
      ...model.nodes.map((n) => frame.y(n)),
    );
    const depth = low + (edge.from === "iti" ? RETURN_DEPTH : RETURN_DEPTH - 10);
    return `M ${x1} ${y1 + R} C ${x1} ${depth}, ${x2} ${depth}, ${x2} ${y2 + R}`;
  }

  const dx = Math.max((x2 - x1) / 2, 6);
  return `M ${x1 + R} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2 - R} ${y2}`;
}

/** Same tints the live panel uses (`TaskGraph.strokeFor`), so the two
 *  drawings — and `OutcomeMix` — agree about what an outcome looks like. */
function edgeStroke(edge: TaskEdge): string {
  switch (edge.kind) {
    case "reward":
      return OUTCOME_STYLE.rewarded.fill;
    case "error":
      return OUTCOME_STYLE.wrongWell.fill;
    case "abort":
    case "return":
      return "var(--color-halo)";
    default:
      return "var(--color-static)";
  }
}

/**
 * Where an edge's label sits. A level edge labels its midpoint, just above the
 * line. A diagonal one labels partway down the run, below the path — the raw
 * midpoint of a steep edge lands on the source node's own chip stack, which is
 * exactly where a label about *leaving* that node shouldn't sit.
 */
function labelPos(x1: number, y1: number, x2: number, y2: number) {
  if (Math.abs(y2 - y1) < 4) {
    return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 1.8 };
  }
  return { x: x1 + (x2 - x1) * 0.6, y: y1 + (y2 - y1) * 0.68 + 2.4 };
}

function EdgePath({
  edge,
  model,
  lit,
  frame,
}: {
  edge: TaskEdge;
  model: TaskGraphModel;
  lit: Set<string> | null;
  frame: Frame;
}) {
  const d = pathFor(edge, model, frame);
  // An edge is part of the lit territory only when both of its ends are — a
  // half-lit edge points out of the highlight and reads as leakage.
  const on = lit === null ? null : lit.has(edge.from) && lit.has(edge.to);
  const base = edge.kind === "return" ? 0.35 : 0.55;
  const opacity = on === null ? base : on ? 0.95 : 0.1;

  const from = model.nodes.find((n) => n.id === edge.from);
  const to = model.nodes.find((n) => n.id === edge.to);

  return (
    <g style={{ opacity, transition: "opacity 160ms" }}>
      <path
        d={d}
        fill="none"
        stroke={on ? "var(--color-pulsar)" : edgeStroke(edge)}
        strokeWidth={on ? 0.7 : 0.5}
        strokeDasharray={
          edge.kind === "abort" || edge.kind === "return" ? "1.6 1.8" : undefined
        }
        vectorEffect="non-scaling-stroke"
        style={{ transition: "stroke 160ms" }}
      />
      {edge.label && from && to && (
        <text
          {...labelPos(frame.x(from), frame.y(from), frame.x(to), frame.y(to))}
          textAnchor="middle"
          className="fill-static font-mono"
          fontSize={2.1}
          opacity={0.75}
        >
          {edge.label}
        </text>
      )}
    </g>
  );
}

// --- nodes ------------------------------------------------------------------

function NodeGlyph({
  node,
  chips,
  lit,
  hoverGroup,
  frame,
  onEnter,
  onLeave,
  onClick,
  onChipEnter,
  onChipLeave,
  onChipClick,
}: {
  node: TaskNode;
  chips: Chip[];
  /** null = resting (nothing highlighted anywhere). */
  lit: boolean | null;
  hoverGroup: string | null;
  frame: Frame;
  onEnter: () => void;
  onLeave: () => void;
  onClick: () => void;
  onChipEnter: (group: string) => void;
  onChipLeave: () => void;
  onChipClick: (group: string) => void;
}) {
  const x = frame.x(node);
  const y = frame.y(node);
  const dimmed = lit === false;
  const fill = fillFor(node);

  const anchor = node.labelAnchor ?? "below";
  const labelX = anchor === "right" ? x + R + 2 : x;
  const labelY = anchor === "right" ? y + 1 : anchor === "above" ? y - R - 2.6 : y + R + 4.4;
  const textAnchor = anchor === "right" ? "start" : "middle";

  // Chips stack under the label (or trail it, for right-anchored nodes).
  const chipX = anchor === "right" ? x + R + 2 : x;
  const chipY0 = anchor === "right" ? y + 4.6 : anchor === "above" ? y + R + 4 : labelY + 3.4;

  return (
    <g
      style={{ opacity: dimmed ? 0.18 : 1, transition: "opacity 160ms", cursor: "pointer" }}
      onPointerEnter={onEnter}
      onPointerLeave={onLeave}
      onClick={onClick}
    >
      {/* The ring: the highlight's own mark, sprung in rather than toggled. */}
      {lit === true && (
        <motion.circle
          cx={x}
          cy={y}
          fill="none"
          stroke="var(--color-pulsar)"
          strokeWidth={0.55}
          vectorEffect="non-scaling-stroke"
          initial={{ r: R, opacity: 0 }}
          animate={{ r: R + 1.6, opacity: 1 }}
          transition={springSnappy}
        />
      )}

      {node.kind === "outcome" ? (
        <rect
          x={x - R}
          y={y - R}
          width={R * 2}
          height={R * 2}
          rx={1.1}
          fill={fill}
          fillOpacity={0.22}
          stroke={fill}
          strokeWidth={0.5}
          vectorEffect="non-scaling-stroke"
        />
      ) : (
        <circle
          cx={x}
          cy={y}
          r={R}
          fill="var(--color-nebula)"
          stroke={node.kind === "abort" ? "var(--color-static)" : "var(--color-starlight)"}
          strokeOpacity={node.kind === "abort" ? 0.55 : 0.8}
          strokeWidth={0.5}
          strokeDasharray={node.kind === "abort" ? "1.3 1.3" : undefined}
          vectorEffect="non-scaling-stroke"
        />
      )}

      <text
        x={labelX}
        y={labelY}
        textAnchor={textAnchor}
        fontSize={2.9}
        className={lit ? "fill-starlight" : "fill-static"}
        style={{ transition: "fill 160ms" }}
      >
        {node.label}
      </text>

      {/* The parameter chips: the subtle labels the mapping asks for. During a
          group hover only that group's chips stay up, so the highlight names
          itself instead of leaving the reader to compare colours. */}
      {chips.map((chip, index) => {
        const covered = hoverGroup !== null && chip.covers.includes(hoverGroup);
        const chipOpacity =
          hoverGroup === null ? (lit === false ? 0.15 : 0.55) : covered ? 1 : 0.12;
        return (
          <text
            key={chip.short}
            x={chipX}
            y={chipY0 + index * 3}
            textAnchor={textAnchor}
            fontSize={2.05}
            className={covered ? "fill-pulsar" : "fill-static"}
            style={{ opacity: chipOpacity, transition: "opacity 160ms, fill 160ms", cursor: "pointer" }}
            onPointerEnter={(event) => {
              event.stopPropagation();
              onChipEnter(chip.group);
            }}
            onPointerLeave={(event) => {
              event.stopPropagation();
              onChipLeave();
            }}
            onClick={(event) => {
              event.stopPropagation();
              onChipClick(chip.group);
            }}
          >
            {chip.short}
          </text>
        );
      })}
    </g>
  );
}
