/**
 * Where the state machine's nodes actually land, in CSS pixels.
 *
 * Pure — no React, no DOM — for the same reason `topology.ts` is: this is where
 * a quiet mistake shows up as a drawing that looks deliberate and is wrong, so
 * it has to be testable without mounting anything. `SketchStateMachine` draws
 * what these return; it owns no geometry of its own.
 *
 * The model's columns (authored, ~6–140) map onto whatever horizontal room the
 * tile offers; its rows map onto a fixed vertical rhythm that the two bands
 * below the spine are then measured against. So width is the fluid axis — the
 * one a window resize actually changes — and height is a property of the task's
 * shape. Type and marks stay constant either way.
 */

import type { TaskGraphModel, TaskNode } from "./topology";

/*
 * Everything below is CSS pixels. The model's columns (authored, ~6–140) map
 * onto whatever horizontal room the tile offers; its rows (unit-spaced) map
 * onto a FIXED vertical rhythm. So width is the fluid axis — the one a window
 * resize actually changes — and height is a property of the task's shape, not
 * of the window. Type and marks stay constant either way.
 */

/** The width band the fluid layout serves. Below MIN_W the narrowest column
 *  gap (~18/134 of the span) no longer clears a centred chip, so Mission
 *  Control's live panel scales the MIN_W drawing down uniformly instead — a
 *  smaller correct drawing, not colliding labels. The editor has its own,
 *  higher floor and never scales (`EDITOR_MIN_W`). Above MAX_W added width is
 *  only longer edges, so the drawing centres instead. Between them, rendering
 *  is 1:1. */
export const MIN_W = 460;
export const MAX_W = 1000;
/** The task editor's floor, above `MIN_W`. The editor never draws below it and
 *  never scales: its page rearranges (`editorLayout`) so the diagram's host is
 *  always at least this wide, and on the rare host that is not, the drawing
 *  scrolls sideways rather than shrinking its type. */
export const EDITOR_MIN_W = 560;
/** Layout widths move in steps of this many pixels, so a window drag re-spaces
 *  the machine a few times rather than on every pixel — and each step glides
 *  (`useGlidingWidth`) instead of jumping. */
export const WIDTH_STEP = 40;

/**
 * The width the machine is laid out at for a host this wide: clamped to the
 * band, then snapped down to a `WIDTH_STEP` (never below the floor). Null — not
 * yet measured — is `FALLBACK_W`.
 */
export function layoutWidthFor(host: number | null, min: number = MIN_W, max: number = MAX_W): number {
  const clamped = Math.min(Math.max(host ?? FALLBACK_W, min), max);
  return Math.max(min, Math.floor(clamped / WIDTH_STEP) * WIDTH_STEP);
}
/** Pre-measurement layout width. One frame at most — the tile fades in over
 *  it, so a settle from here is never visible. */
export const FALLBACK_W = 720;

/** Node radius. */
export const R = 9;

/**
 * Where a glyph's text sits relative to its centre.
 *
 * **Shared with `measureNode` on purpose.** These offsets used to live only in
 * `NodeGlyph`'s JSX, which was fine while nothing needed to know how tall a
 * node was; now the abort band is derived from exactly that. Two copies of
 * these numbers would drift, and the drift would be invisible — the band would
 * simply settle inside a chip stack, with nothing thrown and no test failing.
 */
export const LABEL_BELOW_DY = 15;
export const LABEL_RIGHT_DY = 4;
export const LABEL_ABOVE_DY = -(R + 9);
/** Gap from a below-anchored label's baseline to the first chip's. */
export const CHIP_GAP = 12;
/** Baseline-to-baseline within the chip stack. */
export const CHIP_STEP = 12;
export const CHIP_RIGHT_DY = 17;
export const CHIP_ABOVE_DY = R + 14;
/** Descender room under the lowest baseline. */
export const TEXT_DESCENT = 3;

/**
 * The condition tick strip, drawn between the glyph and its label.
 *
 * `ACTIVE_H` is double `TICK_H` deliberately: the active tick has to be
 * readable at a glance from across the room, and the theme bans the two things
 * that usually carry that (gradients and glow). **Shape survives distance and
 * colour-vision deficits; brightness alone does not**, so the active tick is
 * taller as well as lighter.
 */
export const TICK_W = 2;
export const TICK_H = 5;
export const TICK_ACTIVE_H = 10;
export const TICK_PITCH = 5;
/** Past this many, the strip says `⋯` rather than competing with the labels of
 *  neighbouring columns — the vocabulary allows twelve odor lines. */
export const TICK_MAX = 8;
/** Vertical room the strip claims under the glyph. */
export const TICK_BLOCK = TICK_ACTIVE_H + 3;

/** Horizontal pads. The right one only shelters the ITI; the outcome column's
 *  right-anchored labels fit because the model keeps a whole column of room
 *  between it and the frame edge. */
export const PAD_L = 30;
export const PAD_R = 30;

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
export interface Geometry {
  rowPx: number;
  padT: number;
  returnDepth: number;
}

/** The sketch viewer's geometry — chips under every node. */
export const VIEWER_GEOMETRY: Geometry = { rowPx: 52, padT: 30, returnDepth: 62 };
/** The live panel's — no chips, and every vertical px competes with the
 *  charts below it in a view that must fit the window without scrolling. */
export const LIVE_GEOMETRY: Geometry = { rowPx: 34, padT: 24, returnDepth: 48 };

export interface Frame {
  width: number;
  height: number;
  x: (n: TaskNode) => number;
  y: (n: TaskNode) => number;
  /** y of the lowest node — the return arcs hang from it. */
  lowY: number;
  /** The deepest return arc's sweep below `lowY` (see `Geometry`). */
  returnDepth: number;
}

/**
 * How far a node's drawn content reaches above and below its centre, in px.
 *
 * The whole reason the band is derived. `chips` is the count the HOST will
 * draw — four in the viewer, zero in the live panel — which is why this cannot
 * live in `topology.ts`: a model-side measurement would be right for one host
 * and ~48px optimistic for the other, and the symptom would be an abort band
 * sitting inside a chip stack rather than an error.
 */
export function measureNode(node: TaskNode, chips: number): { up: number; down: number } {
  const anchor = node.labelAnchor ?? "below";
  const ticks = (node.multiplicity ?? 0) > 1 ? TICK_BLOCK : 0;
  if (anchor === "right") {
    const bottom =
      chips > 0 ? CHIP_RIGHT_DY + (chips - 1) * CHIP_STEP + TEXT_DESCENT : LABEL_RIGHT_DY;
    return { up: R, down: Math.max(R, bottom) };
  }
  if (anchor === "above") {
    const bottom =
      chips > 0 ? CHIP_ABOVE_DY + (chips - 1) * CHIP_STEP + TEXT_DESCENT : R;
    return { up: -LABEL_ABOVE_DY + 8, down: Math.max(R, bottom) };
  }
  const labelBaseline = R + ticks + LABEL_BELOW_DY;
  const bottom =
    chips > 0
      ? labelBaseline + CHIP_GAP + (chips - 1) * CHIP_STEP + TEXT_DESCENT
      : labelBaseline + TEXT_DESCENT;
  return { up: R, down: bottom };
}

/** Clearance between the deepest drawn content and the top of the abort band. */
export const BAND_GAP = 10;

/**
 * Rows, resolved.
 *
 * Three passes, and the order matters: the fan is spaced against its own
 * measured content, then the floor band is pushed below everything that is not
 * itself in the band. The old code did neither — it multiplied an authored row
 * by a constant — which is why a fan that grew walked into a band that didn't.
 *
 * > [!CAUTION]
 * > **The floor is a LOWER BOUND, never a replacement.** `Math.max` against the
 * > authored depth, so a task with fewer chips keeps the drawing it has rather
 * > than having the band creep up to meet it. Deriving in both directions would
 * > make the diagram's proportions a function of how many parameter groups a
 * > profile happens to declare, which is a change nobody asked for and would
 * > silently alter every screenshot ever taken of it.
 */
export function rowsFor(
  model: TaskGraphModel,
  geometry: Geometry,
  chipsOf: (node: TaskNode) => number,
): Map<string, number> {
  const { rowPx } = geometry;
  const out = new Map<string, number>();

  // Pass 1 — the fan (congruence fallback only), spaced by measured stack.
  // Sorted by authored row, which is the only place a lane's internal order
  // lives — see `TaskNode.lane`.
  const fan = model.nodes.filter((n) => n.lane === "fan").sort((a, b) => a.row - b.row);
  if (fan.length > 0) {
    const tallest = fan.reduce((most, node) => {
      const box = measureNode(node, chipsOf(node));
      return Math.max(most, box.up + box.down);
    }, 0);
    // The constant this replaces was 1.6, fitted to a two-arm fan with four
    // chips — which measures at ~2px of clearance. Whatever the arms actually
    // occupy, plus room to breathe, expressed back in row units.
    const gap = Math.max(1.6, (tallest + 6) / rowPx);
    fan.forEach((node, index) => {
      out.set(node.id, (index - (fan.length - 1) / 2) * gap);
    });
  }

  const rowOf = (node: TaskNode) => out.get(node.id) ?? node.row;

  // Pass 2 — everything the band must clear: the spine and the fan, never the
  // band itself.
  const above = model.nodes.filter((n) => n.lane !== "floor");
  const deepest = above.reduce((low, node) => {
    return Math.max(low, rowOf(node) * rowPx + measureNode(node, chipsOf(node)).down);
  }, Number.NEGATIVE_INFINITY);

  // Pass 3 — the band, at its authored depth or below the content, whichever
  // is lower.
  const floor = model.nodes.filter((n) => n.lane === "floor");
  if (floor.length > 0) {
    const authoredTop = Math.min(...floor.map((n) => n.row));
    const bandTopPx = Math.max(authoredTop * rowPx, deepest + BAND_GAP);
    const shift = (bandTopPx - authoredTop * rowPx) / rowPx;
    for (const node of floor) out.set(node.id, node.row + shift);
  }

  for (const node of model.nodes) {
    if (!out.has(node.id)) out.set(node.id, node.row);
  }
  return out;
}

export function frameFor(
  model: TaskGraphModel,
  width: number,
  geometry: Geometry,
  chipsOf: (node: TaskNode) => number = () => 0,
): Frame {
  const { rowPx, padT, returnDepth } = geometry;
  const cols = model.nodes.map((n) => n.column);
  const minCol = Math.min(...cols);
  const colSpan = Math.max(Math.max(...cols) - minCol, 1);

  const rows = rowsFor(model, geometry, chipsOf);
  const values = [...rows.values()];
  const minRow = Math.min(...values);
  const lowY = padT + (Math.max(...values) - minRow) * rowPx;
  const innerW = width - PAD_L - PAD_R;
  return {
    width,
    height: lowY + returnDepth + 16,
    x: (n) => PAD_L + ((n.column - minCol) / colSpan) * innerW,
    y: (n) => padT + ((rows.get(n.id) ?? n.row) - minRow) * rowPx,
    lowY,
    returnDepth,
  };
}


/**
 * One continuous SVG path through a sequence of nodes, centre to centre — the
 * transit token's track. Between nodes it follows the same lateral Bézier the
 * drawing uses for an edge (rim to rim, `dx = max(Δx/2, 20)`), so the token
 * rides ON the edges rather than beside them.
 */
export function spinePath(nodes: readonly TaskNode[], frame: Frame): string {
  const first = nodes[0];
  if (!first) return "";
  let d = `M ${frame.x(first)} ${frame.y(first)}`;
  for (let i = 1; i < nodes.length; i++) {
    const a = nodes[i - 1] as TaskNode;
    const b = nodes[i] as TaskNode;
    const x1 = frame.x(a);
    const y1 = frame.y(a);
    const x2 = frame.x(b);
    const y2 = frame.y(b);
    const dx = Math.max((x2 - x1) / 2, 20);
    d += ` L ${x1 + R} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2 - R} ${y2} L ${x2} ${y2}`;
  }
  return d;
}
