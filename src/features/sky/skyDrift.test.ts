/**
 * The backdrop's drift. `DRIFT_CLEARANCE` guards an invariant that lives in a
 * different file with no type connecting them — `OrbitControls`' `maxDistance`
 * of 40 (`CameraRig.tsx`) — so it is pinned here, as `cohortSky.test.ts` pins
 * the worlds against the same number.
 */

import { describe, expect, it } from "vitest";

import { advanceDrift, DRIFT_CLEARANCE, DRIFT_DIR } from "./skyDrift";

/** `OrbitControls` will not let the camera further out than this. */
const MAX_DISTANCE = 40;

describe("sky drift", () => {
  it("keeps drifting stars out of the camera's reach", () => {
    // Outside the ball the camera lives in, a star can never pass between the
    // camera and a box star or a world.
    expect(DRIFT_CLEARANCE).toBeGreaterThan(MAX_DISTANCE);
  });

  it("drifts along a unit direction", () => {
    expect(Math.hypot(...DRIFT_DIR)).toBeCloseTo(1, 10);
  });

  it("wraps the offset into the box however far it has drifted", () => {
    const offset = [0, 0, 0];
    for (const distance of [0.008, 1, 359.9, 1e6, -42]) {
      advanceDrift(offset, distance, 360);
      for (const value of offset) {
        expect(value).toBeGreaterThanOrEqual(0);
        expect(value).toBeLessThan(360);
      }
    }
  });

  it("moves along the direction by the distance asked", () => {
    const offset = [10, 10, 10];
    advanceDrift(offset, 2, 1000);
    expect(offset[0]! - 10).toBeCloseTo(DRIFT_DIR[0] * 2, 10);
    expect(offset[1]! - 10).toBeCloseTo(DRIFT_DIR[1] * 2, 10);
    expect(offset[2]! - 10).toBeCloseTo(DRIFT_DIR[2] * 2, 10);
  });
});
