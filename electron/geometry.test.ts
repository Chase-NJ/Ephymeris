import { describe, expect, it } from "vitest";

import { MIN_HEIGHT, MIN_WIDTH, openingSize } from "./geometry.js";

describe("openingSize", () => {
  it("opens at 4/5 of a large display", () => {
    expect(openingSize(1920, 1080)).toEqual({ width: 1536, height: 864 });
  });

  it("never opens below the minimum on a small display", () => {
    expect(openingSize(1280, 720)).toEqual({ width: MIN_WIDTH, height: MIN_HEIGHT });
  });

  it("clamps each side on its own", () => {
    expect(openingSize(2560, 800)).toEqual({ width: 2048, height: MIN_HEIGHT });
  });

  it("hands Electron whole pixels", () => {
    const { width, height } = openingSize(1366, 911);
    expect(Number.isInteger(width) && Number.isInteger(height)).toBe(true);
  });
});
