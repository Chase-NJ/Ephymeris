/**
 * Star placement for the 3D constellation views (`dashboard.md` §9.1,
 * `dashboard.md` §4).
 *
 * An **occupant** is whatever is standing on a star: an animal in Mission
 * Control, a box in Debug Mode. The placement maths is identical for both,
 * which is the point — box 3 is the same star in the session view, the Debug
 * browser, and the sidebar widget, because all of them resolve the one
 * `box → star` slot map from settings.
 *
 * Two placement modes, and which one is in force is a settings question:
 *
 * * **Zodiac** — when Box Setup has chosen a constellation, the scene *is* that
 *   asterism, lifted out of the 2D widget's 100×54 frame into world space.
 * * **Seeded** — the pre-zodiac fallback, kept verbatim for an install that
 *   never ran Box Setup. Each star is seeded from `(cohortId, occupantId)`
 *   **together**, extending `cohorts.md` §5's procedural generation: the 2D
 *   icon only needed a stable *count*, this needs a permanent position per
 *   occupant, so adding one later must not reshuffle anyone else's star. Only
 *   Mission Control uses it; Debug always has a layout, since the pre-zodiac
 *   `legacyLayout` pins a position per box number.
 *
 * The zodiac mode changes what a star *means* in Mission Control: it is the
 * box, not the animal. An animal's position therefore moves when it is mapped
 * to a different box, and two animals that run in box 1 on different days share
 * a star. That is the arrangement mirroring the rig rather than the roster,
 * which is what makes the shape recognizable at a glance.
 */

import type { ConstellationLayout } from "../constellations/slots";
import { seededRandom } from "../prng";

export interface Star {
  occupantId: string;
  position: [number, number, number];
  /** Seeded size variation, purely for texture. */
  radius: number;
}

/**
 * One renderable point in the sky.
 *
 * Asterism stars and free-floating occupants are the same shape deliberately:
 * links index into a single flat list, so an edge between an occupied star and
 * an empty one needs no special case.
 */
export interface SkyPoint {
  /** Index into the zodiac catalogue's star list, or null when off-asterism. */
  star: number | null;
  /** The occupant standing on this point, when one is. */
  occupantId: string | null;
  /** The box this point belongs to, when the asterism is in force. */
  box: number | null;
  position: [number, number, number];
  radius: number;
}

export interface Sky {
  points: SkyPoint[];
  /** Index pairs into `points`. */
  links: Array<[number, number]>;
}

/** Shell the seeded-fallback stars are scattered through, in world units. */
const MIN_ORBIT = 4.5;
const MAX_ORBIT = 11;

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

/**
 * Where an occupant goes when it has no star on the asterism — an animal with
 * no box mapped in this group, or one whose box Box Setup never bound.
 *
 * Outside the asterism rather than hidden: §6.2 requires every animal in the
 * cohort to be present, including "animals with no box assigned at all". Placed
 * beyond `ASTERISM_SPAN / 2` so they read as the surrounding field rather than
 * as members of the stick figure they are not part of. Debug never reaches
 * this: every bound box is slotted onto a star by `reconcileSlots`.
 */
const FIELD_MIN_ORBIT = 13;
const FIELD_MAX_ORBIT = 17;

export function placeStar(cohortId: string, occupantId: string): Star {
  const rand = seededRandom(`${cohortId}:${occupantId}`);

  // Uniform-ish direction on a sphere, then a jittered radius. Not perfectly
  // area-uniform — a slight pull toward the poles reads as a constellation
  // rather than a shell, which is the point.
  const theta = rand() * Math.PI * 2;
  const phi = Math.acos(2 * rand() - 1);
  const orbit = MIN_ORBIT + rand() * (MAX_ORBIT - MIN_ORBIT);

  return {
    occupantId,
    position: [
      Math.sin(phi) * Math.cos(theta) * orbit,
      Math.cos(phi) * orbit * 0.62, // flattened, so it reads as a sky
      Math.sin(phi) * Math.sin(theta) * orbit,
    ],
    radius: 0.16 + rand() * 0.12,
  };
}

export function placeStars(cohortId: string, ids: string[]): Star[] {
  return ids.map((id) => placeStar(cohortId, id));
}

/** What `buildSky` needs to know: who the occupant is, and which box it is on. */
export interface SkyOccupant {
  occupantId: string;
  /** The box it is mapped to *right now*, or null. */
  box: number | null;
}

/**
 * The whole scene: every point to draw and every link between them.
 *
 * Pass `layout: null` for the seeded fallback. Otherwise `layout` is the very
 * same `ConstellationLayout` the sidebar widget and Debug Mode render, so the
 * three cannot disagree about which box owns which star.
 */
export function buildSky(
  cohortId: string,
  occupants: SkyOccupant[],
  layout: ConstellationLayout | null,
  /** Constellation id — seeds the per-star depth so it is stable per asterism. */
  seed: string,
): Sky {
  if (layout === null) {
    const stars = placeStars(
      cohortId,
      occupants.map((a) => a.occupantId),
    );
    const boxOf = new Map(occupants.map((a) => [a.occupantId, a.box]));
    return {
      points: stars.map((star) => ({
        star: null,
        occupantId: star.occupantId,
        box: boxOf.get(star.occupantId) ?? null,
        position: star.position,
        radius: star.radius,
      })),
      links: linkStars(stars),
    };
  }

  const frame = frameOf([...layout.nodes, ...layout.emptyStars]);
  const occupantForBox = new Map<number, string>();
  for (const occupant of occupants) {
    if (occupant.box !== null) occupantForBox.set(occupant.box, occupant.occupantId);
  }

  const points: SkyPoint[] = [];
  const indexByStar = new Map<number, number>();
  const seated = new Set<string>();

  // Asterism first, in star order — so `indexByStar` is dense and the catalogue
  // edges below translate to point indices with a plain lookup.
  const asterism = [
    ...layout.nodes.map((n) => ({ star: n.star, x: n.x, y: n.y, box: n.box })),
    ...layout.emptyStars.map((s) => ({ star: s.star, x: s.x, y: s.y, box: null })),
  ].sort((a, b) => a.star - b.star);

  for (const entry of asterism) {
    const occupantId = entry.box === null ? null : (occupantForBox.get(entry.box) ?? null);
    if (occupantId !== null) seated.add(occupantId);
    indexByStar.set(entry.star, points.length);
    points.push({
      star: entry.star,
      occupantId,
      box: entry.box,
      position: lift(entry.x, entry.y, entry.star, frame, seed),
      // An unoccupied star is a marker, not a body — small enough to read as
      // the shape of the rig rather than as another occupant.
      radius:
        occupantId === null
          ? 0.09 + seededRandom(`${seed}:r:${entry.star}`)() * 0.04
          : 0.16 + seededRandom(`${cohortId}:${occupantId}`)() * 0.12,
    });
  }

  for (const occupant of occupants) {
    if (seated.has(occupant.occupantId)) continue;
    const star = placeStar(cohortId, occupant.occupantId);
    points.push({
      star: null,
      occupantId: occupant.occupantId,
      box: occupant.box,
      position: toField(star.position),
      radius: star.radius,
    });
  }

  // Catalogue edges verbatim — the traditional stick figure is what makes the
  // asterism recognizable, and nearest-neighbour links would draw a different
  // shape entirely. Field stars get none: they are not part of the figure.
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

/** Push a seeded position out past the asterism, keeping its direction. */
function toField(position: [number, number, number]): [number, number, number] {
  const length = Math.hypot(...position) || 1;
  const t = (length - MIN_ORBIT) / (MAX_ORBIT - MIN_ORBIT);
  const orbit = FIELD_MIN_ORBIT + t * (FIELD_MAX_ORBIT - FIELD_MIN_ORBIT);
  const k = orbit / length;
  return [position[0] * k, position[1] * k, position[2] * k];
}

/**
 * Nearest-neighbour links, deduped — the same rule the 2D icon uses (§5.4), so
 * the two read as one visual family. Used only by the seeded fallback; the
 * zodiac path draws the catalogue's own edges instead.
 *
 * Unlike positions, links legitimately change when the roster does: a link is a
 * statement about the current set, not about one occupant.
 */
export function linkStars(stars: Star[]): Array<[number, number]> {
  const seen = new Set<string>();
  const links: Array<[number, number]> = [];

  for (let i = 0; i < stars.length; i += 1) {
    let best = -1;
    let bestDistance = Infinity;
    for (let j = 0; j < stars.length; j += 1) {
      if (i === j) continue;
      const distance = squaredDistance(stars[i]!.position, stars[j]!.position);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = j;
      }
    }
    if (best < 0) continue;
    const key = i < best ? `${i}-${best}` : `${best}-${i}`;
    if (seen.has(key)) continue;
    seen.add(key);
    links.push([i, best]);
  }

  return links;
}

function squaredDistance(
  a: [number, number, number],
  b: [number, number, number],
): number {
  return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
}
