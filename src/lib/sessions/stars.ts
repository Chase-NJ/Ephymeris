/**
 * Seeded star placement for the 3D constellation (`starting-a-session.md` §6.1).
 *
 * Extends `cohorts.md` §5's procedural generation rather than replacing it —
 * same PRNG, one real change: each star is seeded from `(cohortId, animalId)`
 * **together**. The 2D icon only needed a stable *count*; this needs a specific,
 * permanent position per animal, so adding an animal later must not reshuffle
 * anyone else's star. Seeding per animal is what guarantees that: a star's
 * position is a pure function of its own two ids and nothing else.
 */

import { seededRandom } from "../prng";

export interface Star {
  animalId: string;
  position: [number, number, number];
  /** Seeded size variation, purely for texture. */
  radius: number;
}

/** Shell the stars are scattered through, in world units. */
const MIN_ORBIT = 4.5;
const MAX_ORBIT = 11;

export function placeStar(cohortId: string, animalId: string): Star {
  const rand = seededRandom(`${cohortId}:${animalId}`);

  // Uniform-ish direction on a sphere, then a jittered radius. Not perfectly
  // area-uniform — a slight pull toward the poles reads as a constellation
  // rather than a shell, which is the point.
  const theta = rand() * Math.PI * 2;
  const phi = Math.acos(2 * rand() - 1);
  const orbit = MIN_ORBIT + rand() * (MAX_ORBIT - MIN_ORBIT);

  return {
    animalId,
    position: [
      Math.sin(phi) * Math.cos(theta) * orbit,
      Math.cos(phi) * orbit * 0.62, // flattened, so it reads as a sky
      Math.sin(phi) * Math.sin(theta) * orbit,
    ],
    radius: 0.16 + rand() * 0.12,
  };
}

export function placeStars(cohortId: string, animalIds: string[]): Star[] {
  return animalIds.map((id) => placeStar(cohortId, id));
}

/**
 * Nearest-neighbour links, deduped — the same rule the 2D icon uses (§5.4), so
 * the two read as one visual family.
 *
 * Unlike positions, links legitimately change when the roster does: a link is a
 * statement about the current set, not about one animal.
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
