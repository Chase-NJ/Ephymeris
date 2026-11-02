import { describe, expect, it } from "vitest";

import type { TaskSimulation } from "@/lib/ws/protocol";

import { DEFAULT_FORM, absentLabels, endedLabel, responsesOf, simulateArgs, switchLabels } from "./simulate";
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
