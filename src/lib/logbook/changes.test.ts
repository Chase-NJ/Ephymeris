import { describe, expect, it } from "vitest";

import { changeFacts, changeParts, changeSummary, changeSummaryText } from "./changes";
import type { RunChange } from "./types";

function change(over: Partial<RunChange> = {}): RunChange {
  return {
    runId: "r",
    sessionId: "s",
    animalId: "a1",
    box: 1,
    task: "GRGL",
    recovered: false,
    previousRunId: "p",
    previousSessionId: "s0",
    first: false,
    taskChange: null,
    boxChange: null,
    params: [],
    paramsKnown: true,
    ...over,
  };
}

describe("changeFacts", () => {
  it("separates the values that moved from the settings only one side has", () => {
    const facts = changeFacts(
      change({
        taskChange: { from: "Shaping", to: "GRGL" },
        boxChange: { from: 2, to: 3 },
        params: [
          { key: "holdMs", from: 200, to: 300 },
          { key: "odor", from: null, to: "A" },
          { key: "lazy", from: true, to: null },
          { key: "sides", from: ["L"], to: ["L", "R"] },
        ],
      }),
    );
    expect(facts.task).toEqual({ from: "Shaping", to: "GRGL", revised: false });
    expect(facts.box).toEqual({ from: "2", to: "3" });
    expect(facts.params).toEqual([
      { key: "holdMs", from: "200", to: "300" },
      { key: "sides", from: '["L"]', to: '["L","R"]' },
    ]);
    expect(facts.counted).toBe("odor new, lazy dropped");
    expect(facts.any).toBe(true);
  });

  it("reads the same name under a new hash as a revised definition", () => {
    const facts = changeFacts(change({ taskChange: { from: "GRGL", to: "GRGL" } }));
    expect(facts.task).toEqual({ from: "GRGL", to: "GRGL", revised: true });
  });

  it("has nothing to show for an unchanged run, and only the task for a first one", () => {
    expect(changeFacts(change()).any).toBe(false);
    expect(changeFacts(change({ first: true }))).toMatchObject({ first: true, any: true, params: [] });
  });

  it("prints as the same words the PDF has always used", () => {
    const parts = changeParts(
      change({
        taskChange: { from: "GRGL", to: "GRGL" },
        boxChange: { from: 2, to: 3 },
        params: [
          { key: "holdMs", from: 200, to: 300 },
          { key: "a", from: null, to: 1 },
          { key: "b", from: null, to: 1 },
          { key: "c", from: null, to: 1 },
          { key: "d", from: null, to: 1 },
        ],
      }),
    );
    expect(parts.map((p) => p.text)).toEqual([
      "GRGL definition revised",
      "box 2 → 3",
      "holdMs 200 → 300",
      "4 settings new",
    ]);
    expect(parts.map((p) => p.mono)).toEqual([false, false, true, false]);
    expect(changeParts(change({ first: true })).map((p) => p.text)).toEqual(["first run · GRGL"]);
  });
});

describe("changeSummary", () => {
  it("counts animals, those that changed, and what kind of change each was", () => {
    const changes = [
      change({ runId: "1", animalId: "a1" }),
      change({ runId: "2", animalId: "a2", taskChange: { from: "A", to: "B" } }),
      change({
        runId: "3",
        animalId: "a3",
        boxChange: { from: 1, to: 2 },
        params: [
          { key: "x", from: 1, to: 2 },
          { key: "y", from: 1, to: 2 },
          { key: "z", from: null, to: 2 },
        ],
      }),
      change({ runId: "4", animalId: "a4", first: true }),
    ];
    const summary = changeSummary(changes);
    expect(summary).toEqual({ animals: 4, changed: 3, first: 1, tasks: 1, boxes: 1, settings: 2 });
    expect(changeSummaryText(summary)).toBe("3 of 4 changed · 1 task · 1 box · 2 settings · 1 first run");
  });

  it("says so when nothing, or everything, changed", () => {
    expect(changeSummaryText(changeSummary([]))).toBe("no runs yet");
    expect(changeSummaryText(changeSummary([change(), change({ runId: "2" })]))).toBe(
      "all 2 unchanged",
    );
    expect(changeSummaryText(changeSummary([change({ taskChange: { from: "A", to: "B" } })]))).toBe(
      "all 1 changed · 1 task",
    );
    expect(
      changeSummaryText(changeSummary([change({ first: true }), change({ runId: "2", first: true })])),
    ).toBe("2 first runs");
  });
});
