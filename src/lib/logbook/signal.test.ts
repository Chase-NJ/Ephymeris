import { describe, expect, it } from "vitest";

import {
  UNIT_MIN_HZ,
  UNIT_SNR,
  gradeOf,
  judgeRun,
  sessionTotals,
  sessionVerdicts,
  spikesAbove,
  unitTrend,
} from "./signal";
import type { RunSignal, SiteSignal } from "./types";

const EDGES = [4, 5, 6, 7, 8, 10, 12, 16, 24];
const SECONDS = 1000;

/** A site whose spikes all fall in the bin starting at `snr`, at `hz`. */
function site(channel: string, snr: number, hz: number, extra: Partial<SiteSignal> = {}): SiteSignal {
  const counts = EDGES.map((edge) => (edge === snr ? Math.round(hz * SECONDS) : 0));
  const spikes = Math.round(hz * SECONDS);
  return {
    channel,
    crossings: spikes,
    spikes,
    artifacts: 0,
    noiseUv: 10,
    snrCounts: counts,
    ...extra,
  };
}

function run(sites: SiteSignal[], extra: Partial<RunSignal> = {}): RunSignal {
  return {
    runId: "r1",
    sessionId: "s1",
    animalId: "a1",
    box: 1,
    startedAt: "2026-11-19T14:00:00Z",
    countedSeconds: SECONDS,
    runSeconds: SECONDS,
    threshold: null,
    recordedSeconds: SECONDS,
    snrEdges: EDGES,
    sites,
    ...extra,
  };
}

describe("a site's histogram", () => {
  it("counts the bins wholly at or above the bar", () => {
    const counts = [100, 50, 20, 10, 5, 2, 1, 0, 0];
    expect(spikesAbove(counts, EDGES, 6)).toBe(38);
    // A bar between two edges takes the next edge up, never part of a bin.
    expect(spikesAbove(counts, EDGES, 6.5)).toBe(18);
    expect(spikesAbove(counts, EDGES, 100)).toBe(0);
  });
});

describe("judging a run", () => {
  it("tells unit-like from merely active from quiet", () => {
    const verdict = judgeRun(
      run([
        site("A-000", 8, 2), // large spikes, often
        site("A-001", 4, 5), // busy, but all of it at the noise's edge
        site("A-002", 8, UNIT_MIN_HZ / 5), // large, but too few to be a neuron firing
        site("A-003", 4, 0.1), // nothing much
      ]),
    )!;
    expect(verdict.basis).toBe("waveforms");
    expect(verdict.sites.map((s) => s.cls)).toEqual(["unit", "active", "quiet", "quiet"]);
    expect([verdict.unitLike, verdict.active, verdict.quiet, verdict.total]).toEqual([1, 1, 2, 4]);
    expect(verdict.grade).toBe("worth-sorting");
  });

  it("does not let artifacts make a site active", () => {
    const noisy = site("A-000", 4, 5, { artifacts: 4900 });
    expect(judgeRun(run([noisy]))!.sites[0]!.cls).toBe("quiet");
  });

  it("falls back to live crossings, ungraded, when no waveforms were measured", () => {
    const bare = (channel: string, crossings: number): SiteSignal => ({
      channel,
      crossings,
      spikes: null,
      artifacts: null,
      noiseUv: null,
      snrCounts: null,
    });
    const verdict = judgeRun(
      run([bare("A-000", 2000), bare("A-001", 100)], { recordedSeconds: null }),
    )!;
    expect(verdict.basis).toBe("crossings");
    expect(verdict.sites.map((s) => s.cls)).toEqual(["active", "quiet"]);
    expect(verdict.unitLike).toBe(0);
    expect(verdict.grade).toBeNull();
    expect(verdict.partial).toBe(false);
  });

  it("marks a live count that covered only part of the run", () => {
    const bare: SiteSignal = {
      channel: "A-000",
      crossings: 600,
      spikes: null,
      artifacts: null,
      noiseUv: null,
      snrCounts: null,
    };
    const verdict = judgeRun(run([bare], { recordedSeconds: null, countedSeconds: 500 }))!;
    expect(verdict.partial).toBe(true);
    expect(verdict.sites[0]!.cls).toBe("active");
  });

  it("says nothing about a run measured for a few seconds", () => {
    expect(judgeRun(run([site("A-000", 8, 2)], { recordedSeconds: 4, countedSeconds: 4 }))).toBeNull();
  });

  it("uses the bar the page prints", () => {
    expect(EDGES).toContain(UNIT_SNR);
  });
});

describe("grades", () => {
  it("go by the share of sites that are unit-like", () => {
    expect(gradeOf(0, 16)).toBe("none");
    expect(gradeOf(2, 16)).toBe("low-yield");
    expect(gradeOf(4, 16)).toBe("worth-sorting");
    expect(gradeOf(8, 16)).toBe("sort-first");
    expect(gradeOf(0, 0)).toBe("none");
  });
});

describe("a session's verdicts", () => {
  it("lets the longest measurement speak for a restarted animal", () => {
    const short = run([site("A-000", 4, 0.1)], { runId: "early", recordedSeconds: 60, countedSeconds: 60, runSeconds: 60 });
    const long = run([site("A-000", 8, 2)], { runId: "real" });
    const verdicts = sessionVerdicts([short, long]);
    expect(verdicts.get("a1")!.runId).toBe("real");
    expect(sessionTotals(verdicts.values())).toEqual({ unitLike: 1, total: 1, graded: true });
  });

  it("trends an animal's unit-like sites in session order", () => {
    const order = new Map([
      ["s1", 1],
      ["s2", 2],
      ["s3", 3],
    ]);
    const runs = [
      run([site("A-000", 8, 2), site("A-001", 8, 2)], { runId: "c", sessionId: "s3" }),
      run([site("A-000", 8, 2), site("A-001", 4, 1)], { runId: "a", sessionId: "s1" }),
      run([site("A-000", 4, 1)], { runId: "b", sessionId: "s2", recordedSeconds: null }),
      run([site("A-000", 8, 2)], { runId: "x", sessionId: "s2", animalId: "other" }),
    ];
    // s2 was judged on crossings alone, so it has no unit-like count to trend.
    expect(unitTrend(runs, "a1", order)).toEqual([
      { sessionId: "s1", unitLike: 1, total: 2 },
      { sessionId: "s3", unitLike: 2, total: 2 },
    ]);
  });
});
