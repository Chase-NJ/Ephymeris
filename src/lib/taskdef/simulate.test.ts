import { describe, expect, it } from "vitest";

import type { TaskSimulation } from "@/lib/ws/protocol";

import { DEFAULT_FORM, absentLabels, endedLabel, responsesOf, simulateArgs, switchLabels, verdict } from "./simulate";
import type { SpineDefinition } from "./spine";

const def = {
  id: "t",
  name: "T",
  category: "Tasks",
  slots: [],
  spine: [
    { phase: "wait", on: "port" },
    { phase: "response", responses: ["left", "right"] },
    { phase: "response", responses: ["right", "centre"] },
  ],
  rows: [],
  blocks: [],
  params: {},
} as unknown as SpineDefinition;

const sim = (over: Partial<TaskSimulation>): TaskSimulation =>
  ({ seed: 1, limitMs: 3_600_000, endedBy: "blocks", switches: [], absent: [], ...over }) as TaskSimulation;

describe("simulateArgs", () => {
  it("sends the default form as an always-correct animal with a fresh seed", () => {
    expect(simulateArgs(def, DEFAULT_FORM)).toEqual({ args: { animal: { kind: "correct" }, limitMs: 3_600_000 } });
  });

  it("sends a typed seed, and refuses one outside the trial seed's range", () => {
    expect(simulateArgs(def, { ...DEFAULT_FORM, seed: "42" })).toMatchObject({ args: { seed: 42 } });
    expect(simulateArgs(def, { ...DEFAULT_FORM, seed: "0" })).toHaveProperty("error");
    expect(simulateArgs(def, { ...DEFAULT_FORM, seed: "1.5" })).toHaveProperty("error");
  });

  it("refuses a time limit that is not a positive number of minutes", () => {
    expect(simulateArgs(def, { ...DEFAULT_FORM, limitMin: "0" })).toHaveProperty("error");
    expect(simulateArgs(def, { ...DEFAULT_FORM, limitMin: "x" })).toHaveProperty("error");
    expect(simulateArgs(def, { ...DEFAULT_FORM, limitMin: "1.5" })).toMatchObject({ args: { limitMs: 90_000 } });
  });

  it("sends a biased animal's response and its percent as permille", () => {
    const form = { ...DEFAULT_FORM, kind: "biased" as const, response: "right", percent: "90" };
    expect(simulateArgs(def, form)).toMatchObject({
      args: { animal: { kind: "biased", response: "right", permille: 900 } },
    });
    expect(simulateArgs(def, { ...form, response: "" })).toHaveProperty("error");
    expect(simulateArgs(def, { ...form, percent: "120" })).toHaveProperty("error");
  });
});

describe("the labels", () => {
  it("lists every response slot once, in spine order", () => {
    expect(responsesOf(def)).toEqual(["left", "right", "centre"]);
  });

  it("numbers a block switch from trial 1", () => {
    expect(switchLabels(sim({ switches: [{ index: 0, block: "a" }, { index: 8, block: "b" }] }))).toEqual([
      "a from trial 1",
      "b from trial 9",
    ]);
  });

  it("says whether an absent row is in no block or never drawn", () => {
    const absent = [
      { rowId: "no_go", name: "No-go", blocks: [] },
      { rowId: "catch", name: "", blocks: ["b1"] },
    ];
    expect(absentLabels(sim({ absent }))).toEqual(["No-go: in no block", "catch: never drawn in b1"]);
  });

  it("says what ended the session", () => {
    expect(endedLabel(sim({ endedBy: "timeLimit", limitMs: 90_000 }))).toBe("ended at its 1.5 min time limit");
    expect(endedLabel(sim({ endedBy: "blocks" }))).toBe("ended when the blocks ran out");
  });
});

describe("the verdict in words", () => {
  const tally = (outcomeClass: string, n: number) => ({ outcomeClass, n, of: 200, p: n / 200, low: null, high: null });
  const run = (over: Partial<TaskSimulation>) =>
    sim({
      overall: { id: "o", label: "o", pSession: 1, pWindow: null, hits: 200, counted: 200, triggered: 200, excluded: 0, windowSize: 20, wilsonLow: null, wilsonHigh: null } as never,
      replay: {
        trials: 200,
        classes: [tally("correct", 200)],
        rows: [
          { rowId: "row_1", name: "Odor 1", trials: 98, unclassified: 0, classes: [tally("correct", 98)] },
          { rowId: "row_2", name: "Odor 2", trials: 102, unclassified: 0, classes: [tally("correct", 102)] },
        ],
      } as never,
      trialTable: { kind: "replay", phases: [], gaps: [], trials: [{ index: 199, atMs: 23 * 60_000 } as never] },
      ...over,
    });

  it("says a perfect run as every one right, by trial type", () => {
    expect(verdict(run({}), "Always correct")).toEqual([
      "Always correct: 200 trials in about 23 min, every one right (98 Odor 1, 102 Odor 2).",
      "Every trial type was presented.",
      "Ended when the blocks ran out.",
    ]);
  });

  it("says a mixed run as the share right, the outcome mix and each trial type's count", () => {
    const mixed = run({
      overall: { hits: 71, counted: 200 } as never,
      replay: {
        trials: 200,
        classes: [tally("correct", 71), tally("wrong_response", 70), tally("omission", 59)],
        rows: [
          { rowId: "row_1", name: "Odor 1", trials: 98, unclassified: 0, classes: [tally("correct", 36), tally("wrong_response", 35), tally("omission", 27)] },
          { rowId: "row_2", name: "Odor 2", trials: 102, unclassified: 0, classes: [tally("correct", 35), tally("wrong_response", 35), tally("omission", 32)] },
        ],
      } as never,
      absent: [{ rowId: "row_3", name: "Odor 3", blocks: [] }],
      endedBy: "trials",
    });
    expect(verdict(mixed, "Random")).toEqual([
      "Random: 200 trials in about 23 min: 71 right of 200 counted (36 %) · 71 correct, 70 wrong response, 59 omission.",
      "By trial type: Odor 1 36 of 98, Odor 2 35 of 102.",
      "Never presented: Odor 3: in no block.",
      "Ended at the session's trial cap.",
    ]);
  });

  it("says when nothing ran", () => {
    expect(verdict(run({ replay: null, overall: null, trialTable: { kind: "replay", phases: [], gaps: [], trials: [] } }), "Never responds")[0]).toBe(
      "Never responds: 0 trials. Nothing ran.",
    );
  });
});
