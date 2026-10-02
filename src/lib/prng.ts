/**
 * Deterministic pseudo-randomness for generated visuals.
 *
 * Extracted from the starfield so a cohort's world (`ARCHITECTURE.md#cohort-browser`) seeds from
 * the same generator rather than growing a second one. Both need the same
 * property: identical output for identical input, forever — a cohort's icon is
 * its identity, so it must not drift between renders, sessions, or machines.
 */

/** mulberry32 — small, fast, dependency-free, good enough for visual jitter. */
export function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Hash a string into a 32-bit seed (FNV-1a).
 *
 * Lets a uuid seed the generator directly, so a cohort's world is derived from
 * its id itself, with nothing extra stored.
 */
export function hashString(value: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Convenience: a generator seeded straight from an id. */
export function seededRandom(id: string): () => number {
  return mulberry32(hashString(id));
}
