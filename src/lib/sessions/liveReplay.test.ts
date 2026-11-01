import { describe, expect, it } from "vitest";

import type { LiveReplay, MetricSummary } from "@/lib/ws/protocol";

import { replayNote, replayStrip, replayWarns } from "./liveReplay";

function metric(id: string, label: string, pSession: number | null, counted: number): MetricSummary {
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
    wilsonLow: null,
    wilsonHigh: null,
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
});
