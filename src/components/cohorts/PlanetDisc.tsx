import { useMemo } from "react";

import {
  planetPalette,
  resolveAppearance,
  type ResolvedAppearance,
} from "@/lib/cohorts/appearance";
import { mulberry32, hashString } from "@/lib/prng";
import type { CohortAppearance } from "@/lib/ws/protocol";

/**
 * A cohort's world at icon scale — `ARCHITECTURE.md#cohort-browser`.
 *
 * It replaced `CohortIcon`, the seeded constellation, when the browser became a
 * sky of planets. The reason is continuity and nothing else: a cohort that is a
 * banded amber world in the browser and an unrelated star cluster in the
 * session picker has two identities, and neither reminds you of the other.
 * Same appearance record, same seeding contract, same five sizes.
 *
 * **Flat, and deliberately.** The 3D planet is a bounded exception to the
 * theme's no-gradients rule (`ARCHITECTURE.md#shaders-and-lights`), earned by
 * carrying readings at full size. A 32px disc carries none of them, so it gets
 * no exception: this is banded fills, a hard terminator and a hairline ring.
 * What survives the shrink is the thing the icon exists for — hue, banding and
 * silhouette, enough to recognise a world you have seen at full size.
 *
 * No canvas and no WebGL. A second GL context per list row would be absurd, and
 * this has to render in the archived list, the session picker and the analytics
 * rail — three places that draw dozens at once.
 */
export function PlanetDisc({
  cohortId,
  appearance,
  size = 56,
  className = "",
}: {
  cohortId: string;
  /** The stored record, or null/undefined to derive it from the id. */
  appearance?: CohortAppearance | null;
  size?: number;
  className?: string;
}) {
  const world = useMemo(
    () => resolveAppearance(cohortId, appearance),
    [cohortId, appearance],
  );
  const palette = useMemo(() => planetPalette(world), [world]);
  const bands = useMemo(() => bandsFor(world), [world]);

  const clip = `planet-clip-${cohortId}`;
  const night = `planet-night-${cohortId}`;

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={className}
      aria-hidden
    >
      <defs>
        {/* Every band is drawn as a full-width bar and clipped to the disc —
            far cheaper than computing chord widths, and exact. */}
        <clipPath id={clip}>
          <circle cx={50} cy={50} r={DISC} />
        </clipPath>

        {/* The terminator, as the disc MINUS a circle offset toward the light.
            What is left is a crescent hugging the far limb — which is what
            shading on a sphere looks like. The first version drew the whole
            far half instead and read as a bisected pie rather than a lit
            world. Still hard-edged: a soft gradient is the one thing this file
            is not allowed to draw (`ARCHITECTURE.md#theme`). */}
        <mask id={night} maskUnits="userSpaceOnUse">
          <circle cx={50} cy={50} r={DISC} fill="white" />
          <circle
            cx={50 - DISC * LIGHT_X}
            cy={50 - DISC * LIGHT_Y}
            r={DISC * 1.12}
            fill="black"
          />
        </mask>
      </defs>

      <circle cx={50} cy={50} r={DISC} fill={palette.edge.getStyle()} />

      <g clipPath={`url(#${clip})`}>
        {bands.map((band, i) => (
          <rect
            key={i}
            x={0}
            y={band.y}
            width={100}
            height={band.height}
            fill={(band.accent ? palette.accent : palette.core).getStyle()}
            opacity={band.opacity}
          />
        ))}

        {/* Offset up-left, the same direction `PlanetarySurface`'s `uLight`
            points, so a disc and its planet agree about where the sun is. */}
        <circle
          cx={50}
          cy={50}
          r={DISC}
          fill="var(--color-void)"
          opacity={0.5}
          mask={`url(#${night})`}
        />
      </g>

      {world.ring && (
        // An ellipse, not a circle: a ring seen edge-on is what says the disc
        // is a sphere rather than a coin.
        <ellipse
          cx={50}
          cy={50}
          rx={DISC * 1.52}
          ry={DISC * 0.42}
          fill="none"
          stroke={palette.accent.getStyle()}
          strokeWidth={2.4}
          opacity={0.55}
          transform="rotate(-18 50 50)"
        />
      )}

      {/* A hairline rim so a dark world still has an edge against the Void. */}
      <circle
        cx={50}
        cy={50}
        r={DISC}
        fill="none"
        stroke={palette.atmosphere.getStyle()}
        strokeWidth={1.6}
        opacity={0.6}
      />
    </svg>
  );
}

const DISC = 34;

/** Where the light comes from, as a fraction of the radius. Matches the
 *  direction `planetSurface.ts` lights a world from. */
const LIGHT_X = 0.42;
const LIGHT_Y = 0.32;

interface Band {
  y: number;
  height: number;
  opacity: number;
  accent: boolean;
}

/**
 * The banding, seeded from the world.
 *
 * The `rand()` call order is the contract, exactly as it was in the icon this
 * replaced: reordering these lines silently redraws every untouched cohort in
 * the lab. Add anything new at the END.
 *
 * Counts differ by type because the silhouette is what survives at 32px: a gas
 * giant is *made of* bands and needs many, a rocky world reads as a couple of
 * continents, and an ice world is nearly plain with one bright crack.
 */
function bandsFor(world: ResolvedAppearance): Band[] {
  const rand = mulberry32(hashString(`disc:${world.type}:${Math.floor(world.seed)}`));
  const count = BAND_COUNT[world.type];
  const out: Band[] = [];
  let y = 50 - DISC;
  const span = DISC * 2;
  for (let i = 0; i < count; i += 1) {
    const height = (span / count) * (0.5 + rand() * 0.9);
    out.push({
      y,
      height,
      opacity: 0.35 + rand() * 0.5,
      // One accent band at most, and only past the halfway point, so a world's
      // one bright feature is never the first thing at the top edge.
      accent: i > count / 2 && rand() < 0.28,
    });
    y += height * (0.8 + rand() * 0.5);
    if (y > 50 + DISC) break;
  }
  return out;
}

const BAND_COUNT: Record<ResolvedAppearance["type"], number> = {
  rocky: 4,
  gas: 9,
  ice: 3,
  ocean: 5,
  lava: 6,
};
