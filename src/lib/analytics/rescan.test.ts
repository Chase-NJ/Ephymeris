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
    logs: {
      files: 0,
      unreadable: 0,
      sessions: 0,
      notes: 0,
      logs: 0,
      weighIns: 0,
      unknownAnimals: [],
    },
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

  it("says what the folders' log files brought in, and what they could not", () => {
    const logs = {
      files: 3,
      unreadable: 1,
      sessions: 2,
      notes: 5,
      logs: 1,
      weighIns: 0,
      unknownAnimals: ["HM07"],
    };
    const note = describeRescan(result({ adopted: 6, logs }));
    expect(note).toContain(
      "read in 2 sessions another machine ran, 5 notes and who ran and summed up 1 session from the session folders' log files",
    );
    expect(note).toContain("HM07 is named in those files and not in this cohort");
    expect(note).toContain("1 log file couldn't be read and was left as it is");
  });

  it("says nothing about log files that brought nothing", () => {
    const logs = { ...result().logs, files: 12 };
    expect(describeRescan(result({ logs }))).toBe(
      "Scanned 12 files — everything on disk is already indexed.",
    );
  });
});
