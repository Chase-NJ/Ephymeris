/**
 * The spine editor's edits — `TASKS.md#the-spine-editor`. The editor holds the
 * unsaved document and changes only what the operator asked; everything it
 * draws comes back from `tasks.preview`. These pin the edits that touch more
 * than one place: a row leaving its blocks, a phase moving every block's
 * override index, a block leaving every `next`.
 */

import { describe, expect, it } from "vitest";

import type { TaskDiagnostic } from "@/lib/ws/protocol";

import {
  addBlock,
  addRow,
  diagnosticsOn,
  foldStored,
  insertPhase,
  isSpine,
  meterOf,
  removeBlock,
  removePhase,
  removeRow,
  setBinding,
  setMapEntry,
  type SpineDefinition,
} from "./spine";

/** The go/no-go seed, named and bound — as `taskdef/seeds.py` writes it. */
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
      { phase: "hold", on: "port", outputs: ["cue"], ms: 200 },
      { phase: "present", outputs: ["cue", "sample"], ms: 1000, abortOnRelease: "port" },
      { phase: "response", responses: ["resp"], ms: 3000 },
      { phase: "outcome", ms: 0 },
      { phase: "iti", ms: 3000 },
    ],
    rows: [
      {
        id: "row_1",
        name: "Go",
        bind: { port: "odor_port", sample: "odor_line_1" },
        rewardMs: 100,
        rewardPermille: 1000,
        map: {
          resp: { outcome: "correct", line: "reward", rewardPermille: 1000 },
          timeout: { outcome: "omission" },
        },
      },
      {
        id: "row_2",
        name: "No-go",
        bind: { port: "odor_port", sample: "odor_line_2" },
        rewardMs: 100,
        rewardPermille: 1000,
        map: { resp: { outcome: "false_alarm" }, timeout: { outcome: "withheld" } },
      },
    ],
    blocks: [
      { id: "b1", rows: ["row_1", "row_2"], select: "weighted", weights: [3, 1], trials: 100, phaseMs: { "5": 4000, "2": 800 } },
      { id: "b2", rows: ["row_2"], trials: 20, next: "b1" },
    ],
    params: {},
    legacyNames: [],
    notes: "",
  };
}

describe("a spine document", () => {
  it("is told from a trial-table one by its spine", () => {
    expect(isSpine(goNoGo())).toBe(true);
    expect(isSpine({ id: "t", name: "T", trials: [], stages: [] } as never)).toBe(false);
  });
});

describe("rows", () => {
  it("adds a row with the next free neutral id, no name, copied from the last, drawn where it was", () => {
    const next = addRow(goNoGo());
    const row = next.rows[2]!;
    expect(row!.id).toBe("row_3");
    expect(row!.name).toBe("");
    expect(row!.map).toEqual(goNoGo().rows[1]!.map);
    expect(row!.bind).toEqual(goNoGo().rows[1]!.bind);
    expect(next.blocks[0]!.rows).toEqual(["row_1", "row_2", "row_3"]);
    expect(next.blocks[0]!.weights).toEqual([3, 1, 1]);
    expect(next.blocks[1]!.rows).toEqual(["row_2", "row_3"]);
  });

  it("never reuses an id another row holds, wherever it sits", () => {
    const def = goNoGo();
    def.rows[0]!.id = "row_3";
    expect(addRow(def).rows[2]!.id).toBe("row_1");
  });

  it("removes a row from every block, with its weight", () => {
    const next = removeRow(goNoGo(), 0);
    expect(next.rows.map((r) => r.id)).toEqual(["row_2"]);
    expect(next.blocks[0]!).toMatchObject({ rows: ["row_2"], weights: [1] });
  });

  it("binds one slot of one row and maps one response", () => {
    const bound = setBinding(goNoGo(), 1, "resp", "right_well");
    expect(bound.rows[1]!.bind).toEqual({ port: "odor_port", sample: "odor_line_2", resp: "right_well" });
    expect(bound.rows[0]!.bind.resp).toBeUndefined();
    const unbound = setBinding(bound, 1, "resp", "");
    expect("resp" in unbound.rows[1]!.bind).toBe(false);

    const mapped = setMapEntry(goNoGo(), 0, "resp", { outcome: "correct", line: "reward", rewardPermille: 800 });
    expect(mapped.rows[0]!.map?.resp).toEqual({ outcome: "correct", line: "reward", rewardPermille: 800 });
    expect(mapped.rows[1]!.map).toEqual(goNoGo().rows[1]!.map);
  });
});

describe("phases", () => {
  it("inserts a phase from the palette and moves each block's overrides with the phases after it", () => {
    const next = insertPhase(goNoGo(), 2, "delay");
    expect(next.spine.map((p) => p.phase)).toEqual(["wait", "hold", "delay", "present", "response", "outcome", "iti"]);
    expect(next.spine[2]!).toEqual({ phase: "delay", ms: 1000 });
    expect(next.blocks[0]!.phaseMs).toEqual({ "6": 4000, "3": 800 });
  });

  it("removes a phase, its overrides with it, and moves the rest back", () => {
    const next = removePhase(goNoGo(), 2);
    expect(next.spine.map((p) => p.phase)).toEqual(["wait", "hold", "response", "outcome", "iti"]);
    expect(next.blocks[0]!.phaseMs).toEqual({ "4": 4000 });
  });

  it("gives a new phase the fields its kind needs, from the slots the spine has", () => {
    expect(insertPhase(goNoGo(), 0, "wait").spine[0]!).toEqual({ phase: "wait", on: "port" });
    expect(insertPhase(goNoGo(), 0, "counter").spine[0]!).toEqual({ phase: "counter", on: "port", count: 5 });
    expect(insertPhase(goNoGo(), 0, "response").spine[0]!).toEqual({ phase: "response", responses: [], ms: 3000 });
  });
});

describe("values stored over a phase", () => {
  const tuned = (): SpineDefinition => ({
    ...goNoGo(),
    params: { present_2_ms: 700, block_b1_iti_5_ms: 4500, reward_ms_row_1: 80 },
  });
  const stored = [
    { key: "present_2_ms", value: 700, target: { kind: "phase" as const, index: 2 }, field: "spine[2].ms" },
    { key: "block_b1_iti_5_ms", value: 4500, target: { kind: "block" as const, index: 0 }, field: "blocks[0].phaseMs.5" },
    { key: "reward_ms_row_1", value: 80, target: { kind: "row" as const, index: 0 }, field: null },
  ];

  it("fold into the fields they override, so a phase can move with its value", () => {
    const folded = foldStored(tuned(), stored);
    expect(folded.spine[2]!.ms).toBe(700);
    expect(folded.blocks[0]!.phaseMs).toEqual({ "5": 4500, "2": 800 });
    expect(folded.params).toEqual({ reward_ms_row_1: 80 });
  });

  it("then travel with their phase when one is inserted before it", () => {
    const next = insertPhase(foldStored(tuned(), stored), 0, "delay");
    expect(next.spine[3]).toMatchObject({ phase: "present", ms: 700 });
    expect(next.blocks[0]!.phaseMs).toEqual({ "6": 4500, "3": 800 });
    expect(next.params).toEqual({ reward_ms_row_1: 80 });
  });
});

describe("blocks", () => {
  it("adds a block drawing every row, with a fresh id", () => {
    const next = addBlock(goNoGo());
    expect(next.blocks[2]!).toEqual({ id: "b3", rows: ["row_1", "row_2"], trials: 100 });
  });

  it("removes a block and every next that named it", () => {
    const next = removeBlock(goNoGo(), 0);
    expect(next.blocks).toEqual([{ id: "b2", rows: ["row_2"], trials: 20 }]);
  });
});

describe("where a diagnostic shows", () => {
  const d = (kind: TaskDiagnostic["target"]["kind"], index: number | null): TaskDiagnostic => ({
    location: "x",
    message: "m",
    code: "SPN106",
    target: { kind, index },
  });

  it("is its target, never its message", () => {
    const all = [d("phase", 2), d("row", 0), d("block", 1), d("phase", 3), d("ram", null)];
    expect(diagnosticsOn(all, "phase", 2)).toEqual([all[0]]);
    expect(diagnosticsOn(all, "ram")).toEqual([all[4]]);
    expect(diagnosticsOn(all, "block", 0)).toEqual([]);
  });
});

describe("the RAM meter", () => {
  it("draws the parts the sidecar counted, against the budget", () => {
    const meter = meterOf({ bytes: 4000, budget: 5000, parts: [{ label: "A", bytes: 3000 }, { label: "B", bytes: 1000 }] });
    expect(meter!.over).toBe(false);
    expect(meter!.scale).toBe(5000);
    expect(meter!.segments).toEqual([
      { label: "A", bytes: 3000, start: 0, width: 0.6 },
      { label: "B", bytes: 1000, start: 0.6, width: 0.2 },
    ]);
    expect(meter!.budgetAt).toBe(1);
  });

  it("over the budget, scales to the bytes so the overflow shows past the budget's mark", () => {
    const meter = meterOf({ bytes: 6250, budget: 5000, parts: [{ label: "A", bytes: 6250 }] });
    expect(meter!.over).toBe(true);
    expect(meter!.budgetAt).toBe(0.8);
  });

  it("has nothing to draw when the spine cannot be lowered", () => {
    expect(meterOf({ bytes: null, budget: 5000, parts: [] })).toBeNull();
  });
});
