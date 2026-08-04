/**
 * Deterministic layout for the compiled machine graph — vertical, top to
 * bottom.
 *
 * The compiler emits no coordinates — this is where they come from, as a PURE
 * function of the `SpecGraph` payload. No randomness, no measured text, no
 * simulation: two compiles of the same spec must produce an identical picture,
 * for the same reason `canonical.to_json` sorts its keys — a rendering that
 * moves when nothing moved is worthless as a thing to compare.
 *
 * The rules, in order of authority:
 *
 * 1. BAND = ROW GROUP. Four bands top to bottom with a header row, matching
 *    the listing's `── 1 · engagement ──` rules exactly. A trial reads down
 *    the page the way it reads down the listing.
 * 2. THE FLOW AXIS IS VERTICAL, AND ORDER MATCHES THE LISTING: within every
 *    lane, flow position is strictly increasing in node index; lanes are
 *    ordered by the index of their first member; bands by band number.
 *    Reading lane 0 top to bottom reproduces the listing's main line — the
 *    graph and the review artifact must not disagree about ordering.
 * 3. X BY BRANCH (lanes). Nodes that can reach a LATER band sit on the spine
 *    (lane 0); everything else is a branch — a penalty chain, an outcome fan —
 *    pushed to the next lane, one lane per connected branch, in
 *    first-encountered order. A branch is COMPACTED to start at the flow
 *    position of the spine node it leaves from, not at its global index —
 *    otherwise every branch node pushes the spine along and leaves empty
 *    spine slots (band 1 of grgl_2odor used to consume 10 slots for a
 *    6-deep spine).
 * 4. ADVANCE/REPEAT edges are RETURNS — excluded from reachability, drawn as
 *    faint arcs up a reserved right-hand rail, never labelled.
 * 5. TEXT IS BUDGETED, NEVER OVERFLOWING. Band headers live in a fixed left
 *    gutter so they cannot reach a lane; node labels are left-anchored beside
 *    the node inside `LABEL_BUDGET`; everything is fitted with `fitMono`,
 *    which is character arithmetic, not measurement — determinism again.
 */

import type { SpecGraph, SpecGraphEdge, SpecGraphNode } from "./types";
import { scoredClass } from "./selection";

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
  /** `guard` or the `score:<class>` effect — precomputed so the renderer never
   * decides what a label says. Null on returns and unlabelled edges. */
  label: string | null;
  labelX: number;
  labelY: number;
  labelAnchor: "start" | "middle";
  /** Lateral bow for parallel edges sharing (src, dst), so two edges read as
   * two. Zero when the pair is alone. */
  bow: number;
}

export interface BandBox {
  band: number;
  label: string;
  y0: number;
  y1: number;
}

export interface SpecLayout {
  nodes: LaidOutNode[];
  edges: LaidOutEdge[];
  bands: BandBox[];
  width: number;
  height: number;
  laneCount: number;
  /** The x of the return rail — the vertical track ADVANCE/REPEAT arcs ride. */
  returnRailX: number;
}

export const BAND_LABELS: Record<number, string> = {
  1: "engagement",
  2: "sampling",
  3: "response",
  4: "outcome",
};

/**
 * One line per band, read off the topology knobs — the band header's subtitle.
 *
 * Beside `BAND_LABELS` because it answers the same question the labels do, one
 * level down: the label says which epoch, this says what shape the epoch is in.
 * Band 4 is deliberately blank — the outcome epoch's shape is the contingency's
 * outcome map, not a knob, so there is nothing here that would not be a guess.
 *
 * Shared because the Designer and the wizard drew the same header from two
 * identical private copies, which is a caption that can disagree with itself
 * about what the operator is looking at.
 */
export function bandReadouts(
  knobs: Record<string, unknown> | null,
): Record<number, string> {
  const k = knobs ?? {};
  const stages = typeof k["n_sampling_stages"] === "number" ? k["n_sampling_stages"] : null;
  const ports = Array.isArray(k["response_ports"]) ? k["response_ports"].length : 0;
  return {
    1: k["commit_hold"] === false ? "no commitment hold" : "commitment hold on",
    2:
      stages === 0
        ? "epoch skipped"
        : `${stages ?? "?"} stage${stages === 1 ? "" : "s"}` +
          (stages !== null && stages > 1 ? ` + ${stages - 1} gap` : "") +
          (k["retention_delay"] === true ? " + retention" : ""),
    3: `${k["response_mode"] === "go_nogo" ? "go / no-go" : "n-alternative"} · ${ports} port${
      ports === 1 ? "" : "s"
    }`,
    4: "",
  };
}

export const NODE_PITCH_Y = 56;
export const LANE_PITCH_X = 168;
export const BAND_GAP_Y = 34;
/** Room for three stacked header lines before the band's first node. */
export const BAND_HEADER_H = 30;
/** Fixed left column carrying the band name and readout — text there
 * structurally cannot overrun a lane. */
export const GUTTER_X = 130;
const RETURN_GUTTER = 36;
const MARGIN_TOP = 12;
/** Without this the last row's strobe line clipped at the SVG edge. */
const MARGIN_BOTTOM = 22;
/** Text room to the right of each node before the next lane begins. */
export const LABEL_BUDGET = LANE_PITCH_X - 22;

/** JetBrains Mono advance ≈ 0.6 em. Character arithmetic, not measurement —
 * the same string always truncates the same way. Callers put the full string
 * in a `<title>` so hover still gives the whole thing. */
export const MONO_ADVANCE = 0.6;

export function fitMono(s: string, widthPx: number, fontSize: number): string {
  const budget = Math.max(1, Math.floor(widthPx / (fontSize * MONO_ADVANCE)));
  if (s.length <= budget) return s;
  return `${s.slice(0, Math.max(0, budget - 1))}…`;
}

/**
 * The graph's structural identity: what would make the picture a DIFFERENT
 * picture, as opposed to the same picture with different text. Durations,
 * labels, strobe names and watch sets are deliberately excluded — resetting
 * the view because a strobe name changed is the same bug as resetting it
 * because the compile returned a fresh object.
 */
export function graphSignature(g: SpecGraph): string {
  return (
    `${g.nodes.length}/${g.edges.length}:` +
    g.nodes.map((n) => `${n.symbol}.${n.band}.${n.type}`).join(",") +
    "|" +
    g.edges.map((e) => `${e.src}>${e.dst}.${e.trigger}`).join(",")
  );
}

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
 * Which spine node(s) each off-spine node descends from, within its band.
 *
 * This is what makes lanes mean "one branch" rather than "one connected blob".
 * The abort chains of a four_epoch band both end at the SAME repeat terminal,
 * so plain connectivity fuses every branch in the band into one component and
 * stacks it — band 1 of grgl_2odor came out 9 rows deep in a single lane, which
 * is the shape this whole rewrite exists to avoid. Descent separates them:
 * two chains that merely share a sink are still two branches.
 */
function originsOf(graph: SpecGraph, spine: boolean[]): Array<Set<number>> {
  const origins = graph.nodes.map(() => new Set<number>());
  const inBand = (a: number, b: number) =>
    graph.nodes[a]!.band === graph.nodes[b]!.band;

  for (const edge of graph.edges) {
    if (isReturn(edge)) continue;
    if (!spine[edge.src] || spine[edge.dst]) continue;
    if (!inBand(edge.src, edge.dst)) continue;
    origins[edge.dst]!.add(edge.src);
  }
  // Fixed point along off-spine edges. ≤64 nodes by the compiler's capacity
  // rule, so the sweep is free.
  let moved = true;
  while (moved) {
    moved = false;
    for (const edge of graph.edges) {
      if (isReturn(edge)) continue;
      if (spine[edge.src] || spine[edge.dst]) continue;
      if (!inBand(edge.src, edge.dst)) continue;
      const before = origins[edge.dst]!.size;
      for (const o of origins[edge.src]!) origins[edge.dst]!.add(o);
      if (origins[edge.dst]!.size !== before) moved = true;
    }
  }
  return origins;
}

/**
 * Lane per off-spine node: spine is lane 0, each branch takes the next lane
 * within its band in origin-index order, and a JOIN — a node several branches
 * converge on, like the shared repeat terminal — rides the last of the lanes
 * that feed it rather than claiming one of its own. Lane numbering restarts
 * per band, so band 2's single branch and band 3's three don't force each
 * other wider.
 */
function laneOf(
  graph: SpecGraph,
  spine: boolean[],
  origins: Array<Set<number>>,
): number[] {
  const lanes = graph.nodes.map(() => 0);
  const laneOfOrigin = new Map<string, number>();
  const nextLane = new Map<number, number>();

  // Branches first, so a join has lanes to point at.
  for (const [i, node] of graph.nodes.entries()) {
    if (spine[i] || origins[i]!.size !== 1) continue;
    const origin = [...origins[i]!][0]!;
    const key = `${node.band}:${origin}`;
    let lane = laneOfOrigin.get(key);
    if (lane === undefined) {
      lane = (nextLane.get(node.band) ?? 0) + 1;
      nextLane.set(node.band, lane);
      laneOfOrigin.set(key, lane);
    }
    lanes[i] = lane;
  }

  for (const [i, node] of graph.nodes.entries()) {
    if (spine[i] || origins[i]!.size === 1) continue;
    const candidates = [...origins[i]!]
      .map((o) => laneOfOrigin.get(`${node.band}:${o}`))
      .filter((l): l is number => l !== undefined);
    if (candidates.length > 0) {
      lanes[i] = Math.max(...candidates);
    } else {
      // Reachable from no spine node in this band (an orphan, or a node whose
      // only predecessors are in an earlier band): its own lane.
      const lane = (nextLane.get(node.band) ?? 0) + 1;
      nextLane.set(node.band, lane);
      lanes[i] = lane;
    }
  }
  return lanes;
}

export function layoutSpecGraph(graph: SpecGraph): SpecLayout {
  const spine = reachesLaterBand(graph);

  /*
   * The last band has no later band to reach, so by the rule above every node
   * in it would be a branch. Its spine is a CHAIN from its first node,
   * following the lowest-index in-band successor at each step — not everything
   * reachable, which was the same mistake in the other direction: a go/no-go
   * task ends at band 3, and sweeping the whole band onto the spine drew its
   * two genuine forks as one straight column of nine.
   *
   * Lowest index is the listing's own order, and it is a CHOICE where the
   * machine offers no main line: at a go/no-go response window neither
   * "entered a port" nor "window expired" is structurally the main path, so
   * what matters is that both are drawn as forks — which they now are.
   */
  const lastBand = Math.max(0, ...graph.nodes.map((n) => n.band));
  let step = graph.nodes.findIndex((n) => n.band === lastBand);
  while (step >= 0 && !spine[step]) {
    spine[step] = true;
    const successors = graph.edges
      .filter(
        (e) => !isReturn(e) && e.src === step && graph.nodes[e.dst]!.band === lastBand,
      )
      .map((e) => e.dst)
      .filter((d) => !spine[d]);
    step = successors.length > 0 ? Math.min(...successors) : -1;
  }

  const origins = originsOf(graph, spine);
  const lanes = laneOf(graph, spine, origins);

  // Group node indices by band, in index order.
  const bandOf = new Map<number, number[]>();
  for (const [i, node] of graph.nodes.entries()) {
    const list = bandOf.get(node.band);
    if (list) list.push(i);
    else bandOf.set(node.band, [i]);
  }
  const bandsSorted = [...bandOf.keys()].sort((a, b) => a - b);

  /*
   * Flow position within each band — THE COMPACTION.
   *
   * Spine nodes take 0, 1, 2, … in index order. A branch starts at the
   * position just BELOW the spine node it descends from, rather than at its
   * own global index — otherwise every branch node pushes the spine one row
   * further down and leaves the spine's own rows empty, which is what made
   * band 1 ten rows deep for a three-node spine. A join sits below everything
   * that feeds it. A per-lane cursor only ever moves down, so two branches
   * sharing a lane can never overlap.
   */
  const pos = new Array<number>(graph.nodes.length).fill(0);
  const bandHeight = new Map<number, number>();

  const predsOf = (i: number): number[] =>
    graph.edges
      .filter((e) => !isReturn(e) && e.dst === i && graph.nodes[e.src]!.band === graph.nodes[i]!.band)
      .map((e) => e.src);

  for (const band of bandsSorted) {
    const members = bandOf.get(band)!;
    let spineCursor = 0;
    for (const i of members) {
      if (spine[i]) pos[i] = spineCursor++;
    }

    const laneCursor = new Map<number, number>();
    const placed = new Set<number>(members.filter((i) => spine[i]));

    // Branches, grouped by descent, in origin-index order.
    for (const i of members) {
      if (spine[i] || placed.has(i) || origins[i]!.size !== 1) continue;
      const lane = lanes[i]!;
      const origin = [...origins[i]!][0]!;
      const chain = members.filter(
        (m) => !spine[m] && !placed.has(m) && lanes[m] === lane && origins[m]!.size === 1,
      );
      const start = spine[origin] ? (pos[origin] ?? 0) + 1 : 0;
      let k = 0;
      for (const m of chain) {
        pos[m] = Math.max(start + k, laneCursor.get(lane) ?? 0);
        laneCursor.set(lane, pos[m]! + 1);
        placed.add(m);
        k++;
      }
    }

    // Joins last: a node several branches converge on goes below all of them.
    // Index order suffices because a join's in-band predecessors precede it —
    // the emitter builds a chain before the node it ends at.
    for (const i of members) {
      if (placed.has(i)) continue;
      const lane = lanes[i]!;
      const below = Math.max(
        0,
        ...predsOf(i).map((p) => (placed.has(p) ? (pos[p] ?? 0) + 1 : 0)),
      );
      pos[i] = Math.max(below, laneCursor.get(lane) ?? 0);
      laneCursor.set(lane, pos[i]! + 1);
      placed.add(i);
    }

    bandHeight.set(band, 1 + Math.max(0, ...members.map((i) => pos[i]!)));
  }

  // y per band, stacked with headers and gaps.
  const bands: BandBox[] = [];
  const yOf = new Array<number>(graph.nodes.length).fill(0);
  let cursor = MARGIN_TOP;
  for (const band of bandsSorted) {
    const members = bandOf.get(band)!;
    const y0 = cursor;
    const rows = bandHeight.get(band)!;
    for (const i of members) {
      yOf[i] = y0 + BAND_HEADER_H + pos[i]! * NODE_PITCH_Y + 18;
    }
    const y1 = y0 + BAND_HEADER_H + rows * NODE_PITCH_Y;
    bands.push({ band, label: BAND_LABELS[band] ?? `band ${band}`, y0, y1 });
    cursor = y1 + BAND_GAP_Y;
  }
  const height = cursor - BAND_GAP_Y + MARGIN_BOTTOM;

  const laneCount = 1 + Math.max(0, ...lanes);
  const xOf = (i: number) => GUTTER_X + lanes[i]! * LANE_PITCH_X;
  const rightmostLabel = GUTTER_X + (laneCount - 1) * LANE_PITCH_X + 13 + LABEL_BUDGET;
  const returnRailX = rightmostLabel + 24;
  const width = returnRailX + RETURN_GUTTER - 24;

  const nodes: LaidOutNode[] = graph.nodes.map((node, i) => ({
    node,
    x: xOf(i),
    y: yOf[i]!,
  }));

  /*
   * Edges, with their labels PLACED HERE rather than in the renderer, so
   * collision handling stays pure and deterministic. A label sits beside a
   * straight vertical run (never on it) and at the midpoint of a diagonal;
   * labels that would land in the same 12px bucket are pushed down 11px each
   * in edge-index order — O(e), and the same spec always resolves the same
   * way. Parallel edges sharing (src, dst) bow apart laterally.
   */
  const pairCount = new Map<string, number>();
  const pairSeen = new Map<string, number>();
  for (const edge of graph.edges) {
    if (isReturn(edge)) continue;
    const key = `${edge.src}>${edge.dst}`;
    pairCount.set(key, (pairCount.get(key) ?? 0) + 1);
  }

  const buckets = new Map<string, number>();
  const at = (i: number) => ({ x: xOf(i), y: yOf[i]! });
  const edges: LaidOutEdge[] = graph.edges.map((edge) => {
    const from = at(edge.src);
    const to = at(edge.dst);
    const ret = isReturn(edge);

    let bow = 0;
    if (!ret) {
      const key = `${edge.src}>${edge.dst}`;
      const count = pairCount.get(key) ?? 1;
      if (count > 1) {
        const k = pairSeen.get(key) ?? 0;
        pairSeen.set(key, k + 1);
        bow = (k - (count - 1) / 2) * 20;
      }
    }

    const label = ret ? null : (edge.guard ?? scoredClass(edge));
    let labelX = 0;
    let labelY = 0;
    let labelAnchor: "start" | "middle" = "start";
    if (label !== null) {
      if (from.x === to.x) {
        labelX = from.x + 7 + bow;
        labelY = (from.y + to.y) / 2;
        labelAnchor = "start";
      } else {
        labelX = (from.x + to.x) / 2 + bow;
        labelY = (from.y + to.y) / 2 - 4;
        labelAnchor = "middle";
      }
      const bucket = `${Math.round(labelX / 12)}:${Math.round(labelY / 12)}`;
      const occupants = buckets.get(bucket) ?? 0;
      buckets.set(bucket, occupants + 1);
      labelY += occupants * 11;
    }

    return { edge, from, to, isReturn: ret, label, labelX, labelY, labelAnchor, bow };
  });

  return { nodes, edges, bands, width, height, laneCount, returnRailX };
}
