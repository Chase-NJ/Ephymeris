import { describe, expect, it } from "vitest";

import { activeSiteCount, normalizeActiveSiteHz, summarizeYield, type RunYield } from "./yield";

function run(id: string, counts: Record<string, number>, counted: number, total = counted, threshold: RunYield["threshold"] = null): RunYield {
  return {
    runId: id,
    sessionId: "s",
    box: 1,
    startedAt: `2026-11-0${id.slice(1)}T10:00:00Z`,
    countedSeconds: counted,
    runSeconds: total,
    threshold,
    counts,
  };
}

describe("activeSiteCount", () => {
  it("counts sites whose mean rate over the counted seconds reaches the floor, silent ones included in the total", () => {
    // 600 s: 300 crossings is 0.5 Hz (active), 299 is just under.
    expect(activeSiteCount({ "A-000": 300, "A-001": 299, "A-002": 0 }, 600, 0.5)).toEqual({ active: 1, total: 3 });
    expect(activeSiteCount({ "A-000": 5 }, 0, 0.5)).toEqual({ active: 0, total: 1 });
  });
});

describe("summarizeYield", () => {
  it("judges by the seconds the stream covered, so a gap does not read as a quiet electrode", () => {
    // 100 crossings over the 100 s the stream ran is 1 Hz, though the run lasted 600 s.
    const [s] = summarizeYield([run("r1", { "A-000": 100 }, 100, 600)], 0.5);
    expect(s).toMatchObject({ active: 1, total: 1, partial: true });
    expect(s?.coverage).toBeCloseTo(100 / 600, 9);
  });

  it("leaves out runs counted too briefly to say anything, and marks a threshold unlike the latest run's", () => {
    const summaries = summarizeYield(
      [
        run("r1", { "A-000": 600 }, 600, 600, { mode: "absolute", microvolts: -50 }),
        run("r2", { "A-000": 1 }, 5),
        run("r3", { "A-000": 0 }, 600, 600, { mode: "absolute", microvolts: -70 }),
      ],
      0.5,
    );
    expect(summaries.map((s) => [s.runId, s.active, s.thresholdDiffers])).toEqual([
      ["r1", 1, true],
      ["r3", 0, false],
    ]);
  });
});

describe("normalizeActiveSiteHz", () => {
  it("keeps a sensible rate and falls back for anything else", () => {
    expect(normalizeActiveSiteHz(1)).toBe(1);
    expect(normalizeActiveSiteHz(0)).toBe(0.5);
    expect(normalizeActiveSiteHz("2")).toBe(0.5);
  });
});
