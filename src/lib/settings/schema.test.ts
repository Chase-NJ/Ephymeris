import { describe, expect, it } from "vitest";

import { DEFAULT_BAUD, EMPTY_DISCOVERY, normalizeSettings, offeredSketches } from "./schema";

describe("normalizeSettings defaultBaud", () => {
  // The sidecar checks `settings.push` against the schema, where `defaultBaud`
  // is an int: a hand-edited 9600.5 would refuse every push, leaving every box
  // unbound with nothing on screen to say why.
  it("replaces a fractional baud with the default", () => {
    expect(normalizeSettings({ defaultBaud: 9600.5 }).defaultBaud).toBe(DEFAULT_BAUD);
  });

  it("keeps a whole, positive baud", () => {
    expect(normalizeSettings({ defaultBaud: 9600 }).defaultBaud).toBe(9600);
  });

  it("replaces a non-positive baud with the default", () => {
    expect(normalizeSettings({ defaultBaud: 0 }).defaultBaud).toBe(DEFAULT_BAUD);
  });
});

describe("offeredSketches", () => {
  it("leaves out a decode-only sketch and keeps the rest in order", () => {
    const sketch = (name: string, decodeOnly: boolean) =>
      ({ category: "Utility", name, path: `/lib/${name}`, source: "bundled", decodeOnly }) as const;
    const discovery = {
      ...EMPTY_DISCOVERY,
      sketches: [sketch("BOX_Utility", false), sketch("GRGL_Sim", true), sketch("GRGL", false)],
    };
    expect(offeredSketches(discovery).map((s) => s.name)).toEqual(["BOX_Utility", "GRGL"]);
  });
});
