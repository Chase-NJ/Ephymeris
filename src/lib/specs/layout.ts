/**
 * Deterministic layout for the compiled machine graph.
 *
 * The compiler emits no coordinates — this is where they come from, as a PURE
 * function of the `SpecGraph` payload. No randomness, no measured text, no
 * simulation: two compiles of the same spec must produce an identical picture,
 * for the same reason `canonical.to_json` sorts its keys — a rendering that
 * moves when nothing moved is worthless as a thing to compare.
 *
 * The rules, in order of authority:
 *
 * 1. BAND = COLUMN GROUP. Four bands left to right with a labelled gutter,
 *    matching the listing's `── 1 · engagement ──` rules exactly.
 * 2. X WITHIN A BAND = INDEX ORDER. The template emits nodes in the order a
 *    trial visits them; that is authored intent, it is topological by
 *    construction, and — decisively — it is the order the listing prints.
 *    The graph and the review artifact must not disagree about ordering.
 * 3. Y BY BRANCH. Nodes that can reach a LATER band sit on the spine (y = 0);
 *    everything else is a branch — a penalty chain, an outcome fan — pushed
 *    below, one row per connected branch, in first-encountered order. That
 *    matches the convention the operator already reads on the legacy derived
 *    graph: the main line runs straight, aborts hang underneath.
 * 4. ADVANCE/REPEAT edges are RETURNS — excluded from reachability, drawn as
 *    faint arcs by the renderer, never labelled.
 */

import type { SpecGraph, SpecGraphEdge, SpecGraphNode } from "./types";

export interface LaidOutNode {
  node: SpecGraphNode;
  x: number;
  y: number;
}

export interface LaidOutEdge {
  edge: SpecGraphEdge;
  from: { x: number; y: number };
  to: { x: number; y: number };
  isReturn: boolean;
}

export interface BandBox {
  band: number;
  label: string;
  x0: number;
  x1: number;
}

export interface SpecLayout {
  nodes: LaidOutNode[];
  edges: LaidOutEdge[];
  bands: BandBox[];
  width: number;
  height: number;
}

export const BAND_LABELS: Record<number, string> = {
  1: "engagement",
  2: "sampling",
  3: "response",
  4: "outcome",
};

const COL_W = 92;
const ROW_H = 74;
const BAND_GUTTER = 40;
const MARGIN_X = 24;
const MARGIN_Y = 46;

function isReturn(edge: SpecGraphEdge): boolean {
  return edge.trigger === "ADVANCE" || edge.trigger === "REPEAT";
}

/** node index → can it reach a node in a later band (returns excluded)? */
function reachesLaterBand(graph: SpecGraph): boolean[] {
  const out = new Map<number, number[]>();
  for (const edge of graph.edges) {
    if (isReturn(edge)) continue;
    const list = out.get(edge.src);
    if (list) list.push(edge.dst);
    else out.set(edge.src, [edge.dst]);
  }
  const bands = graph.nodes.map((n) => n.band);
  // Fixed-point over "max band reachable from here". The graph is ≤64 nodes by
  // the compiler's own capacity rule, so an O(n·e) sweep is nothing.
  const maxReach = [...bands];
  let moved = true;
  while (moved) {
    moved = false;
    for (const [src, dsts] of out) {
      for (const dst of dsts) {
        const candidate = maxReach[dst] ?? 0;
        if (candidate > (maxReach[src] ?? 0)) {
          maxReach[src] = candidate;
          moved = true;
        }
      }
    }
  }
  return graph.nodes.map((n, i) => (maxReach[i] ?? 0) > n.band);
}

/**
 * Assign each off-spine node a branch row within its band: members of one
 * connected off-spine chain share a row, chains stack in first-encountered
 * (= index) order. Union-find over non-return edges whose BOTH ends are
 * off-spine and share a band.
 */
function branchRows(graph: SpecGraph, spine: boolean[]): number[] {
  const parent = graph.nodes.map((_, i) => i);
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]!]!;
      i = parent[i]!;
    }
    return i;
  };
  const union = (a: number, b: number) => {
    parent[find(a)] = find(b);
  };
  for (const edge of graph.edges) {
    if (isReturn(edge)) continue;
    if (spine[edge.src] || spine[edge.dst]) continue;
    if (graph.nodes[edge.src]!.band !== graph.nodes[edge.dst]!.band) continue;
    union(edge.src, edge.dst);
  }

  const rows = graph.nodes.map(() => 0);
  const rowOfChain = new Map<string, number>();
  const nextRow = new Map<number, number>();
  for (const [i, node] of graph.nodes.entries()) {
    if (spine[i]) continue;
    const key = `${node.band}:${find(i)}`;
    let row = rowOfChain.get(key);
    if (row === undefined) {
      row = (nextRow.get(node.band) ?? 0) + 1;
      nextRow.set(node.band, row);
      rowOfChain.set(key, row);
    }
    rows[i] = row;
  }
  return rows;
}

export function layoutSpecGraph(graph: SpecGraph): SpecLayout {
  const spine = reachesLaterBand(graph);
  // The last band has no later band to reach, so everything there would be a
  // "branch". Its spine is the first chain instead: the node the previous band
  // enters first, in index order — for four_epoch that is the reward path.
  const lastBand = Math.max(0, ...graph.nodes.map((n) => n.band));
  const firstInLast = graph.nodes.findIndex((n) => n.band === lastBand);
  if (firstInLast >= 0) spine[firstInLast] = true;

  const rows = branchRows(graph, spine);

  // x: bands left to right; within a band, nodes in index order.
  const bandOf = new Map<number, number[]>();
  for (const [i, node] of graph.nodes.entries()) {
    const list = bandOf.get(node.band);
    if (list) list.push(i);
    else bandOf.set(node.band, [i]);
  }
  const bandsSorted = [...bandOf.keys()].sort((a, b) => a - b);

  const xOf = new Array<number>(graph.nodes.length).fill(0);
  const bands: BandBox[] = [];
  let cursor = MARGIN_X;
  for (const band of bandsSorted) {
    const members = bandOf.get(band)!;
    const x0 = cursor;
    for (const [pos, i] of members.entries()) {
      xOf[i] = cursor + pos * COL_W;
    }
    const x1 = cursor + (members.length - 1) * COL_W;
    bands.push({ band, label: BAND_LABELS[band] ?? `band ${band}`, x0, x1 });
    cursor = x1 + COL_W + BAND_GUTTER;
  }

  const maxRow = Math.max(0, ...rows);
  const nodes: LaidOutNode[] = graph.nodes.map((node, i) => ({
    node,
    x: xOf[i]!,
    y: MARGIN_Y + rows[i]! * ROW_H,
  }));

  const at = (i: number) => ({ x: nodes[i]!.x, y: nodes[i]!.y });
  const edges: LaidOutEdge[] = graph.edges.map((edge) => ({
    edge,
    from: at(edge.src),
    to: at(edge.dst),
    isReturn: isReturn(edge),
  }));

  return {
    nodes,
    edges,
    bands,
    width: cursor - BAND_GUTTER + MARGIN_X,
    height: MARGIN_Y + (maxRow + 1) * ROW_H + 24,
  };
}
