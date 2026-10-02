/**
 * The zodiac catalogue — hand-authored, simplified asterisms for the
 * box-status constellation (`ARCHITECTURE.md#status-constellation`).
 *
 * Data, not code, on purpose: unlike the per-cohort icons (seeded PRNG in
 * `components/cohorts/PlanetDisc.tsx`), these must be *recognizable* — Scorpius
 * has to read as the fishhook, the Teapot as the Teapot. Coordinates are
 * authored directly in the widget's native 100×54 frame (x right, y down);
 * `frameFor()` refits the viewBox anyway, so only proportions matter.
 *
 * Star counts are honest: Aries genuinely has four usable stars and is not
 * padded to six. A rig with more boxes than a constellation has stars simply
 * can't choose that constellation — the picker says so rather than distorting
 * the asterism.
 */

export interface ZodiacStar {
  x: number;
  y: number;
}

export interface ZodiacConstellation {
  /** The persisted key in `settings.constellation`. */
  id: string;
  name: string;
  stars: ReadonlyArray<ZodiacStar>;
  /** Star-index pairs forming the traditional stick figure. */
  edges: ReadonlyArray<readonly [number, number]>;
}

/** All twelve, in ecliptic order. */
export const ZODIAC: ReadonlyArray<ZodiacConstellation> = [
  {
    id: "aries",
    name: "Aries",
    // Mesarthim–Sheratan–Hamal, then the long reach to 41 Ari.
    stars: [
      { x: 16, y: 36 },
      { x: 24, y: 25 },
      { x: 40, y: 14 },
      { x: 72, y: 9 },
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
    ],
  },
  {
    id: "taurus",
    name: "Taurus",
    // The Hyades V with Aldebaran, horns to Elnath and ζ Tau, λ at the chest.
    stars: [
      { x: 32, y: 16 }, // ε
      { x: 36, y: 23 }, // δ
      { x: 42, y: 30 }, // γ (vertex)
      { x: 48, y: 28 }, // θ
      { x: 56, y: 26 }, // α Aldebaran
      { x: 74, y: 5 }, // β Elnath
      { x: 80, y: 33 }, // ζ
      { x: 20, y: 40 }, // λ
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [4, 6],
      [0, 5],
      [2, 7],
    ],
  },
  {
    id: "gemini",
    name: "Gemini",
    // The twins: two chains from Castor and Pollux, joined at the shoulders
    // and hips, down to Propus and Alhena.
    stars: [
      { x: 38, y: 6 }, // α Castor
      { x: 52, y: 8 }, // β Pollux
      { x: 37, y: 15 }, // τ
      { x: 51, y: 17 }, // υ
      { x: 33, y: 26 }, // ε
      { x: 53, y: 27 }, // δ
      { x: 30, y: 37 }, // μ
      { x: 56, y: 37 }, // ζ
      { x: 26, y: 46 }, // η Propus
      { x: 62, y: 46 }, // γ Alhena
    ],
    edges: [
      [0, 2],
      [2, 4],
      [4, 6],
      [6, 8],
      [1, 3],
      [3, 5],
      [5, 7],
      [7, 9],
      [2, 3],
      [4, 5],
    ],
  },
  {
    id: "cancer",
    name: "Cancer",
    // The upside-down Y around δ, the Beehive's chaperone.
    stars: [
      { x: 40, y: 6 }, // ι
      { x: 46, y: 14 }, // γ
      { x: 48, y: 26 }, // δ
      { x: 68, y: 36 }, // α Acubens
      { x: 26, y: 44 }, // β Altarf
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [2, 4],
    ],
  },
  {
    id: "leo",
    name: "Leo",
    // The Sickle down to Regulus, then the haunch triangle to Denebola.
    stars: [
      { x: 16, y: 16 }, // ε
      { x: 24, y: 9 }, // μ
      { x: 33, y: 11 }, // ζ
      { x: 40, y: 19 }, // γ Algieba
      { x: 37, y: 30 }, // η
      { x: 35, y: 42 }, // α Regulus
      { x: 63, y: 25 }, // δ
      { x: 60, y: 38 }, // θ
      { x: 85, y: 31 }, // β Denebola
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [4, 5],
      [3, 6],
      [5, 7],
      [6, 7],
      [6, 8],
      [7, 8],
    ],
  },
  {
    id: "virgo",
    name: "Virgo",
    // The reclining figure, Spica hanging below the hip.
    stars: [
      { x: 10, y: 14 }, // β
      { x: 22, y: 20 }, // η
      { x: 34, y: 24 }, // γ Porrima
      { x: 40, y: 13 }, // δ
      { x: 52, y: 7 }, // ε Vindemiatrix
      { x: 45, y: 33 }, // θ
      { x: 53, y: 46 }, // α Spica
      { x: 60, y: 27 }, // ζ
      { x: 74, y: 18 }, // τ
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [2, 5],
      [5, 6],
      [6, 7],
      [7, 8],
      [3, 7],
    ],
  },
  {
    id: "libra",
    name: "Libra",
    // The scales: beam triangle with the two pans trailing south.
    stars: [
      { x: 32, y: 46 }, // σ
      { x: 22, y: 30 }, // α Zubenelgenubi
      { x: 46, y: 10 }, // β Zubeneschamali
      { x: 60, y: 22 }, // γ
      { x: 68, y: 38 }, // υ
      { x: 66, y: 46 }, // τ
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [1, 3],
      [3, 4],
      [4, 5],
    ],
  },
  {
    id: "scorpius",
    name: "Scorpius",
    // The fishhook: head fan, Antares, the long curved tail to the sting.
    stars: [
      { x: 22, y: 10 }, // δ Dschubba
      { x: 30, y: 5 }, // β
      { x: 16, y: 16 }, // π
      { x: 28, y: 21 }, // α Antares
      { x: 30, y: 29 }, // τ
      { x: 29, y: 37 }, // ε
      { x: 34, y: 44 }, // μ
      { x: 41, y: 49 }, // ζ
      { x: 51, y: 51 }, // η
      { x: 61, y: 49 }, // θ Sargas
      { x: 67, y: 44 }, // ι
      { x: 72, y: 34 }, // λ Shaula
    ],
    edges: [
      [0, 1],
      [0, 2],
      [0, 3],
      [3, 4],
      [4, 5],
      [5, 6],
      [6, 7],
      [7, 8],
      [8, 9],
      [9, 10],
      [10, 11],
    ],
  },
  {
    id: "sagittarius",
    name: "Sagittarius",
    // The Teapot: spout, lid, body, handle.
    stars: [
      { x: 20, y: 32 }, // γ (spout tip)
      { x: 32, y: 42 }, // ε
      { x: 34, y: 24 }, // δ
      { x: 44, y: 14 }, // λ (lid)
      { x: 52, y: 24 }, // φ
      { x: 62, y: 16 }, // σ Nunki
      { x: 68, y: 26 }, // τ
      { x: 60, y: 36 }, // ζ
    ],
    edges: [
      [0, 1],
      [0, 2],
      [2, 3],
      [3, 4],
      [4, 2],
      [4, 5],
      [5, 6],
      [6, 7],
      [7, 4],
      [7, 1],
    ],
  },
  {
    id: "capricornus",
    name: "Capricornus",
    // The smile: horns at both tips, the keel curving between them.
    stars: [
      { x: 12, y: 9 }, // α Algedi
      { x: 16, y: 19 }, // β Dabih
      { x: 25, y: 33 }, // ψ
      { x: 35, y: 41 }, // ω
      { x: 51, y: 42 }, // ζ
      { x: 63, y: 35 }, // ε
      { x: 71, y: 21 }, // γ
      { x: 79, y: 12 }, // δ Deneb Algedi
      { x: 45, y: 19 }, // θ
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [4, 5],
      [5, 6],
      [6, 7],
      [1, 8],
      [8, 6],
    ],
  },
  {
    id: "aquarius",
    name: "Aquarius",
    // Sadalsuud to Sadalmelik, the water-jar Y, the stream falling south.
    stars: [
      { x: 10, y: 26 }, // ε
      { x: 24, y: 18 }, // β Sadalsuud
      { x: 42, y: 14 }, // α Sadalmelik
      { x: 52, y: 10 }, // γ
      { x: 58, y: 5 }, // ζ
      { x: 66, y: 9 }, // η
      { x: 50, y: 22 }, // θ
      { x: 62, y: 28 }, // λ
      { x: 58, y: 40 }, // δ
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [4, 5],
      [3, 5],
      [2, 6],
      [6, 7],
      [7, 8],
    ],
  },
  {
    id: "pisces",
    name: "Pisces",
    // The Circlet, the cords meeting at Alrescha, the northern fish.
    stars: [
      { x: 14, y: 38 }, // circlet
      { x: 20, y: 32 },
      { x: 28, y: 34 },
      { x: 28, y: 42 },
      { x: 20, y: 44 },
      { x: 40, y: 42 }, // western cord
      { x: 55, y: 41 },
      { x: 70, y: 44 }, // α Alrescha (the knot)
      { x: 67, y: 32 }, // northern cord
      { x: 63, y: 20 },
      { x: 58, y: 9 }, // η
    ],
    edges: [
      [0, 1],
      [1, 2],
      [2, 3],
      [3, 4],
      [4, 0],
      [3, 5],
      [5, 6],
      [6, 7],
      [7, 8],
      [8, 9],
      [9, 10],
    ],
  },
];

export function zodiacById(id: string | null | undefined): ZodiacConstellation | null {
  if (!id) return null;
  return ZODIAC.find((c) => c.id === id) ?? null;
}
