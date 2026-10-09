/**
 * The backdrop's drift — the numbers behind "drifting through space"
 * (`ARCHITECTURE.md#one-sky`).
 *
 * The far sky sits at infinity and never moves; two nearer layers of stars
 * slide past along one direction at one speed, so the only thing that makes a
 * near mote cross the frame faster than a mid-field star is that it is nearer.
 * That difference is the parallax, and the parallax is the whole effect.
 *
 * Pure so the invariants below can be tested without a GL context.
 */

/**
 * The direction the drifting stars move through the world — the opposite of
 * the way we are coasting. Seen from the default view (`OVERVIEW_POSITION`,
 * looking down −z) it is mostly leftward, a little upward and a little toward
 * the viewer: a sideways glide, not a flight into the frame, so the flow never
 * radiates out of the screen's centre, where the box stars sit. The 2D
 * `Starfield` drifts the same way on screen so the two skies agree.
 */
export const DRIFT_DIR: readonly [number, number, number] = normalize([-0.85, 0.18, 0.45]);

/**
 * World units per second. A mote ~60 units out moves about half a degree a
 * second and takes two to three minutes to cross the frame: noticeable when
 * you look, never in the corner of your eye during a session.
 */
export const DRIFT_SPEED = 0.5;

/**
 * Drifting stars fade out before they come this close to the origin. It must
 * stay above `OrbitControls`' `maxDistance` (40): the camera and everything it
 * looks at live inside that ball, so a star outside it can never pass between
 * the camera and a box or a world.
 */
export const DRIFT_CLEARANCE = 48;

/**
 * Advance a layer's offset by `distance` along `DRIFT_DIR`, wrapped into
 * `[0, size)` on every axis. In place, so the per-frame call allocates
 * nothing; wrapped on the CPU so the float uniform it feeds never grows and
 * loses precision over a long session.
 */
export function advanceDrift(offset: number[], distance: number, size: number): void {
  for (let i = 0; i < 3; i += 1) {
    const moved = (offset[i]! + DRIFT_DIR[i]! * distance) % size;
    offset[i] = moved < 0 ? moved + size : moved;
  }
}

function normalize(v: [number, number, number]): [number, number, number] {
  const length = Math.hypot(...v);
  return [v[0] / length, v[1] / length, v[2] / length];
}
