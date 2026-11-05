/**
 * The session's shapes (`TASKS.md#the-spine-editor`): recognised from the
 * blocks and written back to them, the reversal making the reversed trial
 * types it needs. What follows each block is still the preview's.
 */

import { describe, expect, it } from "vitest";

import type { SpineDefinition } from "./spine";
import { applyShape, canReverse, defaultShape, endRuleWords, reversedMap, sessionSentence, shapeOf } from "./sessionShape";

function goNoGo(): SpineDefinition {
  return {
    id: "gng",
    name: "GNG",
    category: "Tasks",
    slots: [
      { id: "port", type: "digital_in" },
      { id: "resp", type: "digital_in" },
      { id: "cue", type: "digital_out" },
      { id: "sample", type: "digital_out" },
      { id: "reward", type: "digital_out" },
    ],
    spine: [
      { phase: "wait", on: "port", outputs: ["cue"] },
      { phase: "present", outputs: ["cue", "sample"], ms: 1000, abortOnRelease: "port" },
      { phase: "response", responses: ["resp"], ms: 3000 },
      { phase: "outcome", ms: 0 },
      { phase: "iti", ms: 3000 },
    ],
    rows: [
      { id: "row_1", name: "Go", bind: { sample: "odor_line_1" }, rewardMs: 100, rewardPermille: 1000, map: { resp: { outcome: "correct", line: "reward", rewardPermille: 1000 }, timeout: { outcome: "omission" } } },
      { id: "row_2", name: "No-go", bind: { sample: "odor_line_2" }, rewardMs: 100, rewardPermille: 1000, map: { resp: { outcome: "false_alarm" }, timeout: { outcome: "withheld" } } },
    ],
    blocks: [{ id: "b1", rows: ["row_1", "row_2"], select: "weighted", weights: [3, 1], trials: 200 }],
    params: {},
    legacyNames: [],
    notes: "",
  };
}

describe("recognising a shape", () => {
  it("reads one block of N as single, and anything with a draw or a loop alone as custom", () => {
    expect(shapeOf(goNoGo())).toEqual({ kind: "single", trials: 200 });
    const drawn = goNoGo();
    drawn.blocks[0]!.trialsMax = 300;
    expect(shapeOf(drawn)).toEqual({ kind: "custom" });
    const looped = goNoGo();
    looped.blocks[0]!.next = "b1";
    expect(shapeOf(looped)).toEqual({ kind: "custom" });
  });

  it("round-trips each shape through the blocks", () => {
    const reversal = applyShape(goNoGo(), { kind: "reversal", correct: 8, of: 10, trials: 60 });
    expect(shapeOf(reversal)).toEqual({ kind: "reversal", correct: 8, of: 10, trials: 60 });
    const alternate = applyShape(goNoGo(), { kind: "alternate", trials: 40, cap: 400 });
    expect(shapeOf(alternate)).toEqual({ kind: "alternate", trials: 40, cap: 400 });
    expect(shapeOf(applyShape(alternate, { kind: "single", trials: 150 }))).toEqual({ kind: "single", trials: 150 });
  });
});

describe("a reversal", () => {
  it("gives each trial type the map of one whose correct answer differs: go becomes no-go", () => {
    const def = goNoGo();
    expect(reversedMap(def.rows[0]!, def.rows)).toEqual(def.rows[1]!.map);
    expect(reversedMap(def.rows[1]!, def.rows)).toEqual(def.rows[0]!.map);
    expect(canReverse(def)).toBe(true);
  });

  it("swaps a 2AFC pair's maps, so the reversed left row pays at the right well from the right line", () => {
    const def = goNoGo();
    def.spine[2] = { phase: "response", responses: ["left", "right"], ms: 5000 };
    def.rows[0]!.map = { left: { outcome: "correct", line: "reward_l" }, right: { outcome: "wrong_response" }, timeout: { outcome: "omission" } };
    def.rows[1]!.map = { left: { outcome: "wrong_response" }, right: { outcome: "correct", line: "reward_r" }, timeout: { outcome: "omission" } };
    const next = applyShape(def, { kind: "reversal", correct: 8, of: 10, trials: 60 });
    expect(next.rows.map((r) => [r.id, r.name])).toEqual([
      ["row_1", "Go"],
      ["row_2", "No-go"],
      ["row_1_rev", "Go (reversed)"],
      ["row_2_rev", "No-go (reversed)"],
    ]);
    expect(next.rows[2]!.map).toEqual(def.rows[1]!.map);
    expect(next.rows[2]!.bind).toEqual(def.rows[0]!.bind);
    expect(next.blocks).toEqual([
      { id: "b1", rows: ["row_1", "row_2"], select: "weighted", weights: [3, 1], criterion: { correct: 8, of: 10 } },
      { id: "b2", rows: ["row_1_rev", "row_2_rev"], trials: 60 },
    ]);
  });

  it("cannot be made when every trial type has the same correct answer", () => {
    const def = goNoGo();
    def.rows[1]!.map = structuredClone(def.rows[0]!.map!);
    expect(canReverse(def)).toBe(false);
    expect(reversedMap(def.rows[0]!, def.rows)).toBeNull();
  });

  it("drops its reversed rows when another shape replaces it", () => {
    const reversal = applyShape(goNoGo(), { kind: "reversal", correct: 8, of: 10, trials: 60 });
    const single = applyShape(reversal, { kind: "single", trials: 100 });
    expect(single.rows.map((r) => r.id)).toEqual(["row_1", "row_2"]);
    expect(single.blocks).toEqual([{ id: "b1", rows: ["row_1", "row_2"], select: "weighted", weights: [3, 1], trials: 100 }]);
  });
});

describe("two blocks that alternate", () => {
  it("loop back to the first and set the cap, since only the cap ends them", () => {
    const next = applyShape(goNoGo(), { kind: "alternate", trials: 40, cap: 400 });
    expect(next.blocks).toEqual([
      { id: "b1", rows: ["row_1", "row_2"], select: "weighted", weights: [3, 1], trials: 40 },
      { id: "b2", rows: ["row_1", "row_2"], trials: 40, next: "b1" },
    ]);
    expect(next.sessionTrials).toBe(400);
    expect(defaultShape(goNoGo(), "alternate")).toEqual({ kind: "alternate", trials: 100, cap: 400 });
  });
});

describe("the session in words", () => {
  it("names each block, its trial types and end rule, and what follows as the preview says", () => {
    const def = applyShape(goNoGo(), { kind: "alternate", trials: 40, cap: 400 });
    expect(endRuleWords({ id: "x", rows: [], trials: 40, trialsMax: 60, criterion: { correct: 8, of: 10 } })).toBe("40–60 trials, or 8 of the last 10 right");
    expect(sessionSentence(def, [1, 0])).toBe("Block 1 (Go, No-go): 40 trials, then Block 2. Block 2 (Go, No-go): 40 trials, then back to Block 1.");
    expect(sessionSentence(goNoGo(), [null])).toBe("Block 1 (Go, No-go): 200 trials, then the session ends.");
    expect(sessionSentence(goNoGo(), [])).toBe("Block 1 (Go, No-go): 200 trials.");
  });
});
