import * as THREE from "three";

import { hashString, mulberry32 } from "@/lib/prng";
import type { CohortAppearance } from "@/lib/ws/protocol";

export type { CohortAppearance };

/**
 * How a cohort's world looks — `ARCHITECTURE.md#cohort-browser`.
 *
 * **Derived unless the operator says otherwise.** A cohort with no stored
 * appearance gets all four fields from a hash of its `id`, which is the same
 * contract the flat constellation icon lived under and the reason this change
 * needed no data migration: every cohort that has ever existed already has a
 * stable, distinct world, and one that is never tuned stays that way forever.
 *
 * The split between what is derived and what is chosen is the whole design.
 * `resolveAppearance` is the only place the two meet, so nothing downstream —
 * the shader, the 2D disc, the editor — has to know which it is looking at.
 *
 * A seed shifts the noise field and **nothing else**: a re-roll changes the
 * world's weather, never its type, hue or size. That is what lets an operator
 * hunt for a pattern they like without losing the identity they already
 * recognise across the room.
 */

export const PLANET_TYPES = ["rocky", "gas", "ice", "ocean", "lava"] as const;
export type PlanetType = (typeof PLANET_TYPES)[number];

/** Human labels for the editor. The values are the wire's, and are not shown. */
export const PLANET_TYPE_LABEL: Record<PlanetType, string> = {
  rocky: "Rocky",
  gas: "Gas giant",
  ice: "Ice",
  ocean: "Ocean",
  lava: "Lava",
};

export interface ResolvedAppearance {
  type: PlanetType;
  /** 0–360. */
  hue: number;
  ring: boolean;
  seed: number;
}

/**
 * The appearance a cohort actually renders with.
 *
 * `stored` wins field by field where it is present, so a half-written record
 * from an older build still resolves rather than falling back wholesale.
 */
export function resolveAppearance(
  cohortId: string,
  stored: CohortAppearance | null | undefined,
): ResolvedAppearance {
  const derived = derivedAppearance(cohortId);
  if (!stored) return derived;
  const type = isPlanetType(stored.type) ? stored.type : derived.type;
  return {
    type,
    hue: Number.isFinite(stored.hue) ? mod360(stored.hue) : derived.hue,
    ring: typeof stored.ring === "boolean" ? stored.ring : derived.ring,
    seed: Number.isFinite(stored.seed) ? stored.seed : derived.seed,
  };
}

/**
 * The world a cohort has by virtue of existing.
 *
 * The `rand()` call order is the contract, exactly as it is in the icon this
 * replaced: reordering these four lines silently re-rolls every untouched
 * cohort in the lab. Add new fields at the END.
 */
export function derivedAppearance(cohortId: string): ResolvedAppearance {
  const rand = mulberry32(hashString(`planet:${cohortId}`));
  const type = PLANET_TYPES[Math.floor(rand() * PLANET_TYPES.length)] ?? "rocky";
  const hue = rand() * 360;
  // A quarter of worlds, so a ring stays a distinguishing mark. At half they
  // stop telling anything apart, which is the only job they have here.
  const ring = rand() < 0.25;
  const seed = Math.floor(rand() * 100_000);
  return { type, hue, ring, seed };
}

export function isPlanetType(value: unknown): value is PlanetType {
  return typeof value === "string" && (PLANET_TYPES as readonly string[]).includes(value);
}

/** A fresh noise field, leaving identity alone. The editor's re-roll. */
export function rerollSeed(appearance: ResolvedAppearance): ResolvedAppearance {
  return { ...appearance, seed: Math.floor(Math.random() * 100_000) };
}

function mod360(value: number): number {
  return ((value % 360) + 360) % 360;
}

// --- the palette ----------------------------------------------------------

/**
 * Six colours per world: four stops of ground, one accent, one mineral.
 *
 * Built in HSL from the operator's hue so one slider moves a whole coherent
 * palette rather than tinting a fixed texture — a tinted texture keeps the
 * original's value structure and every world ends up reading as the same world
 * in a different colour.
 *
 * **Saturation and lightness are the type's, not the hue's.** That is what
 * keeps an ice world pale and a lava world dark at every hue, so the type
 * survives being recoloured — and it is what keeps these inside the matte
 * palette's register (`ARCHITECTURE.md#theme`) instead of drifting toward the
 * saturated primaries a free-for-all HSL picker would reach.
 *
 * **Four stops of ground, not two.** The first cut had `edge` and `core` and
 * every rocky world came out one flat tan: with nothing between "low" and
 * "high" there is no lowland, no upland and no snowline, only a tint. `deep`
 * and `peak` bracket them now, and `mineral` is a second hue laid down in
 * slow patches — one colour family across a whole world is paint; two is
 * geology.
 */
export interface PlanetPalette {
  /** The lowest ground: sea floor, crust, the shadowed side of a band. */
  deep: THREE.Color;
  /** Low ground. */
  edge: THREE.Color;
  /** High ground, cloud tops. */
  core: THREE.Color;
  /** The highest ground: snowline, cloud crests. */
  peak: THREE.Color;
  /** The one thing allowed to be bright: caps, foam, cracks, a storm. */
  accent: THREE.Color;
  /** A second hue in patches, so the ground is not one colour. */
  mineral: THREE.Color;
  /** The fresnel shell. */
  atmosphere: THREE.Color;
}

type SL = [saturation: number, lightness: number];

interface TypeStyle {
  deep: SL;
  edge: SL;
  core: SL;
  peak: SL;
  accent: SL;
  mineral: SL;
  /** Hue offsets in degrees for [deep, edge, core, peak, accent, mineral]. */
  shift: [number, number, number, number, number, number];
  atmosphere: [saturation: number, lightness: number, hueShift: number];
  /** How much of the rim shell shows. */
  atmosphereStrength: number;
}

const STYLE: Record<PlanetType, TypeStyle> = {
  // Iron-dark lowlands up through ochre highlands to a pale summit; the
  // mineral is a cooler hue a third of the way round, the way basalt sits
  // against sandstone.
  rocky: {
    deep: [0.36, 0.1],
    edge: [0.4, 0.24],
    core: [0.38, 0.42],
    peak: [0.22, 0.66],
    accent: [0.08, 0.86],
    mineral: [0.3, 0.3],
    shift: [-18, -8, 6, 14, 0, 120],
    atmosphere: [0.3, 0.55, 18],
    atmosphereStrength: 0.5,
  },
  // Banded and bright; the widest spread, because the bands ARE the reading.
  gas: {
    deep: [0.5, 0.16],
    edge: [0.48, 0.3],
    core: [0.46, 0.58],
    peak: [0.4, 0.76],
    accent: [0.5, 0.82],
    mineral: [0.42, 0.44],
    shift: [-28, -16, 8, 18, 30, 40],
    atmosphere: [0.45, 0.62, 12],
    atmosphereStrength: 0.85,
  },
  // Pale and nearly desaturated: an ice world is white first and coloured
  // second, so the hue only tints the shadows.
  ice: {
    deep: [0.22, 0.34],
    edge: [0.16, 0.5],
    core: [0.1, 0.72],
    peak: [0.05, 0.88],
    accent: [0.06, 0.95],
    mineral: [0.2, 0.58],
    shift: [-12, -6, 4, 0, 0, 150],
    atmosphere: [0.25, 0.7, -10],
    atmosphereStrength: 0.7,
  },
  // Two materials: deep water against dry land. The ground stops are the
  // LAND's — the sea is a single flat colour, which is what makes a coastline
  // read as a coastline.
  ocean: {
    deep: [0.55, 0.16],
    edge: [0.5, 0.24],
    core: [0.34, 0.42],
    peak: [0.18, 0.7],
    accent: [0.14, 0.9],
    mineral: [0.36, 0.34],
    shift: [-6, 0, 150, 156, 150, 96],
    atmosphere: [0.5, 0.6, 6],
    atmosphereStrength: 0.8,
  },
  // Dark crust, hot cracks. The only world whose accent is genuinely emissive,
  // and the reason the shader has an emissive term at all.
  lava: {
    deep: [0.3, 0.04],
    edge: [0.34, 0.09],
    core: [0.38, 0.18],
    peak: [0.32, 0.3],
    accent: [0.92, 0.56],
    mineral: [0.4, 0.14],
    shift: [-10, -6, 8, 14, 22, -40],
    atmosphere: [0.6, 0.45, 14],
    atmosphereStrength: 0.6,
  },
};

export function planetPalette(appearance: ResolvedAppearance): PlanetPalette {
  const style = STYLE[appearance.type];
  const h = (offset: number) => ((((appearance.hue + offset) % 360) + 360) % 360) / 360;
  const c = (sl: SL, offset: number) => new THREE.Color().setHSL(h(offset), sl[0], sl[1]);
  return {
    deep: c(style.deep, style.shift[0]),
    edge: c(style.edge, style.shift[1]),
    core: c(style.core, style.shift[2]),
    peak: c(style.peak, style.shift[3]),
    accent: c(style.accent, style.shift[4]),
    mineral: c(style.mineral, style.shift[5]),
    atmosphere: new THREE.Color().setHSL(
      h(style.atmosphere[2]),
      style.atmosphere[0],
      style.atmosphere[1],
    ),
  };
}

export function atmosphereStrength(appearance: ResolvedAppearance): number {
  return STYLE[appearance.type].atmosphereStrength;
}

/** The shader's `uType` — an index, because GLSL has no strings. */
export function typeIndex(type: PlanetType): number {
  return Math.max(0, PLANET_TYPES.indexOf(type));
}

// --- the readings a planet carries (`ARCHITECTURE.md#shaders-and-lights`) ---

/**
 * Roster size → world size.
 *
 * **Bounded hard, and the ceiling is lower than it looks like it should be.**
 * The radius is not just how big the sphere is: `Scene.tsx` derives the hit
 * sphere (×4), the hover reticle (×2.1), the arrival rings (×2.6–4.8), the
 * orbit reach (×2.6+) and — the one that bit — the **nameplate drop** (×3.5)
 * from it. At the range this first had (0.42–0.92) a big world's plate hung
 * more than three units below it, which is far enough in a field this size to
 * land under a *different* planet and label it. The span in `cohortSky.ts` is
 * sized against these numbers; the two have to move together.
 */
export function radiusFor(animalCount: number): number {
  const t = Math.min(1, animalCount / 24);
  return 0.3 + t * 0.32;
}

/**
 * How long ago the cohort was touched → how alive the world looks.
 *
 * 1 for something edited today, easing to a floor over a fortnight. It drives
 * spin rate and day-side brightness together, so "nobody has been here" reads
 * as one impression rather than two competing ones. The floor is not zero: a
 * dormant cohort is still a place, and a frozen black sphere reads as a bug.
 */
export function livelinessFor(updatedAt: string | null | undefined): number {
  if (!updatedAt) return LIVELINESS_FLOOR;
  const then = Date.parse(updatedAt);
  if (Number.isNaN(then)) return LIVELINESS_FLOOR;
  const days = (Date.now() - then) / 86_400_000;
  const t = 1 - Math.min(1, Math.max(0, days / 14));
  return LIVELINESS_FLOOR + (1 - LIVELINESS_FLOOR) * t;
}

const LIVELINESS_FLOOR = 0.3;
