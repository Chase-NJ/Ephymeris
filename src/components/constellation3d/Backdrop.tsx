import { useReduceMotion } from "@/lib/useReduceMotion";
import { useWindowFocus } from "@/lib/useWindowFocus";

import { DriftField } from "./DriftField";
import { FarSky } from "./FarSky";
import { SkyEvents } from "./SkyEvents";

/**
 * The deep-sky backdrop behind every route: we are drifting through space
 * (`ARCHITECTURE.md#one-sky`).
 *
 * It used to be one shell of scenery turning about us as a piece, and however
 * rich the shell, a sky that turns as one reads as a globe, not a place you
 * are moving through. Travel is parallax — near things sliding past far ones
 * — so the sky is now three depths:
 *
 * - **The far sky** (`FarSky`): a baked dome of nebulae and a galactic band,
 *   the home galaxy, distant galaxies and faint fixed stars, all at infinity.
 *   It never drifts. It is the frame the motion is measured against.
 * - **Mid-field stars**, drifting slowly past.
 * - **Near motes**, faint dust drifting past at the same speed and so crossing
 *   the frame fastest, because they are nearest.
 *
 * And the things that happen — meteors, supernovae, the odd comet — on their
 * own seeded schedule (`SkyEvents`).
 *
 * Everything here is scenery, and scenery in this app obeys two rules. It is
 * **deterministic** — every position, hue, phase, event and the dome's noise
 * lattice are seeded through `mulberry32`, so the sky is the same sky on every
 * mount and every machine; only the clock is live. And it is **behind the
 * data**: the far sky is drawn at the far plane, the drifting layers fade
 * before they reach the camera's reach (`DRIFT_CLEARANCE`), and everything
 * renders with `depthWrite` off and a negative `renderOrder`, so no piece of
 * scenery ever occludes or competes with a star or a world an operator is
 * reading.
 *
 * All of it holds when the window loses focus, as the 2D `Starfield` does —
 * an event already under way plays out, but no new one starts. Under reduced
 * motion the whole backdrop holds still and no event fires — the field stays,
 * the theatre goes.
 */

/** One backdrop seed — change it and a different (equally permanent) sky. */
const SKY_SEED = 0xa57e21;

/** Where `SkyEvents` stages meteors and novae — outside the drift clearance. */
const EVENT_SHELL_NEAR = 58;
const EVENT_SHELL_FAR = 92;

/* Layer sizes as module constants: `DriftField` rebuilds its buffer when a
 * prop's identity changes, so an inline array would rebuild it every render. */
const MID_SIZES: [number, number] = [0.3, 0.7];
const NEAR_SIZES: [number, number] = [0.35, 0.7];

export function SceneBackdrop() {
  const reduceMotion = useReduceMotion();
  const focused = useWindowFocus();
  const still = reduceMotion || !focused;

  return (
    <group>
      <FarSky seed={SKY_SEED} still={still} />
      {/* Mid-field: stellar-class tints, a gentle twinkle, out to ~200. */}
      <DriftField
        seed={SKY_SEED ^ 0x3c}
        count={4000}
        size={400}
        sizeRange={MID_SIZES}
        gain={0.9}
        twinkle={0.4}
        renderOrder={-5}
        still={still}
      />
      {/* Near motes: dust, not stars — one pale tint, steady, faint. A
          smaller box keeps them dense where they are nearest. */}
      <DriftField
        seed={SKY_SEED ^ 0x2d}
        count={3200}
        size={280}
        sizeRange={NEAR_SIZES}
        gain={0.5}
        twinkle={0}
        tint="#d8d4ea"
        renderOrder={-4}
        still={still}
      />
      <SkyEvents
        seed={SKY_SEED}
        shellNear={EVENT_SHELL_NEAR}
        shellFar={EVENT_SHELL_FAR}
        paused={!focused}
      />
    </group>
  );
}
