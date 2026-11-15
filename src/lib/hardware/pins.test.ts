import { describe, expect, it } from "vitest";

import { isReserved, lowestFreePin } from "./pins";
import type { RigDocument } from "./types";

const SERIAL = [
  { pin: 0, name: "RX0" },
  { pin: 1, name: "TX0" },
];

function doc(pins: number[], range = { min: 0, max: 53 }): RigDocument {
  return {
    rig_version: 1,
    pin_range: range,
    channels: {},
    pins: Object.fromEntries(pins.map((p, i) => [`c${i}`, { index: p }])),
  };
}

describe("lowestFreePin", () => {
  it("skips the serial pins on a rig that has never used them", () => {
    expect(lowestFreePin(doc([]), SERIAL)).toBe(2);
    expect(lowestFreePin(doc([2, 3, 5]), SERIAL)).toBe(4);
  });

  it("is null when every offered pin is taken", () => {
    expect(lowestFreePin(doc([2, 3], { min: 0, max: 3 }), SERIAL)).toBeNull();
  });

  it("reads the pin range from the document", () => {
    expect(lowestFreePin(doc([], { min: 10, max: 20 }), SERIAL)).toBe(10);
  });
});

describe("isReserved", () => {
  it("names the reserved pins and nothing else", () => {
    expect(isReserved(0, SERIAL)).toBe(true);
    expect(isReserved(1, SERIAL)).toBe(true);
    expect(isReserved(2, SERIAL)).toBe(false);
  });
});
