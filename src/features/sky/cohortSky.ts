import { mulberry32, hashString } from "@/lib/prng";

/**
 * Where each cohort's world sits — the cohort browser's placement.
 *
 * The counterpart of `useRigSky`/`buildSky`, which places *boxes* and cannot be
 * reused: a rig has exactly six slots in a declared asterism, and a lab has
 * however many cohorts it has.
 *
 * **A phyllotaxis, not a grid.** Successive slots step by the golden angle, the
 * arrangement seeds pack themselves into on a sunflower head — which is the
 * cheapest known way to fill a disc evenly with no two neighbours at the same
 * spacing. A grid would read as a spreadsheet with lighting, and a ring stops
 * working past about eight.
 *
 * Three properties this has to have, each learned from a way the naive version
 * fails:
 *
 * 1. **A slot belongs to a cohort, not to a position in the filtered list.**
 *    Search dims rather than removes precisely so a world stays where you
 *    learned it was; if placement keyed on the visible index instead, every
 *    keystroke would reshuffle the sky.
 * 2. **Everything stays well inside `OrbitControls`' `maxDistance` of 40** and
 *    far inside the backdrop shell at 58–92, or the camera can dolly out past
 *    the field and then through the stars behind it.
 * 3. **The span grows with the count, sub-linearly.** Fixed, three worlds are
 *    lost in an empty sky and twenty overlap. Linear, twenty are so far apart
 *    that the overview shows four of them.
 */

export interface PlanetPlacement {
  position: [number, number, number];
}

/** The golden angle. Successive slots differ by it, so no two rings line up. */
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/**
 * World units from the centre to the outermost slot at a typical count.
 *
 * Kept well inside half of `maxDistance` so the whole field frames at the
 * overview and the camera can still pull back from it — and no tighter than
 * this, because `Scene.tsx` hangs a nameplate 3.5 radii BELOW each world. Pack
 * the slots closer than that drop and a big world labels its neighbour.
 */
const BASE_SPAN = 6.0;
const MAX_SPAN = 15;

/** How far a world may sit off the plane. Small: depth here is parallax and
 *  overlap relief, not a third axis to navigate. */
const DEPTH_SPREAD = 1.5;

/**
 * Lay out `count` slots. Index 0 is the innermost.
 *
 * Deterministic given the count, so the same library lays out the same way on
 * every mount and on every machine — the sky is not re-rolled when you walk
 * away and come back.
 */
export function planetSlots(count: number): PlanetPlacement[] {
  const span = Math.min(MAX_SPAN, BASE_SPAN * Math.sqrt(Math.max(1, count) / 3));
  return Array.from({ length: count }, (_, i) => {
    // `+0.5` keeps slot 0 off the exact centre: a world at the origin is where
    // the camera's overview target is, so it sits under every arrival.
    const t = Math.sqrt((i + 0.5) / Math.max(1, count));
    const angle = i * GOLDEN_ANGLE;
    const reach = span * t;
    // Depth is seeded from the SLOT, not the cohort — it is a property of the
    // arrangement, so re-sorting rearranges depth along with everything else
    // rather than dragging each world's old z into its new place.
    const rand = mulberry32(hashString(`slot:${i}`));
    return {
      position: [
        Math.cos(angle) * reach,
        Math.sin(angle) * reach * 0.72, // flattened: the frame is wider than tall
        (rand() - 0.5) * 2 * DEPTH_SPREAD,
      ] as [number, number, number],
    };
  });
}
