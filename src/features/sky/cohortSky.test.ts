/**
 * The cohort browser's placement.
 *
 * Two of these guard invariants that live in a *different* file and have no
 * type connecting them: `OrbitControls`' `maxDistance` of 40 and the drifting
 * backdrop's clearance (`CameraRig.tsx`, `skyDrift.ts`). Nothing stops a future span
 * change from pushing worlds past the point the camera can dolly to, and the
 * symptom would be a planet you can see and never reach.
 */

import { describe, expect, it } from "vitest";

import { planetSlots } from "./cohortSky";
import { DRIFT_CLEARANCE } from "./skyDrift";

/** `OrbitControls` will not let the camera further out than this. */
const MAX_DISTANCE = 40;
/** The nearest the deep-sky backdrop comes to the origin. */
const BACKDROP_NEAR = DRIFT_CLEARANCE;

function reach(position: [number, number, number]): number {
  return Math.hypot(...position);
}

describe("planet slots", () => {
  it("gives every cohort a slot", () => {
    for (const count of [1, 2, 6, 12, 40]) {
      expect(planetSlots(count)).toHaveLength(count);
    }
  });

  it("lays out the same library the same way every time", () => {
    // The sky is not re-rolled while you walk away and come back.
    expect(planetSlots(9)).toEqual(planetSlots(9));
  });

  it("keeps every world inside the camera's reach", () => {
    for (const count of [1, 3, 12, 40, 200]) {
      for (const slot of planetSlots(count)) {
        // Comfortably inside, not merely inside: the camera has to be able to
        // pull BACK from the outermost world, not just touch it.
        expect(reach(slot.position)).toBeLessThan(MAX_DISTANCE / 2);
        expect(reach(slot.position)).toBeLessThan(BACKDROP_NEAR);
      }
    }
  });

  it("never puts a world at the origin", () => {
    // The overview target is the origin, so a world there sits under every
    // arrival and cannot be looked at from outside.
    for (const count of [1, 2, 8]) {
      for (const slot of planetSlots(count)) {
        expect(reach(slot.position)).toBeGreaterThan(0.5);
      }
    }
  });

  it("spreads a bigger library further, but sub-linearly", () => {
    const three = outermost(planetSlots(3));
    const twelve = outermost(planetSlots(12));
    const forty = outermost(planetSlots(40));

    // Fixed, three worlds are lost in an empty sky and forty overlap.
    expect(twelve).toBeGreaterThan(three);
    expect(forty).toBeGreaterThan(twelve);
    // Linear, forty would be so far apart that the overview shows four.
    expect(forty).toBeLessThan(three * (40 / 3));
  });

  it("keeps neighbours apart at every size", () => {
    // The golden angle's whole job. A layout that stacked two worlds would put
    // one inside the other's 4×-radius hit sphere and make it unclickable.
    for (const count of [2, 5, 12, 30]) {
      const slots = planetSlots(count);
      for (let i = 0; i < slots.length; i += 1) {
        for (let j = i + 1; j < slots.length; j += 1) {
          const a = slots[i]!.position;
          const b = slots[j]!.position;
          const gap = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
          expect(gap).toBeGreaterThan(0.8);
        }
      }
    }
  });

  it("survives a count of zero rather than dividing by it", () => {
    expect(planetSlots(0)).toEqual([]);
  });
});

function outermost(slots: ReturnType<typeof planetSlots>): number {
  return Math.max(...slots.map((s) => reach(s.position)));
}
