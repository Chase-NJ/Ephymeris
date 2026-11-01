import { describe, expect, it } from "vitest";

import type { LiveReplay, MetricSummary } from "@/lib/ws/protocol";

import { replayNote, replayStrip, replayWarns, spineAccuracy } from "./liveReplay";

function metric(
  id: string,
  label: string,
  pSession: number | null,
  counted: number,
  interval: [number, number] | null = null,
): MetricSummary {
  return {
    id,
    label,
    pSession,
    pWindow: null,
    hits: 0,
    counted,
    triggered: counted,
    excluded: 0,
    windowSize: 0,
    wilsonLow: interval?.[0] ?? null,
    wilsonHigh: interval?.[1] ?? null,
    lowConfidence: true,
    answerSide: null,
  };
}

function replay(extra: Partial<LiveReplay> = {}): LiveReplay {
  return {
    box: 1,
    animalId: "a1",
    status: "replaying",
    detail: null,
    state: 3,
    phase: 2,
    row: "go",
    provisional: false,
    unavailable: null,
    trials: 0,
    current: null,
    last: null,
    metrics: [],
    overall: null,
    replay: null,
    divergence: null,
    ...extra,
  };
}

describe("a spine run's live numbers, as the sidecar sent them", () => {
  it("shows each row's P(correct) and the pooled one, labelled by the sidecar", () => {
    const strip = replayStrip(
      replay({
        metrics: [metric("replay:go:correct", "P(correct | Go)", 0.75, 4)],
        overall: metric("overall", "Overall accuracy", 0.5, 8),
      }),
    );
    expect(strip.metrics).toEqual([
      { id: "replay:go:correct", value: 0.75, n: 4 },
      { id: "overall", value: 0.5, n: 8 },
    ]);
    expect(strip.labels).toEqual({ "replay:go:correct": "P(correct | Go)", overall: "Overall accuracy" });
  });

  it("shows nothing for a diverged run, and says why", () => {
    const diverged = replay({
      status: "diverged",
      detail: "diverged at strobe 40: replay predicts FLUID_2_ON@3200, the file records FLUID_2_ON@3201",
    });
    expect(replayStrip(diverged).metrics).toEqual([]);
    expect(replayNote(diverged)).toMatch(/^Diverged — diverged at strobe 40/);
    expect(replayWarns(diverged)).toBe(true);
  });

  it("waits for a first trial rather than showing zero", () => {
    expect(replayStrip(replay()).metrics).toEqual([]);
    expect(replayNote(replay())).toMatch(/No complete trial yet/);
    expect(replayWarns(replay())).toBe(false);
    expect(replayNote(null)).toMatch(/replaying the run/);
  });

  it("carries each figure's n and its 95% interval to the strip", () => {
    const strip = replayStrip(
      replay({ metrics: [metric("replay:go:correct", "P(correct | Go)", 0.75, 4, [0.3, 0.95])] }),
    );
    expect(strip.intervals).toEqual({ "replay:go:correct": [0.3, 0.95] });
    expect(strip.metrics[0]!.n).toBe(4);
  });

  it("says why its numbers are gone when the live scorer is down, and keeps the token", () => {
    const down = replay({ unavailable: "the live scorer stopped, so live numbers are unavailable" });
    expect(replayStrip(down).metrics).toEqual([]);
    expect(replayNote(down)).toMatch(/live scorer stopped/);
    expect(replayWarns(down)).toBe(false);
  });

  it("calls a replay that failed unavailable, with no numbers", () => {
    const failed = replay({ status: "unavailable", detail: "the live replay could not take a strobe" });
    expect(replayWarns(failed)).toBe(true);
    expect(replayNote(failed)).toMatch(/could not take a strobe/);
  });
});

describe("a spine star's temperature", () => {
  it("is the run's pooled P(correct) so far, as the sidecar scored it", () => {
    expect(spineAccuracy(replay({ overall: metric("overall", "Overall accuracy", 0.8, 10) }))).toBe(0.8);
  });

  it("is nothing before a scored trial, for a run that will not be scored, or with the scorer down", () => {
    expect(spineAccuracy(null)).toBeNull();
    expect(spineAccuracy(replay())).toBeNull();
    const overall = metric("overall", "Overall accuracy", 0.8, 10);
    expect(spineAccuracy(replay({ status: "diverged", overall }))).toBeNull();
    expect(spineAccuracy(replay({ unavailable: "down", overall }))).toBeNull();
  });
});
