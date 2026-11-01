import { describe, expect, it } from "vitest";
import { describeRederive } from "./rederive";
import type { RederiveResult } from "./types";

function result(overrides: Partial<RederiveResult> = {}): RederiveResult {
  return {
    scanned: 3,
    rewritten: 0,
    current: 3,
    failed: 0,
    entries: [],
    cohortId: "c1",
    dataFolder: "/data/Batch A",
    folderMissing: false,
    ...overrides,
  };
}

describe("describeRederive", () => {
  it("says every table is current when nothing was rewritten", () => {
    expect(describeRederive(result())).toBe(
      "Every trial table is current (3 spine runs).",
    );
  });

  it("counts the rewritten runs and names each failure by file", () => {
    const note = describeRederive(
      result({
        rewritten: 1,
        current: 1,
        failed: 1,
        entries: [
          { jsonPath: "/a.json", status: "rewritten", reason: null },
          { jsonPath: "/b.json", status: "failed", reason: "disk full" },
        ],
      }),
    );
    expect(note).toBe(
      "Rewrote the trial table of 1 of 3 spine runs; /b.json: disk full.",
    );
  });

  it("says when there is nothing to re-derive", () => {
    expect(describeRederive(result({ scanned: 0, current: 0 }))).toBe(
      "No spine runs in this cohort — nothing to re-derive.",
    );
  });

  it("says when the folder is unreachable", () => {
    expect(describeRederive(result({ folderMissing: true }))).toContain(
      "Can't reach /data/Batch A",
    );
  });
});
