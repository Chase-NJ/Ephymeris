import { describe, expect, it } from "vitest";

import {
  barHeights,
  binRects,
  channelRange,
  cropSnippet,
  fitProbeMap,
  niceCeiling,
  rateStrength,
  voltageToY,
  yToVoltage,
} from "./scopeMath";
import type { ProbePage } from "./types";

describe("cropSnippet", () => {
  // The sidecar cuts 2 ms before and 4 ms after at 30 kS/s: 60 + 1 + 120.
  const cut = Array.from({ length: 181 }, (_, i) => i - 60);

  it("puts the crossing a third of the way across, as RHX does", () => {
    const { values, zeroIndex } = cropSnippet(cut, 30000, 2, 6);
    expect(values).toHaveLength(181);
    expect(values[zeroIndex]).toBe(0);
    expect(zeroIndex).toBe(60);
  });

  it("crops symmetrically around the crossing for a shorter time scale", () => {
    const { values, zeroIndex } = cropSnippet(cut, 30000, 2, 2);
    expect(zeroIndex).toBe(20); // 2/3 ms before
    expect(values).toHaveLength(20 + 1 + 40);
    expect(values[zeroIndex]).toBe(0); // still the crossing, not a neighbour
    expect(values[0]).toBe(-20);
  });

  it("never reads outside the snippet it was given", () => {
    const short = cut.slice(0, 100);
    const { values, zeroIndex } = cropSnippet(short, 30000, 2, 6);
    expect(values[zeroIndex]).toBe(0);
    expect(values.every((v) => v !== undefined)).toBe(true);
  });
});

describe("voltage axis", () => {
  it("is RHX's: the scale is the FULL height, zero in the middle, positive up", () => {
    expect(voltageToY(0, 500, 200)).toBe(100);
    expect(voltageToY(250, 500, 200)).toBe(0);
    expect(voltageToY(-250, 500, 200)).toBe(200);
  });

  it("round-trips a dragged threshold to a whole microvolt", () => {
    for (const uv of [-70, -250, 0, 118]) {
      expect(yToVoltage(voltageToY(uv, 500, 300), 500, 300)).toBe(uv);
    }
  });
});

describe("barHeights", () => {
  it("scales to the largest bin and keeps an empty bin at exactly zero", () => {
    expect(barHeights([0, 5, 10])).toEqual([0, 0.5, 1]);
    expect(barHeights([0, 0])).toEqual([0, 0]);
  });

  it("keeps a single interval visible beside a thousand on the log axis", () => {
    const [empty, one, many] = barHeights([0, 1, 1000], true);
    expect(empty).toBe(0);
    expect(one).toBeGreaterThan(0.09);
    expect(many).toBe(1);
  });
});

describe("niceCeiling", () => {
  it("rounds up to 1, 2 or 5 times a power of ten", () => {
    expect([0, 0.7, 1, 3, 12, 50, 51, 870].map(niceCeiling)).toEqual([1, 1, 1, 5, 20, 50, 100, 1000]);
  });
});

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

describe("rateStrength", () => {
  it("is zero for a silent site and one for the busiest", () => {
    expect(rateStrength(0, 40)).toBe(0);
    expect(rateStrength(40, 40)).toBe(1);
    expect(rateStrength(10, 40)).toBeCloseTo(0.5, 9); // sqrt: a quarter reads as half
    expect(rateStrength(5, 0)).toBe(0);
  });
});

describe("channelRange", () => {
  it("names channels the way RHX does", () => {
    expect(channelRange("a", 14, 16)).toEqual(["A-014", "A-015", "A-016"]);
  });
});

describe("binRects", () => {
  it("places bins by time and clips a partial last bin to its true width", () => {
    // 50 ms at 20 ms bins over 500 px: 200, 200, then 100 px for 40–50 ms.
    const rects = binRects(3, 20, 50, 500);
    expect(rects.map((r) => r.x)).toEqual([0, 200, 400]);
    expect(rects.map((r) => r.w)).toEqual([199, 199, 99]);
  });

  it("never draws a bar under a pixel wide, and nothing for no bins", () => {
    expect(binRects(1000, 1, 1000, 100).every((r) => r.w >= 1)).toBe(true);
    expect(binRects(0, 5, 100, 300)).toEqual([]);
    expect(binRects(4, 5, 0, 300)).toEqual([]);
  });
});
