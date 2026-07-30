/**
 * Slot logic — which box sits on which star (settings.md §5).
 *
 * Pure functions, no React. `reconcileSlots` is the single authority for slot
 * hygiene; everything that mutates boxes or switches constellations funnels
 * through it, and `layoutFor` runs it defensively so a stale persisted map can
 * never render a node off the chart.
 *
 * Semantics: **slots follow boxes.** Deleting a box frees its star; a new box
 * takes the lowest free star; switching constellations keeps star indices that
 * still exist and reassigns the rest. Keys are strings because the map rides
 * JSON on the wire — every caller must `String(box)`.
 */

import type { ZodiacConstellation } from "./zodiac";

export interface ConstellationNode {
  box: number;
  star: number;
  x: number;
  y: number;
}

export interface ConstellationLayout {
  nodes: ConstellationNode[];
  /** Star-index pairs, verbatim from the catalogue. */
  edges: ReadonlyArray<readonly [number, number]>;
  emptyStars: Array<{ star: number; x: number; y: number }>;
}

/**
 * Bring a persisted `box → star` map into agreement with reality.
 *
 * Keeps an entry iff the box is configured, the star exists in this
 * constellation, and no lower-numbered box already claimed the star
 * (first-wins). Every remaining box then takes the lowest-index free star,
 * ascending — deterministic, and a fixed point under re-runs.
 */
export function reconcileSlots(
  constellation: ZodiacConstellation,
  slots: Record<string, number>,
  boxes: number[],
): Record<string, number> {
  const ordered = [...boxes].sort((a, b) => a - b);
  const next: Record<string, number> = {};
  const taken = new Set<number>();

  for (const box of ordered) {
    const star = slots[String(box)];
    if (
      typeof star === "number" &&
      Number.isInteger(star) &&
      star >= 0 &&
      star < constellation.stars.length &&
      !taken.has(star)
    ) {
      next[String(box)] = star;
      taken.add(star);
    }
  }

  for (const box of ordered) {
    if (String(box) in next) continue;
    const free = constellation.stars.findIndex((_, index) => !taken.has(index));
    if (free === -1) break; // more boxes than stars — the picker prevents this
    next[String(box)] = free;
    taken.add(free);
  }

  return next;
}

/** The renderable layout for one constellation + slot assignment. */
export function layoutFor(
  constellation: ZodiacConstellation,
  slots: Record<string, number>,
  boxes: number[],
): ConstellationLayout {
  const clean = reconcileSlots(constellation, slots, boxes);
  const occupied = new Set(Object.values(clean));

  const nodes = Object.entries(clean)
    .map(([box, star]) => ({
      box: Number(box),
      star,
      x: constellation.stars[star]!.x,
      y: constellation.stars[star]!.y,
    }))
    .sort((a, b) => a.box - b.box);

  const emptyStars = constellation.stars
    .map((s, star) => ({ star, x: s.x, y: s.y }))
    .filter((s) => !occupied.has(s.star));

  return { nodes, edges: constellation.edges, emptyStars };
}

/** Reassign one box to a specific star, swapping with any current occupant. */
export function assignStar(
  slots: Record<string, number>,
  box: number,
  star: number,
): Record<string, number> {
  const next = { ...slots };
  const from = next[String(box)];
  const occupant = Object.keys(next).find((b) => next[b] === star && b !== String(box));
  if (occupant !== undefined && typeof from === "number") {
    next[occupant] = from;
  } else if (occupant !== undefined) {
    delete next[occupant];
  }
  next[String(box)] = star;
  return next;
}
