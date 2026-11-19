import { describe, expect, it } from "vitest";

import { describeRescan } from "./rescan";
import type { RescanResult } from "./types";

function result(extra: Partial<RescanResult> = {}): RescanResult {
  return {
    scanned: 12,
    adopted: 0,
    pruned: { runs: 0, adopted: 0, sessions: 0 },
    rehomed: 0,
    duplicates: 0,
    orphans: [],
    cohortId: "c",
    dataFolder: "D:/data/Batch A",
    folderMissing: false,
    ...extra,
  } as RescanResult;
}

describe("the rescan note", () => {
  it("says when there was nothing to do", () => {
    expect(describeRescan(result())).toBe(
      "Scanned 12 files — everything on disk is already indexed.",
    );
  });

  it("names an unreachable folder alone, never as an empty archive", () => {
    const note = describeRescan(result({ folderMissing: true, scanned: 0 }));
    expect(note).toContain("Can't reach D:/data/Batch A");
    expect(note).not.toContain("Scanned");
  });

  it("always states what it adopted and what it dropped", () => {
    const note = describeRescan(
      result({ adopted: 3, pruned: { runs: 1, adopted: 0, sessions: 2 }, duplicates: 1 }),
    );
    expect(note).toContain("adopted 3 that no run record pointed at");
    expect(note).toContain("skipped 1 duplicate copy");
    expect(note).toContain("dropped the records of 1 run and 2 sessions");
    expect(note.endsWith(".")).toBe(true);
  });
});
