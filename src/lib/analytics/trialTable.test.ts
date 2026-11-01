import { describe, expect, it } from "vitest";

import type { ReplayTrial, TrialTable } from "@/lib/ws/protocol";

import { classParts, clockOf, outcomeFill, outcomeLabel, trialRows } from "./trialTable";

const trial = (over: Partial<ReplayTrial>): ReplayTrial => ({
  index: 0,
  atMs: 0,
  block: "b1",
  row: "r1",
  rowName: "Odor 1",
  level: null,
  phaseEntries: [],
  response: null,
  responseEdge: null,
  responseMs: null,
  latencyMs: null,
  outcome: null,
  outcomeMs: null,
  correct: null,
  rewarded: false,
  rewardLine: null,
  rewardMs: null,
  correction: false,
  inputCounts: [],
  complete: true,
  presented: true,
  scores: [],
  ...over,
});

describe("a spine run's trial table", () => {
  it("words a class and gives one never seen before a neutral colour", () => {
    expect(outcomeLabel("wrong_response")).toBe("wrong response");
    expect(outcomeLabel(null)).toBe("no outcome");
    expect(outcomeFill("outcome_42")).toBe(outcomeFill(null));
    expect(outcomeFill("correct")).not.toBe(outcomeFill(null));
  });

  it("splits trials by class, the unclassified last, summing to the trials", () => {
    const tally = (outcomeClass: string, n: number) => ({ outcomeClass, n, of: 5, p: n / 5, low: null, high: null });
    const parts = classParts([tally("correct", 3), tally("omission", 0), tally("outcome_42", 1)], 1);
    expect(parts.map((p) => p.label)).toEqual(["correct", "outcome 42", "no outcome"]);
    expect(parts.reduce((sum, p) => sum + p.n, 0)).toBe(5);
  });

  it("shows each trial as the sidecar reported it", () => {
    const table: TrialTable = {
      kind: "replay",
      phases: ["wait", "present", "iti"],
      gaps: [],
      trials: [
        trial({ index: 0, atMs: 61_000, phaseEntries: [61_000, 61_200, null], outcome: "correct",
                rewarded: true, rewardLine: "fluid_2", rewardMs: 100, response: "left_well", latencyMs: 350 }),
        trial({ index: 1, atMs: 65_000, complete: false }),
      ],
    };
    const [first, second] = trialRows(table);
    expect(first).toMatchObject({ number: 1, at: "1:01", row: "Odor 1", outcome: "correct",
                                  reward: "fluid_2 100 ms", response: "left_well +350 ms",
                                  phases: ["+0", "+200", "—"] });
    expect(second).toMatchObject({ outcome: "no outcome", reward: "—", response: "—", complete: false });
    expect(clockOf(5_999)).toBe("0:05");
  });
});
