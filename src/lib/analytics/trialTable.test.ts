import { describe, expect, it } from "vitest";

import type { ReplayTrial, TrialTable, WindowRate } from "@/lib/ws/protocol";

import { classParts, clockOf, outcomeFill, outcomeLabel, rateRows, trialRows } from "./trialTable";

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

describe("a spine run's phase-window rates", () => {
  const estimate = (n: number, mean: number | null, low: number | null, high: number | null) => ({ n, mean, low, high });
  const window = (over: Partial<WindowRate>): WindowRate => ({
    rowId: "cs_plus",
    name: "CS+",
    phase: 0,
    label: "delay",
    channel: "lick_spout",
    rate: estimate(30, 2, 1.5, 2.5),
    reference: null,
    versus: null,
    lowConfidence: false,
    ...over,
  });

  it("words each rate and its difference against the baseline, as the sidecar reported them", () => {
    const [baseline, cs, empty] = rateRows([
      window({}),
      window({ phase: 1, label: "present", rate: estimate(30, 12.04, 10.5, 13.6), reference: 0,
               versus: estimate(30, 10.04, 8.25, 11.8) }),
      window({ rowId: "cs_minus", name: "CS−", phase: 1, label: "present", rate: estimate(0, null, null, null),
               reference: 0, versus: estimate(0, null, null, null), lowConfidence: true }),
    ]);
    expect(baseline).toMatchObject({ row: "CS+", window: "1 delay", channel: "lick_spout",
                                     rate: "2.0/s [1.5, 2.5]", versus: "baseline", n: 30 });
    expect(cs).toMatchObject({ window: "2 present", rate: "12.0/s [10.5, 13.6]", versus: "+10.0/s [8.3, 11.8] vs 1" });
    expect(empty).toMatchObject({ row: "CS−", rate: "—", versus: "—", n: 0, lowConfidence: true });
  });

  it("gives a single trial's rate no interval", () => {
    const [one] = rateRows([window({ rate: estimate(1, 3, null, null) })]);
    expect(one?.rate).toBe("3.0/s");
  });
});
