import { describe, expect, it } from "vitest";

/**
 * A `motion.circle` that animates its radius names where the radius starts.
 * Without an `initial`, framer-motion takes `r` out of the rendered attributes
 * and writes `r="undefined"` on the first frame, which the browser reports as
 * an error once per circle. A static `r={…}` beside the `animate` does not
 * prevent it.
 */

const SOURCES = import.meta.glob("/src/**/*.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const TAG = /<motion\.circle\b[\s\S]*?\/>/g;
const ANIMATES_RADIUS = /\banimate=\{[\s\S]*?\br:/;
const NAMES_A_START = /\binitial=/;

describe("animated circles", () => {
  it("sees the source tree (or this test is checking nothing)", () => {
    const tags = Object.values(SOURCES).flatMap((text) => text.match(TAG) ?? []);
    expect(tags.some((tag) => ANIMATES_RADIUS.test(tag))).toBe(true);
  });

  it("give every animated radius an initial", () => {
    const offenders = Object.entries(SOURCES).flatMap(([file, text]) =>
      (text.match(TAG) ?? [])
        .filter((tag) => ANIMATES_RADIUS.test(tag) && !NAMES_A_START.test(tag))
        .map(() => file),
    );
    expect(offenders, `add initial={false} or an initial r:\n  ${offenders.join("\n  ")}`).toEqual([]);
  });
});
