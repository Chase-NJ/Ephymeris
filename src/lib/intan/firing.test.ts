import { describe, expect, it } from "vitest";

import {
  FLASH_TAU_MS,
  FiringModel,
  RATE_CEIL_HZ,
  RATE_FLOOR_HZ,
  RATE_MAX_STRENGTH,
  quantile,
  rateStrength,
} from "./firing";

describe("FiringModel", () => {
  it("lights a site fully the moment it spikes, and fades it within a few hundred ms", () => {
    const m = new FiringModel(["A-000", "A-001"]);
    m.add({ "A-000": 1 }, 1000);
    expect(m.strength(0)).toBe(1);
    expect(m.strength(1)).toBe(0);
    m.advance(1000 + FLASH_TAU_MS);
    expect(m.strength(0)).toBeCloseTo(Math.exp(-1), 2);
    m.advance(1000 + 5 * FLASH_TAU_MS);
    expect(m.strength(0)).toBeLessThan(0.01);
  });

  it("settles on a steady unit's true rate", () => {
    const m = new FiringModel(["A-000"]);
    // 20 Hz, as 30 fps batches would carry it: one spike every 50 ms.
    for (let t = 0; t <= 20_000; t += 50) m.add({ "A-000": 1 }, t);
    expect(m.rateHz(0)).toBeGreaterThan(19);
    expect(m.rateHz(0)).toBeLessThan(21.5);
  });

  it("ignores channels that are not on its map", () => {
    const m = new FiringModel(["A-000"]);
    m.add({ "B-007": 5 }, 0);
    expect(m.strength(0)).toBe(0);
  });

  it("shades one site the same whatever the others do", () => {
    const quiet = new FiringModel(["A-000", "A-001"]);
    const loud = new FiringModel(["A-000", "A-001"]);
    for (let t = 0; t <= 10_000; t += 100) {
      quiet.add({ "A-000": 1 }, t);
      loud.add({ "A-000": 1, "A-001": 20 }, t);
    }
    quiet.advance(10_400);
    loud.advance(10_400);
    expect(loud.strength(0)).toBeCloseTo(quiet.strength(0), 6);
  });
});

describe("rateStrength", () => {
  it("is a fixed log scale from the floor to the ceiling", () => {
    expect(rateStrength(0)).toBe(0);
    expect(rateStrength(RATE_FLOOR_HZ)).toBe(0);
    expect(rateStrength(RATE_CEIL_HZ)).toBeCloseTo(1, 9);
    expect(rateStrength(10 * RATE_CEIL_HZ)).toBe(1);
    expect(rateStrength(Math.sqrt(RATE_FLOOR_HZ * RATE_CEIL_HZ))).toBeCloseTo(0.5, 9);
  });

  it("keeps the steady glow below a spike's flash", () => {
    const m = new FiringModel(["A-000"]);
    for (let t = 0; t <= 10_000; t += 5) m.add({ "A-000": 1 }, t); // 200 Hz
    m.advance(10_000 + 10 * FLASH_TAU_MS);
    expect(m.strength(0)).toBeLessThanOrEqual(RATE_MAX_STRENGTH);
  });
});

describe("quantile", () => {
  it("picks from the sorted sample, and has nothing to say about none", () => {
    expect(quantile([], 0.95)).toBeNull();
    expect(quantile([30, 10, 20], 0.5)).toBe(20);
    expect(quantile([1, 2, 3, 4, 5, 6, 7, 8, 9, 100], 0.95)).toBe(100);
  });
});
