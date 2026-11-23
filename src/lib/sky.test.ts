import { describe, expect, it } from "vitest";

/**
 * The sky behind a route is never put at `opacity: 0`
 * (`ARCHITECTURE.md#one-sky`). A canvas at zero opacity drops out of
 * compositing, while its render loop keeps drawing, and the next route that
 * shows it again pays in one blocking task on the way in: leaving the Log,
 * which zeroed its sky once the desk covered it, froze the app for 0.2 to 0.5 s
 * on every exit. A route that wants a plain background covers the sky with an
 * opaque layer of its own.
 */

const SOURCES = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const TAG = /<SkyBackdrop\b[\s\S]*?\/>/g;
const OPACITY = /\bopacity=\{([^}]*)\}/;
/** A literal zero as the whole value or as one branch of a conditional. */
const CAN_BE_ZERO = /(?:^|[?:(,|&]\s*)0(?:\.0*)?\s*(?=$|[:?),])/;

const opacities = Object.entries(SOURCES).flatMap(([file, text]) =>
  (text.match(TAG) ?? []).flatMap((tag) => {
    const value = OPACITY.exec(tag)?.[1]?.trim();
    return value === undefined ? [] : [{ file, value }];
  }),
);

describe("the sky's opacity", () => {
  it("sees the source tree (or this test is checking nothing)", () => {
    expect(opacities.length).toBeGreaterThan(0);
    expect(CAN_BE_ZERO.test("covered ? 0 : DENSE_SKY_OPACITY")).toBe(true);
    expect(CAN_BE_ZERO.test("0")).toBe(true);
    expect(CAN_BE_ZERO.test("0.35")).toBe(false);
  });

  it("is never zero: cover the sky instead", () => {
    const offenders = opacities
      .filter(({ value }) => CAN_BE_ZERO.test(value))
      .map(({ file, value }) => `${file}: opacity={${value}}`);
    expect(offenders, `cover it with an opaque layer:\n  ${offenders.join("\n  ")}`).toEqual([]);
  });
});
