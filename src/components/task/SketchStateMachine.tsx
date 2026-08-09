import { motion } from "framer-motion";
import { useMemo, useState, type ReactNode } from "react";

import { NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import { OUTCOME_STYLE } from "@/lib/analytics/view";
import { springSnappy } from "@/lib/motion";
import { useReduceMotion } from "@/lib/useReduceMotion";
import type { TaskProfile } from "@/lib/sessions/types";
import type {
  TaskEdge,
  TaskGraphModel,
  TaskNode,
} from "@/lib/tasks/topology";
import { useElementWidth } from "@/lib/useElementWidth";

/**
 * The sketch's state machine, as the page's centrepiece tile.
 *
 * This replaced `TaskGraph` + `TaskRail` on the sketch viewer, and the same
 * drawing now serves Mission Control's live panel as `LiveStateMachine` below
 * — one style for the machine everywhere it appears. What changed is not the
 * model — the nodes and edges still come verbatim from `taskGraph()`, the
 * derived-never-declared machine (`tasks.md` §4) — but what the drawing is
 * *for*: the old diagram showed the trial and mentioned parameters; this one
 * is built around the mapping between them.
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
 *
 * **Drawn in CSS pixels, not a scaled viewBox.** The first version scaled a
 * fixed frame to the column's width, which made every window resize a
 * font-size change — the machine ballooned and shrank with the window. Here
 * type, node radii and strokes are constant, and the measured width goes into
 * the *layout*: columns spread to fill what the tile has, clamped to a band
 * (see the geometry section) so labels never collide at the narrow end and
 * edges never sprawl at the wide one. Resizing the window now slides states
 * closer or further apart; it never changes what a label reads like.
 */

/** Node fill by kind, with outcomes borrowing the analytics palette so the
 *  machine and `OutcomeMix` never disagree about what "rewarded" looks like.
 *  (Moved here from the retired `TaskGraph`, which drew the same model in a
 *  scaled viewBox.) */
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
  /** Safety cap on rendered height. The drawing's height is fixed by its
      content now, so this only bites on unusually short windows — where the
      whole drawing shrinks uniformly rather than overflowing the tile. */
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

  const [host, hostWidth] = useElementWidth<HTMLDivElement>();
  const layoutWidth = Math.min(Math.max(hostWidth ?? FALLBACK_W, MIN_W), MAX_W);
  const frame = useMemo(
    () => frameFor(model, layoutWidth, VIEWER_GEOMETRY),
    [model, layoutWidth],
  );

  function enterNode(node: TaskNode) {
    setHoverNode(node);
    onHoverNode(node);
  }
  function leaveNode() {
    setHoverNode(null);
    onHoverNode(null);
  }

  return (
    <div ref={host}>
      {/* Three regimes off two style rules: inside the clamp band the drawing
          is 1:1 (width = layout width = host width); on a tile wider than
          MAX_W it stops growing and centres; on one narrower than MIN_W the
          MIN_W layout shrinks uniformly via maxWidth — the one place viewBox
          scaling survives, as graceful degradation below the supported band
          rather than as the sizing model. */}
      <svg
        viewBox={`0 0 ${frame.width} ${frame.height}`}
        className="mx-auto block"
        style={{ width: frame.width, maxWidth: "100%", maxHeight }}
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
        {/* Group first, node second: on a chip both hovers are live and the
            highlight is already showing the group's territory — the sentence
            has to describe the same thing the geometry does. */}
        {hoverGroup ? (
          <>
            <span className="text-starlight">{hoverGroup}</span> tunes{" "}
            {model.nodes
              .filter((n) => n.governedBy.includes(hoverGroup))
              .map((n) => n.label)
              .join(" · ") || "nothing on this task"}
          </>
        ) : hoverNode ? (
          <>
            <span className="text-starlight">{hoverNode.label}</span>
            {hoverNode.detail && <> — {hoverNode.detail}</>}
            {tunedByLine(hoverNode, declared)}
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

/**
 * The same machine, live — Mission Control's panel (`dashboard.md` §9.4).
 *
 * One drawing, two homes: this is `SketchStateMachine`'s geometry, glyphs and
 * palette with the parameter apparatus stripped away and a token added — the
 * running box's own state, decoded from its strobes (`useLiveNode`), wearing
 * the pulsing flat ring the session journey's current step wears. No chips
 * (mid-session is not the moment to tune parameters, and the vertical room
 * they needed belongs to the charts below — see `LIVE_GEOMETRY`), and the
 * caption strip reads the live state instead of a hover legend; hovering a
 * state still describes it, exactly as the viewer does.
 *
 * Counts are deliberately absent. The recorded figures come from derive.py
 * over a finished run; showing a half-session's partial tallies beside a
 * moving token would invite reading them as the run's result (`topology.ts`).
 */
export function LiveStateMachine({
  model,
  liveNode,
}: {
  model: TaskGraphModel;
  /** Node the token sits on — null before the first strobe of a trial. */
  liveNode: string | null;
}) {
  const reduceMotion = useReduceMotion();
  const [hoverNode, setHoverNode] = useState<TaskNode | null>(null);

  const litNodes = useMemo(
    () => (hoverNode ? new Set([hoverNode.id]) : null),
    [hoverNode],
  );

  const [host, hostWidth] = useElementWidth<HTMLDivElement>();
  const layoutWidth = Math.min(Math.max(hostWidth ?? FALLBACK_W, MIN_W), MAX_W);
  const frame = useMemo(
    () => frameFor(model, layoutWidth, LIVE_GEOMETRY),
    [model, layoutWidth],
  );

  const current =
    liveNode === null ? null : (model.nodes.find((n) => n.id === liveNode) ?? null);

  return (
    <div ref={host}>
      {/* The same three sizing regimes as the viewer — see the note there. */}
      <svg
        viewBox={`0 0 ${frame.width} ${frame.height}`}
        className="mx-auto block"
        style={{ width: frame.width, maxWidth: "100%" }}
        role="img"
        aria-label="The task's state machine, with the box's current state lit"
      >
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
            chips={[]}
            lit={litNodes === null ? null : litNodes.has(node.id)}
            hoverGroup={null}
            frame={frame}
            live={liveNode === node.id}
            reduceMotion={reduceMotion}
            onEnter={() => setHoverNode(node)}
            onLeave={() => setHoverNode(null)}
            onChipEnter={() => {}}
            onChipLeave={() => {}}
            onChipClick={() => {}}
          />
        ))}
      </svg>

      {/* The caption strip, repurposed as the live readout: the state the box
          is in, said in words under the drawing that shows it. A hover
          overrides it — the operator asking about a state outranks the
          narration — and it returns the moment the pointer leaves. */}
      <p className="mt-2 min-h-[2.25em] border-t border-halo/60 pt-2 font-mono text-[11px] leading-snug text-static">
        {hoverNode ? (
          <>
            <span className="text-starlight">{hoverNode.label}</span>
            {hoverNode.detail && <> — {hoverNode.detail}</>}
          </>
        ) : current ? (
          <>
            <span className="text-starlight">● {current.label}</span>
            {current.detail && <> — {current.detail}</>}
          </>
        ) : (
          <span className="text-static/60">
            The lit state is where this box is in the trial — the token moves
            as strobes arrive.
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

/*
 * Everything below is CSS pixels. The model's columns (authored, ~6–140) map
 * onto whatever horizontal room the tile offers; its rows (unit-spaced) map
 * onto a FIXED vertical rhythm. So width is the fluid axis — the one a window
 * resize actually changes — and height is a property of the task's shape, not
 * of the window. Type and marks stay constant either way.
 */

/** The width band the fluid layout serves. Below MIN_W the narrowest column
 *  gap (~18/134 of the span) no longer clears a centred chip, so the whole
 *  drawing scales down uniformly instead — the HUD's fixed columns leave the
 *  machine ~(window − 990px), so that regime is real on a 1280-wide window
 *  and the honest answer there is a smaller correct drawing, not colliding
 *  labels. Above MAX_W added width is only longer edges, so the drawing
 *  centres instead. Between them, rendering is 1:1. */
const MIN_W = 460;
const MAX_W = 1000;
/** Pre-measurement layout width. One frame at most — the tile fades in over
 *  it, so a settle from here is never visible. */
const FALLBACK_W = 720;

/** Node radius. */
const R = 9;

/** Horizontal pads. The right one only shelters the ITI; the outcome column's
 *  right-anchored labels fit because the model keeps a whole column of room
 *  between it and the frame edge. */
const PAD_L = 30;
const PAD_R = 30;

/**
 * The vertical geometry, parameterized because the drawing has two homes with
 * different tenants below the nodes:
 *
 *  - `rowPx` — px per model row unit. The sketch viewer's is sized so the
 *    deepest chip stack (an odor arm's four) clears the next fan-out row; the
 *    live view draws no chips, so its rows sit closer.
 *  - `padT` — above the top row: room for an `above`-anchored label when the
 *    top row is the spine.
 *  - `returnDepth` — how far the deepest return arc sweeps below the lowest
 *    node; `repeat`'s nests 16px shallower. The viewer's clears the abort
 *    chips (~36px below their nodes); the live view's clears only the labels.
 */
interface Geometry {
  rowPx: number;
  padT: number;
  returnDepth: number;
}

/** The sketch viewer's geometry — chips under every node. */
const VIEWER_GEOMETRY: Geometry = { rowPx: 52, padT: 30, returnDepth: 62 };
/** The live panel's — no chips, and every vertical px competes with the
 *  charts below it in a view that must fit the window without scrolling. */
const LIVE_GEOMETRY: Geometry = { rowPx: 34, padT: 24, returnDepth: 48 };

interface Frame {
  width: number;
  height: number;
  x: (n: TaskNode) => number;
  y: (n: TaskNode) => number;
  /** y of the lowest node — the return arcs hang from it. */
  lowY: number;
  /** The deepest return arc's sweep below `lowY` (see `Geometry`). */
  returnDepth: number;
}

function frameFor(model: TaskGraphModel, width: number, geometry: Geometry): Frame {
  const { rowPx, padT, returnDepth } = geometry;
  const cols = model.nodes.map((n) => n.column);
  const rows = model.nodes.map((n) => n.row);
  const minCol = Math.min(...cols);
  const colSpan = Math.max(Math.max(...cols) - minCol, 1);
  const minRow = Math.min(...rows);
  const lowY = padT + (Math.max(...rows) - minRow) * rowPx;
  const innerW = width - PAD_L - PAD_R;
  return {
    width,
    height: lowY + returnDepth + 16,
    x: (n) => PAD_L + ((n.column - minCol) / colSpan) * innerW,
    y: (n) => padT + (n.row - minRow) * rowPx,
    lowY,
    returnDepth,
  };
}

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
    // frame because `frameFor` pads by the return depth.
    const depth =
      frame.lowY + (edge.from === "iti" ? frame.returnDepth : frame.returnDepth - 16);
    return `M ${x1} ${y1 + R} C ${x1} ${depth}, ${x2} ${depth}, ${x2} ${y2 + R}`;
  }

  const dx = Math.max((x2 - x1) / 2, 20);
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
  if (Math.abs(y2 - y1) < 14) {
    return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 - 7 };
  }
  return { x: x1 + (x2 - x1) * 0.6, y: y1 + (y2 - y1) * 0.68 + 12 };
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
        strokeWidth={on ? 1.4 : 1}
        strokeDasharray={
          edge.kind === "abort" || edge.kind === "return" ? "6 7" : undefined
        }
        style={{ transition: "stroke 160ms" }}
      />
      {edge.label && from && to && (
        <text
          {...labelPos(frame.x(from), frame.y(from), frame.x(to), frame.y(to))}
          textAnchor="middle"
          className="fill-static font-mono"
          fontSize={9}
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
  live = false,
  reduceMotion = false,
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
  /** The running box is in this state right now (`LiveStateMachine`). */
  live?: boolean;
  /** Gates the token's `repeat: Infinity` pulse, which `MotionConfig`'s
   *  reduced-motion setting does not neutralise. */
  reduceMotion?: boolean;
  onEnter: () => void;
  onLeave: () => void;
  /** Absent in the live view, where a state is a reading, not a control. */
  onClick?: (() => void) | undefined;
  onChipEnter: (group: string) => void;
  onChipLeave: () => void;
  onChipClick: (group: string) => void;
}) {
  const x = frame.x(node);
  const y = frame.y(node);
  const dimmed = lit === false;
  const fill = fillFor(node);

  const anchor = node.labelAnchor ?? "below";
  const labelX = anchor === "right" ? x + R + 6 : x;
  const labelY = anchor === "right" ? y + 4 : anchor === "above" ? y - R - 9 : y + R + 15;
  const textAnchor = anchor === "right" ? "start" : "middle";

  // Chips stack under the label (or trail it, for right-anchored nodes).
  const chipX = anchor === "right" ? x + R + 6 : x;
  const chipY0 = anchor === "right" ? y + 17 : anchor === "above" ? y + R + 14 : labelY + 12;

  return (
    <g
      style={{
        opacity: dimmed ? 0.18 : 1,
        transition: "opacity 160ms",
        cursor: onClick ? "pointer" : "default",
      }}
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
          strokeWidth={1.3}
          initial={{ r: R, opacity: 0 }}
          animate={{ r: R + 5, opacity: 1 }}
          transition={springSnappy}
        />
      )}

      {/* The live token: `SessionJourney`'s StepStar grammar at this drawing's
          scale — a pulsing flat ring around the occupied state, no blur, no
          glow (§2.2). The steady inner ring keeps the state marked between
          pulses and under reduced motion. */}
      {live && !reduceMotion && (
        <motion.circle
          cx={x}
          cy={y}
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={1}
          initial={false}
          animate={{ r: [R + 2, R + 13], opacity: [0.5, 0] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: "easeOut" }}
          pointerEvents="none"
        />
      )}
      {live && (
        <circle
          cx={x}
          cy={y}
          r={R + 4.5}
          fill="none"
          stroke="var(--color-starlight)"
          strokeWidth={0.8}
          opacity={0.55}
          pointerEvents="none"
        />
      )}

      {node.kind === "outcome" ? (
        // A live outcome brightens in its own colour — "rewarded" flashing
        // green says more than a generic token colour would.
        <motion.rect
          x={x - R}
          y={y - R}
          width={R * 2}
          height={R * 2}
          rx={3}
          fill={fill}
          animate={{ fillOpacity: live ? 0.75 : 0.22 }}
          transition={springSnappy}
          stroke={fill}
          strokeWidth={1}
        />
      ) : (
        <motion.circle
          cx={x}
          cy={y}
          r={R}
          animate={{ fill: live ? "var(--color-starlight)" : "var(--color-nebula)" }}
          transition={springSnappy}
          stroke={node.kind === "abort" ? "var(--color-static)" : "var(--color-starlight)"}
          strokeOpacity={node.kind === "abort" ? 0.55 : 0.8}
          strokeWidth={1}
          strokeDasharray={node.kind === "abort" ? "5 5" : undefined}
        />
      )}

      <text
        x={labelX}
        y={labelY}
        textAnchor={textAnchor}
        fontSize={11}
        className={lit || live ? "fill-starlight" : "fill-static"}
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
            y={chipY0 + index * 12}
            textAnchor={textAnchor}
            fontSize={9}
            className={covered ? "fill-pulsar" : "fill-static"}
            style={{ opacity: chipOpacity, transition: "opacity 160ms, fill 160ms", cursor: "pointer" }}
            // The hover handlers must NOT stopPropagation: React synthesizes
            // enter/leave from pointerout/over, so stopping the chip's leave
            // also swallowed the node <g>'s — leaving the graph *from a chip*
            // left the node ringed and its pills lit forever. Only the click
            // stays fenced, so a chip click doesn't double as a node click.
            onPointerEnter={() => onChipEnter(chip.group)}
            onPointerLeave={() => onChipLeave()}
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
