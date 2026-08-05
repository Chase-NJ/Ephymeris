import { LINK_STROKE, NODE_PRIMARY } from "@/components/chrome/constellationStyle";
import type { SpecGraphNode } from "@/lib/specs/types";

/**
 * The drawing vocabulary of the compiled machine, shared by every surface that
 * draws one.
 *
 * SHAPE IS THE PRIMITIVE, FILL IS THE EPOCH — and both are a vocabulary rather
 * than a canvas detail, which is why they live here now that the Designer's
 * full graph and the wizard's per-epoch slice both draw them. Two private
 * copies of a legend is a legend that can disagree with itself.
 *
 * It stays a component module (`.tsx`, under `components/`) rather than joining
 * `lib/specs/layout.ts`: layout is pure geometry and React-free by doctrine,
 * and these return JSX.
 */

/**
 * Shape by primitive — the distinction the derived graph cannot draw:
 * circle DELAY · ring WAIT_ENTRY · square HOLD · open square WAIT_EXIT ·
 * bar PULSE · hexagon TERMINAL. Fill by band, so the rows read as the
 * listing's own sections.
 */
export function NodeShape({
  node,
  flagged,
}: {
  node: SpecGraphNode;
  flagged: boolean;
}) {
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
      return (
        <rect x={-6.5} y={-6.5} width={13} height={13} rx={2} fill={fill} stroke={stroke} />
      );
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
      return (
        <rect x={-8} y={-3.5} width={16} height={7} rx={1.5} fill={fill} stroke={stroke} />
      );
    case "TERMINAL":
      return (
        <path
          d="M 0 -8 L 7 -4 L 7 4 L 0 8 L -7 4 L -7 -4 Z"
          fill={fill}
          stroke={stroke}
          strokeWidth={1}
        />
      );
    default: // DELAY
      return <circle r={r} fill={fill} stroke={stroke} strokeWidth={1} />;
  }
}

export const BAND_FILL: Record<number, string> = {
  1: "var(--color-pulsar)",
  2: "var(--color-series-2, #7ea8c8)",
  3: "var(--color-series-3, #c8b57e)",
  4: "var(--color-ion)",
};

/**
 * The arrowhead, with its id as a PROP.
 *
 * An SVG marker is referenced by a document-level id, so two graphs on one page
 * sharing a hardcoded `spec-arrow` is an id collision — and the failure is the
 * quiet kind, where whichever `<defs>` mounted last wins and the other graph's
 * arrows point at a definition that has moved.
 */
export function ArrowMarker({ id }: { id: string }) {
  return (
    <defs>
      <marker
        id={id}
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
  );
}

/**
 * The path from one node to another, including the radius offsets that stop an
 * arrowhead landing inside the glyph it points at.
 *
 * Shared because those offsets are arithmetic tied to `NodeShape`'s radii — two
 * copies drift the moment a shape changes size, and the symptom is an arrowhead
 * buried under a node, which reads as a layout bug rather than a constant.
 */
export function edgePath(
  from: { x: number; y: number },
  to: { x: number; y: number },
  bow: number,
): string {
  const midY = (from.y + to.y) / 2;
  if (from.x === to.x && bow === 0) {
    return `M ${from.x} ${from.y + 9} L ${to.x} ${to.y - 11}`;
  }
  return `M ${from.x} ${from.y + 9} C ${from.x + bow} ${midY}, ${to.x + bow} ${midY}, ${to.x} ${to.y - 11}`;
}
