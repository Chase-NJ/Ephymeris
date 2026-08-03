import { useMemo, useState } from "react";

import {
  LINK_OPACITY_DIM,
  LINK_STROKE,
  NODE_PRIMARY,
} from "@/components/chrome/constellationStyle";
import { layoutSpecGraph } from "@/lib/specs/layout";
import type { PlacedDiagnostics } from "@/lib/specs/diagnostics";
import type { SpecGraph as SpecGraphData, SpecGraphNode } from "@/lib/specs/types";

/**
 * The compiled MACHINE graph — six node primitives, trigger-keyed edges —
 * deliberately not a second mode of `TaskGraph.tsx`. That component draws the
 * behavioural graph derived from a task.json (states an animal passes
 * through, a live token); this draws what the interpreter executes. Collapsing
 * the six primitives onto its three node kinds would destroy exactly the
 * distinction a topology editor exists to show — and TaskGraph serves the
 * live-session path, which this feature has no business perturbing.
 *
 * What IS shared is the visual vocabulary (stroke tokens, the return-arc
 * treatment, outcome-ish colouring), the same relationship TaskRail already
 * has to TaskGraph: read as the same family, share no model.
 *
 * Hovering a node shows its listing block — duration, watches, out-edges with
 * triggers and guards — because the listing is the artifact the graph must
 * agree with, and showing its own words is how the two stay one thing.
 */
export function SpecGraph({
  graph,
  placed,
}: {
  graph: SpecGraphData;
  placed: PlacedDiagnostics | null;
}) {
  const layout = useMemo(() => layoutSpecGraph(graph), [graph]);
  const [hover, setHover] = useState<number | null>(null);

  const hovered = hover !== null ? layout.nodes[hover] : null;
  const outEdges = useMemo(
    () => (hover === null ? [] : graph.edges.filter((e) => e.src === hover)),
    [graph, hover],
  );

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="w-full"
        style={{ maxHeight: 380 }}
        role="img"
        aria-label="Compiled state machine"
      >
        {/* Band gutters and labels — the listing's own section rules. */}
        {layout.bands.map((band) => (
          <g key={band.band}>
            <text
              x={band.x0}
              y={16}
              className="font-mono"
              fontSize={9}
              fill="var(--color-static)"
              opacity={0.8}
            >
              {band.band} · {band.label}
            </text>
            <line
              x1={band.x0 - 14}
              y1={24}
              x2={band.x0 - 14}
              y2={layout.height - 8}
              stroke="var(--color-halo)"
              strokeWidth={band.band === 1 ? 0 : 1}
            />
          </g>
        ))}

        {/* Edges under nodes. Returns are the faintest thing on the canvas and
        are never labelled — the TaskGraph convention, kept on purpose. */}
        {layout.edges.map(({ edge, from, to, isReturn }) => {
          const dim =
            hover !== null && edge.src !== hover && edge.dst !== hover;
          if (isReturn) {
            const lift = Math.max(36, (from.x - to.x) * 0.12);
            return (
              <path
                key={edge.index}
                d={`M ${from.x} ${from.y} C ${from.x} ${from.y + lift}, ${to.x} ${to.y + lift}, ${to.x} ${to.y + 8}`}
                fill="none"
                stroke={LINK_STROKE}
                strokeWidth={0.7}
                opacity={LINK_OPACITY_DIM}
              />
            );
          }
          const mid = (from.x + to.x) / 2;
          return (
            <g key={edge.index} opacity={dim ? 0.18 : 1}>
              <path
                d={
                  from.y === to.y
                    ? `M ${from.x + 9} ${from.y} L ${to.x - 11} ${to.y}`
                    : `M ${from.x} ${from.y} C ${mid} ${from.y}, ${mid} ${to.y}, ${to.x - 11} ${to.y}`
                }
                fill="none"
                stroke={LINK_STROKE}
                strokeWidth={0.9}
                opacity={0.45}
                markerEnd="url(#spec-arrow)"
              />
              {edge.guard && (
                <text
                  x={mid}
                  y={(from.y + to.y) / 2 - 5}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={7.5}
                  fill="var(--color-static)"
                >
                  {edge.guard}
                </text>
              )}
            </g>
          );
        })}

        <defs>
          <marker
            id="spec-arrow"
            viewBox="0 0 8 8"
            refX={7}
            refY={4}
            markerWidth={7}
            markerHeight={7}
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 8 4 L 0 8 z" fill={LINK_STROKE} opacity={0.55} />
          </marker>
        </defs>

        {layout.nodes.map(({ node, x, y }, i) => {
          const diags = placed?.byNode.get(`S${String(node.index).padStart(2, "0")}`);
          return (
            <g
              key={node.index}
              transform={`translate(${x}, ${y})`}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              className="cursor-default"
            >
              <NodeShape node={node} flagged={Boolean(diags?.length)} />
              <text
                y={22}
                textAnchor="middle"
                fontSize={8.5}
                fill={hover === i ? "var(--color-starlight)" : "var(--color-static)"}
              >
                {node.label}
              </text>
              {node.strobeName && (
                <text
                  y={31}
                  textAnchor="middle"
                  className="font-mono"
                  fontSize={7}
                  fill="var(--color-static)"
                  opacity={0.7}
                >
                  {node.strobeName}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      {hovered && (
        <div className="pointer-events-none absolute right-2 top-2 w-[240px] rounded-sm border border-halo bg-void/90 px-2.5 py-2 font-mono text-[10px] leading-relaxed text-static">
          <div className="text-starlight">
            S{String(hovered.node.index).padStart(2, "0")} {hovered.node.type}
            {"  "}
            <span className="text-static">{hovered.node.label}</span>
          </div>
          {hovered.node.durationId && (
            <div>
              {hovered.node.durationId} = {hovered.node.durationMs} ms
            </div>
          )}
          {hovered.node.watch.length > 0 && <div>watches {hovered.node.watch.join(", ")}</div>}
          {hovered.node.silentByDesign && <div>— silent by design (D4)</div>}
          {outEdges.map((e) => (
            <div key={e.index}>
              {e.trigger}
              {e.channel ? `(${e.channel})` : ""}
              {e.guard ? ` [${e.guard}]` : ""} → S{String(e.dst).padStart(2, "0")}
              {e.effect ? `  ${e.effect}` : ""}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Shape by primitive — the distinction the derived graph cannot draw:
 * circle DELAY · ring WAIT_ENTRY · square HOLD · open square WAIT_EXIT ·
 * bar PULSE · hexagon TERMINAL. Fill by band, so the columns read as the
 * listing's own sections.
 */
function NodeShape({ node, flagged }: { node: SpecGraphNode; flagged: boolean }) {
  const fill = BAND_FILL[node.band] ?? NODE_PRIMARY;
  const stroke = flagged ? "var(--color-status-error)" : "var(--color-halo)";
  const r = 7;
  switch (node.type) {
    case "WAIT_ENTRY":
      return (
        <>
          <circle r={r} fill="var(--color-void)" stroke={fill} strokeWidth={2} />
          <circle r={2.2} fill={fill} />
          {flagged && <circle r={r + 3} fill="none" stroke={stroke} strokeWidth={1} />}
        </>
      );
    case "HOLD":
      return <rect x={-6.5} y={-6.5} width={13} height={13} rx={2} fill={fill} stroke={stroke} />;
    case "WAIT_EXIT":
      return (
        <rect
          x={-6.5}
          y={-6.5}
          width={13}
          height={13}
          rx={2}
          fill="var(--color-void)"
          stroke={fill}
          strokeWidth={2}
        />
      );
    case "PULSE":
      return <rect x={-3.5} y={-8} width={7} height={16} rx={1.5} fill={fill} stroke={stroke} />;
    case "TERMINAL":
      return (
        <path
          d="M -8 0 L -4 -7 L 4 -7 L 8 0 L 4 7 L -4 7 Z"
          fill={fill}
          stroke={stroke}
          strokeWidth={1}
        />
      );
    default: // DELAY
      return <circle r={r} fill={fill} stroke={stroke} strokeWidth={1} />;
  }
}

const BAND_FILL: Record<number, string> = {
  1: "var(--color-pulsar)",
  2: "var(--color-series-2, #7ea8c8)",
  3: "var(--color-series-3, #c8b57e)",
  4: "var(--color-ion)",
};
