/**
 * The parameter dial — `TASKS.md#parameter-dial`. The promise under test: the
 * selected planet is at the zenith, and no planet ever leaves the drawn half of
 * the orbit, whichever stop is selected.
 */

import { describe, expect, it } from "vitest";

import { accumulateWheel, angleOf, planetAt, stopSpacing } from "./orrery";

const orbit = { cx: 180, cy: 80, rx: 150, ry: 52 };

describe("the orbit", () => {
  it("puts the selected stop at the zenith, lower indices to its left", () => {
    const at = planetAt(2, 2, 5, orbit);
    expect(at.x).toBeCloseTo(orbit.cx);
    expect(at.y).toBeCloseTo(orbit.cy - orbit.ry);
    expect(at.height).toBeCloseTo(1);
    expect(planetAt(1, 2, 5, orbit).x).toBeLessThan(at.x);
    expect(planetAt(3, 2, 5, orbit).x).toBeGreaterThan(at.x);
  });

  it("keeps every planet above the horizon for any selection", () => {
    for (let n = 1; n <= 9; n++) {
      for (let selected = 0; selected < n; selected++) {
        for (let i = 0; i < n; i++) {
          const angle = angleOf(i, selected, n);
          expect(angle).toBeGreaterThanOrEqual(0);
          expect(angle).toBeLessThanOrEqual(180);
        }
      }
    }
  });

  it("spaces a few stops generously and many stops to fit", () => {
    expect(stopSpacing(1)).toBe(0);
    expect(stopSpacing(4)).toBe(30);
    expect(stopSpacing(3)).toBe(40);
  });
});

describe("accumulateWheel", () => {
  it("turns a trackpad's many small deltas into one stop", () => {
    let pending = 0;
    let moved = 0;
    for (let i = 0; i < 6; i++) {
      const r = accumulateWheel(pending, 10);
      pending = r.pending;
      moved += r.stops;
    }
    expect(moved).toBe(1);
  });

  it("moves backwards as well as forwards", () => {
    expect(accumulateWheel(0, -120).stops).toBe(-2);
  });
});
