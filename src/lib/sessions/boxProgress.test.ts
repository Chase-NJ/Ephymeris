import { describe, expect, it } from "vitest";

import type { LiveReplay, TelemetryMetric } from "@/lib/ws/protocol";

import {
  PROGRESS_LIMIT,
  accuracy,
  appendProgress,
  outcomeMix,
  pacePerMinute,
  progressLines,
  replayTally,
  telemetryTally,
  type Tally,
} from "./boxProgress";

function metric(id: string, triggered: number, counted: number, hits: number): TelemetryMetric {
  return { id, value: counted > 0 ? hits / counted : null, n: counted, triggered, counted, hits };
}

const tally = (offered: number, completed: number, correct: number): Tally => ({
  offered,
  completed,
  correct,
});

describe("telemetryTally", () => {
  it("sums a legacy run's conditions", () => {
    expect(telemetryTally([metric("odor1", 10, 8, 6), metric("odor3", 9, 9, 4)])).toEqual(tally(19, 17, 10));
  });

  it("is null for a run with no live metrics", () => {
    expect(telemetryTally([])).toBeNull();
  });
});

describe("replayTally", () => {
  const replay = (over: Partial<LiveReplay>): LiveReplay =>
    ({ unavailable: null, overall: { triggered: 12, counted: 10, hits: 7 }, ...over }) as LiveReplay;

  it("reads a spine run's pooled figure, never the sum of its rows", () => {
    expect(replayTally(replay({}))).toEqual(tally(12, 10, 7));
  });

  it("is null when the replay has no numbers", () => {
    expect(replayTally(null)).toBeNull();
    expect(replayTally(replay({ overall: null }))).toBeNull();
    expect(replayTally(replay({ unavailable: "the live scorer is down" }))).toBeNull();
  });
});

describe("appendProgress", () => {
  it("adds totals that moved", () => {
    expect(appendProgress([tally(1, 1, 1)], tally(2, 1, 1))).toEqual([tally(1, 1, 1), tally(2, 1, 1)]);
  });

  it("returns the same series for totals that repeat the last", () => {
    const series = [tally(1, 1, 1)];
    expect(appendProgress(series, tally(1, 1, 1))).toBe(series);
  });

  it("starts over when the totals went backwards: a new run", () => {
    expect(appendProgress([tally(40, 30, 20)], tally(1, 0, 0))).toEqual([tally(1, 0, 0)]);
  });

  it("thins a long session evenly, keeping its first point and its newest", () => {
    let series: readonly Tally[] = [];
    for (let i = 1; i <= PROGRESS_LIMIT + 1; i += 1) series = appendProgress(series, tally(i, i, i));
    expect(series.length).toBeLessThanOrEqual(PROGRESS_LIMIT);
    expect(series[0]).toEqual(tally(1, 1, 1));
    expect(series[series.length - 1]).toEqual(tally(PROGRESS_LIMIT + 1, PROGRESS_LIMIT + 1, PROGRESS_LIMIT + 1));
  });
});

describe("progressLines", () => {
  it("draws completed and correct against trials offered, from the origin, on one scale", () => {
    const lines = progressLines([tally(2, 2, 1), tally(4, 3, 2)]);
    expect(lines.completed).toEqual([
      { x: 0, y: 0 },
      { x: 0.5, y: 0.5 },
      { x: 1, y: 0.75 },
    ]);
    expect(lines.correct[lines.correct.length - 1]).toEqual({ x: 1, y: 0.5 });
  });

  it("is empty before a trial is offered", () => {
    expect(progressLines([])).toEqual({ completed: [], correct: [] });
    expect(progressLines([tally(0, 0, 0)])).toEqual({ completed: [], correct: [] });
  });
});

describe("outcomeMix", () => {
  it("divides the trials offered three ways", () => {
    expect(outcomeMix(tally(20, 15, 11))).toEqual({ correct: 11, wrong: 4, unanswered: 5 });
  });
});

describe("accuracy and pace", () => {
  it("is P(correct) among completed trials, null before one", () => {
    expect(accuracy(tally(20, 16, 12))).toBe(0.75);
    expect(accuracy(tally(3, 0, 0))).toBeNull();
  });

  it("is completed trials per minute, held back in the opening seconds", () => {
    expect(pacePerMinute(tally(40, 30, 20), 600)).toBe(3);
    expect(pacePerMinute(tally(2, 1, 1), 10)).toBeNull();
    expect(pacePerMinute(tally(2, 1, 1), null)).toBeNull();
  });
});
