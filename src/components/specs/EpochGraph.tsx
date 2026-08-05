import { useMemo } from "react";

import { LINK_STROKE } from "@/components/chrome/constellationStyle";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import {
  fitMono,
  LABEL_BUDGET,
  layoutSpecGraph,
  type LayoutScope,
} from "@/lib/specs/layout";
import { sid } from "@/lib/specs/selection";
import type { SpecGraph } from "@/lib/specs/types";
import { ArrowMarker, edgePath, NodeShape } from "./nodeShape";

/**
 * One epoch of the compiled machine, live, above the step that edits it.
 *
 * THE OBJECTION THIS ANSWERS, AND THE ONE IT KEEPS. docs/specs.md removed the
 * machine graph from the wizard because twenty-six nodes and thirty-six edges
 * restructuring on every keystroke, in front of someone who has not yet decided
 * how many odours there are, made creating a task read like editing one. That
 * was right about the WHOLE graph and wrong about a slice of it: four to ten
 * nodes, exactly the ones the step below edits, is the picture that answers
 * "what am I changing" — which the four one-line epoch cards it replaced could
 * not.
 *
 * READ-ONLY, AND STRUCTURALLY SO. No pan, no zoom, no selection, no hover
 * card, `pointerEvents: none` on the whole SVG. Editing is the Designer's job
 * and the step below's; a picture that highlighted on hover would invite a
 * click that does nothing.
 *
 * WHY THE 120 MS SNAP-BACK BUG CANNOT HAPPEN HERE. `SpecCanvas` needs
 * `graphSignature` because it holds view state (zoom, pan) that an effect
 * resets, and keying that reset on a payload identity which changes every
 * compile snapped the operator to the top of a graph they were reading. This
 * holds no view state at all, so there is nothing to reset. What remains — a
 * picture that jumps because text changed — is prevented by the layout itself:
 * every coordinate is a function of `band`, `type` and the edge list, which are
 * exactly the fields `graphSignature` hashes, so editing a duration changes
 * captions and moves nothing. Two rules keep that true:
 *
 *   1. No framer `layout` animation in here. It re-measures on every render and
 *      would reintroduce the jump from the other side.
 *   2. The `scope` prop must be memoised by the caller, or it is a fresh object
 *      every render and the layout memo never hits.
 */
export function EpochGraph({
  graph,
  scope,
  stale,
  placed,
  maxHeight = 330,
  emptyNote,
}: {
  graph: SpecGraph | null;
  /** Memoise this — see rule 2 above. */
  scope: LayoutScope;
  /** The current document does not compile; this is the last picture that did. */
  stale: boolean;
  placed?: PlacedDiagnostics | null;
  maxHeight?: number;
  /** What to say when the scope holds no nodes. A go/no-go task really has no
   * outcome epoch — `b.band(Band.OUTCOME)` sits inside the rewarded branch — so
   * this is a reachable, ordinary state and not a defensive fallback. */
  emptyNote?: string;
}) {
  const layout = useMemo(
    () => (graph ? layoutSpecGraph(graph, { scope, returns: false }) : null),
    [graph, scope],
  );

  // Never compiled at all — the first frames before the skeleton's compile
  // lands. The rail and the step's own heading already say where we are.
  if (graph === null || layout === null) return null;

  if (layout.nodes.length === 0) {
    return emptyNote ? (
      <p className="rounded-sm border border-halo px-2.5 py-2 text-[10.5px] leading-relaxed text-static">
        {emptyNote}
      </p>
    ) : null;
  }

  const arrow = "epoch-arrow";

  return (
    <div className="flex flex-col gap-1 rounded-sm border border-halo px-2.5 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-mono text-[10px] tracking-wider text-static uppercase">
          {layout.bands.map((b) => b.label).join(" → ")}
        </div>
        <div className="font-mono text-[10px] text-static/70">
          {layout.nodes.length} state{layout.nodes.length === 1 ? "" : "s"}
        </div>
      </div>

      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        preserveAspectRatio="xMinYMin meet"
        // `meet` is right here in a way it is not on the Designer's canvas: a
        // slice is short and wide, so fitting by width leaves no thin column.
        style={{
          width: "100%",
          maxHeight,
          opacity: stale ? 0.45 : 1,
          transition: "opacity 180ms ease",
          pointerEvents: "none",
        }}
        role="img"
        aria-label={`States in the ${layout.bands.map((b) => b.label).join(" and ")} epoch`}
      >
        <ArrowMarker id={arrow} />

        {layout.edges.map((laid) => (
          <g key={`e${laid.edge.index}`}>
            <path
              d={edgePath(laid.from, laid.to, laid.bow)}
              fill="none"
              stroke={LINK_STROKE}
              strokeWidth={0.9}
              opacity={0.45}
              markerEnd={`url(#${arrow})`}
            />
            {laid.label !== null && (
              <text
                x={laid.labelX}
                y={laid.labelY}
                textAnchor={laid.labelAnchor}
                className="font-mono"
                fontSize={7.5}
                fill="var(--color-static)"
              >
                {fitMono(laid.label, LABEL_BUDGET - 14, 7.5)}
                <title>{laid.label}</title>
              </text>
            )}
          </g>
        ))}

        {/* Edges that leave or enter the slice, as short capped arrows. Drawing
        nothing here would be a lie of omission: an epoch's abort chains LEAVE,
        and that is most of what the picture is for. */}
        {layout.stubs.map((stub) => (
          <g key={`s${stub.edge.index}`} opacity={0.5}>
            <path
              d={`M ${stub.from.x} ${stub.from.y + (stub.direction === "out" ? 9 : 0)} L ${stub.to.x} ${stub.to.y}`}
              fill="none"
              stroke={LINK_STROKE}
              strokeWidth={0.8}
              strokeDasharray="2 2"
              markerEnd={`url(#${arrow})`}
            />
            <text
              x={stub.labelX}
              y={stub.labelY}
              className="font-mono"
              fontSize={7}
              fill="var(--color-static)"
            >
              {fitMono(stub.label, LABEL_BUDGET, 7)}
              <title>{stub.detail}</title>
            </text>
          </g>
        ))}

        {layout.nodes.map(({ node, x, y }) => (
          <g key={node.index} transform={`translate(${x}, ${y})`}>
            <NodeShape
              node={node}
              flagged={Boolean(placed?.byNode.get(sid(node.index))?.length)}
            />
            <text
              x={13}
              y={node.strobeName ? -1 : 3}
              fontSize={8.5}
              fill="var(--color-static)"
            >
              {fitMono(node.label, LABEL_BUDGET, 8.5)}
              <title>{node.label}</title>
            </text>
            {node.strobeName && (
              <text x={13} y={8} className="font-mono" fontSize={7} fill="var(--color-static)">
                {fitMono(node.strobeName, LABEL_BUDGET, 7)}
              </text>
            )}
          </g>
        ))}
      </svg>

      {stale && (
        <p className="text-[10px] leading-relaxed text-static/70">
          The last shape that compiled — the errors below say why this is stale.
        </p>
      )}
    </div>
  );
}
