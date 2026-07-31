/**
 * Star placement for the 3D constellation views (`dashboard.md` §9.1,
 * `dashboard.md` §4).
 *
 * **A star is a box. That is the whole model, and there is exactly one of it.**
 * The scene is the rig's asterism, lifted out of the 2D widget's 100×54 frame
 * into world space — the same `box → star` slot map the sidebar widget, Debug
 * Mode and Mission Control all resolve from settings, so box 3 is the same star
 * wherever you look at it. An install that never chose a constellation gets
 * `legacyLayout`, which pins a position per box number; there is no un-slotted
 * case to fall back to.
 *
 * An **occupant** is whatever is standing on that box's star — an animal in
 * Mission Control, the box itself in Debug. The occupant colours and sizes and
 * names the star; it never *places* it. So an animal's position moves when it is
 * mapped to a different box, and two animals that ran in box 1 on different days
 * share a star. That is the arrangement mirroring the rig rather than the
 * roster, which is what makes the shape recognizable at a glance.
 *
 * > [!CAUTION]
 * > **There used to be a second placement mode**, seeded per
 * > `(cohortId, occupantId)`, which Mission Control used whenever no
 * > constellation had been chosen, plus a "field" ring outside the asterism for
 * > occupants with no box. Both are gone, and neither should come back: they
 * > made Mission Control a *different sky* from the Dashboard and Debug, holding
 * > different stars at different coordinates under a different camera-memory
 * > key. Navigating between them could then only cut, and animals with no box in
 * > the running group left stray stars in the field with nothing to explain
 * > them. A rig cannot run more animals than it has boxes, so the roster never
 * > needed places the rig does not have.
 *
 * The consequence to know: **an occupant whose box is null gets no star.** It is
 * not hidden or drawn faintly, it is simply not in the sky — because the sky is
 * the rig, and it is not on the rig.
 */

import type { ConstellationLayout } from "../constellations/slots";
import { seededRandom } from "../prng";

/** One renderable point in the sky — always a star of the asterism. */
export interface SkyPoint {
  /** Index into the catalogue's star list. */
  star: number;
  /** The occupant standing on this star, when one is. */
  occupantId: string | null;
  /** The box this star is slotted to, when it is slotted to one. */
  box: number | null;
  position: [number, number, number];
  radius: number;
}

export interface Sky {
  points: SkyPoint[];
  /** Index pairs into `points`. */
  links: Array<[number, number]>;
}

/**
 * World-space extent of the asterism's longest axis. Scaled **uniformly** — a
 * per-axis fit would stretch Scorpius's tail and turn the Teapot into a bowl,
 * and recognizability is the entire reason the zodiac coordinates are
 * hand-authored rather than generated.
 *
 * Sized to fit inside the overview camera's frame with margin: at
 * `OVERVIEW_POSITION` (18.4 units out, 45° fov) the visible half-height is
 * ~7.6, so a half-span of 6.5 leaves the whole figure comfortably on screen.
 * The figure has to be legible *without* the operator moving the camera — a
 * constellation you must orbit to recognize isn't mirroring anything.
 */
const ASTERISM_SPAN = 13;

/**
 * How far a star may sit in front of or behind the asterism plane.
 *
 * Not zero: a perfectly flat plane reads as a poster the moment the camera
 * orbits off-axis. Not large either — past roughly this, near stars occlude far
 * ones and the stick figure stops being readable from the overview, which
 * defeats the point. Seeded per `(constellation, star)`, so the depth is a
 * property of the constellation and never reshuffles between renders.
 */
const DEPTH_SPREAD = 1.4;

/** What `buildSky` needs to know: who the occupant is, and which box it is on.
 *  An occupant with no box has no star — see the module note. */
export interface SkyOccupant {
  occupantId: string;
  /** The box it is mapped to *right now*, or null. */
  box: number | null;
}

/**
 * The whole scene: every point to draw and every link between them.
 *
 * `layout` is the very same `ConstellationLayout` the sidebar widget, Debug Mode
 * and Mission Control render, so none of them can disagree about which box owns
 * which star. Build it through `useRigSky` rather than calling this directly —
 * the layout *and* the seed have to match across views, and a hook that resolves
 * both is the only way that stays true without anyone remembering to keep it so.
 */
export function buildSky(
  occupants: SkyOccupant[],
  layout: ConstellationLayout,
  /** Constellation id — seeds per-star depth and size, so both are properties
   *  of the asterism and identical in every view of it. */
  seed: string,
): Sky {
  const frame = frameOf([...layout.nodes, ...layout.emptyStars]);
  const occupantForBox = new Map<number, string>();
  for (const occupant of occupants) {
    if (occupant.box !== null) occupantForBox.set(occupant.box, occupant.occupantId);
  }

  const points: SkyPoint[] = [];
  const indexByStar = new Map<number, number>();

  // In star order — so `indexByStar` is dense and the catalogue edges below
  // translate to point indices with a plain lookup.
  const asterism = [
    ...layout.nodes.map((n) => ({ star: n.star, x: n.x, y: n.y, box: n.box })),
    ...layout.emptyStars.map((s) => ({ star: s.star, x: s.x, y: s.y, box: null })),
  ].sort((a, b) => a.star - b.star);

  for (const entry of asterism) {
    const occupantId = entry.box === null ? null : (occupantForBox.get(entry.box) ?? null);
    indexByStar.set(entry.star, points.length);
    points.push({
      star: entry.star,
      occupantId,
      box: entry.box,
      position: lift(entry.x, entry.y, entry.star, frame, seed),
      /*
       * An unoccupied star is a marker, not a body — small enough to read as the
       * shape of the rig rather than as another occupant.
       *
       * **Both sizes seed on the star, never on the occupant.** Size is texture,
       * and texture belongs to the slot: seeded per occupant, box 3 was one size
       * with an animal standing on it in Mission Control and another size as
       * itself in Debug, so the same star changed size under the camera on every
       * navigation between the two.
       */
      radius:
        occupantId === null
          ? 0.09 + seededRandom(`${seed}:r:${entry.star}`)() * 0.04
          : 0.16 + seededRandom(`${seed}:body:${entry.star}`)() * 0.12,
    });
  }

  // Catalogue edges verbatim — the traditional stick figure is what makes the
  // asterism recognizable, and nearest-neighbour links would draw a different
  // shape entirely.
  const links: Array<[number, number]> = [];
  for (const [a, b] of layout.edges) {
    const from = indexByStar.get(a);
    const to = indexByStar.get(b);
    if (from === undefined || to === undefined) continue;
    links.push([from, to]);
  }

  return { points, links };
}

interface Frame {
  cx: number;
  cy: number;
  scale: number;
}

function frameOf(points: ReadonlyArray<{ x: number; y: number }>): Frame {
  if (points.length === 0) return { cx: 50, cy: 27, scale: ASTERISM_SPAN / 100 };
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return {
    cx: (minX + maxX) / 2,
    cy: (minY + maxY) / 2,
    // One scale for both axes — see ASTERISM_SPAN.
    scale: ASTERISM_SPAN / Math.max(maxX - minX, maxY - minY, 1),
  };
}

/**
 * Catalogue coordinates → world space.
 *
 * The catalogue's y runs **down** (it is authored for an SVG frame) and world
 * y runs up, so the sign flips; without it every asterism renders upside down.
 */
function lift(
  x: number,
  y: number,
  star: number,
  frame: Frame,
  seed: string,
): [number, number, number] {
  const rand = seededRandom(`${seed}:z:${star}`);
  return [
    (x - frame.cx) * frame.scale,
    -(y - frame.cy) * frame.scale,
    (rand() * 2 - 1) * DEPTH_SPREAD,
  ];
}

