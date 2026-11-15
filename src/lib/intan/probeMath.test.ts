import { describe, expect, it } from "vitest";

import { channelRange, fitProbeMap } from "./probeMath";
import type { ProbePage } from "./types";

describe("fitProbeMap", () => {
  // A shank as Intan draws it: tip at the SMALLEST y.
  const page: ProbePage = {
    name: "shank",
    background: "Black",
    lines: [],
    texts: [],
    ports: [
      {
        port: "A",
        sites: [
          { channel: "A-000", x: 0, y: 0, shape: "ellipse", width: 10, height: 10, outline: "White" },
          { channel: "A-001", x: 0, y: 700, shape: "ellipse", width: 10, height: 10, outline: "White" },
        ],
      },
    ],
  };

  it("draws the tip at the BOTTOM — Intan's y is up, a canvas's is down", () => {
    const fit = fitProbeMap(page, 200, 400, 20);
    expect(fit.toY(0)).toBeGreaterThan(fit.toY(700));
    expect(fit.toY(0)).toBeLessThanOrEqual(400 - 20);
    expect(fit.toY(700)).toBeGreaterThanOrEqual(20);
  });

  it("uses one scale for both axes, so a round site stays round", () => {
    const fit = fitProbeMap(page, 800, 400, 20);
    const dx = fit.toX(10) - fit.toX(0);
    const dy = fit.toY(0) - fit.toY(10);
    expect(dx).toBeCloseTo(dy, 9);
    expect(dx).toBeCloseTo(fit.scale * 10, 9);
  });

  it("centres a map narrower than its box", () => {
    const fit = fitProbeMap(page, 800, 400, 20);
    expect(fit.toX(0)).toBeCloseTo(400, 6);
  });
});

describe("channelRange", () => {
  it("names channels the way RHX does", () => {
    expect(channelRange("a", 14, 16)).toEqual(["A-014", "A-015", "A-016"]);
  });
});
