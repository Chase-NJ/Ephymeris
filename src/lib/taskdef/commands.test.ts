/**
 * Naming a duplicated task — `tasks.md` §10.
 *
 * Two saved tasks sharing a name share a sketch folder, so saving one would
 * overwrite the other's firmware. The sidecar refuses that; this is what keeps
 * the Duplicate button from walking straight into the refusal.
 */

import { describe, expect, it } from "vitest";

import { uniqueCopyName } from "./commands";

const NAME_RE = /^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,47}$/;

describe("uniqueCopyName", () => {
  it("appends 'copy', then numbers it clear of what exists", () => {
    expect(uniqueCopyName("GRGL", ["GRGL"])).toBe("GRGL copy");
    expect(uniqueCopyName("GRGL", ["GRGL", "GRGL copy"])).toBe("GRGL copy 2");
    expect(uniqueCopyName("GRGL", ["GRGL", "grgl COPY", "GRGL copy 2"])).toBe("GRGL copy 3");
  });

  it("cuts the source name, never the suffix, and stays a valid sketch name", () => {
    const long = "A".repeat(48);
    const copy = uniqueCopyName(long, [long]);
    expect(copy.endsWith(" copy")).toBe(true);
    expect(copy.length).toBeLessThanOrEqual(48);
    expect(copy).toMatch(NAME_RE);
  });

  it("does not leave a trailing space where the cut fell", () => {
    const name = `${"B".repeat(42)} tail`;
    expect(uniqueCopyName(name, [name])).not.toMatch(/ {2}/);
  });
});
