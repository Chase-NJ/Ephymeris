import { describe, expect, it } from "vitest";

import type { SessionListItem } from "../analytics/types";
import { buildSession, forPrint } from "./document";
import { indexLogbook } from "./store";
import type { SessionNote } from "./types";

const SESSION: SessionListItem = {
  id: "s1",
  cohortId: "c",
  prefixName: "2O-Bdisc",
  sessionNumber: "14",
  date: "2026-10-02",
  startedAt: "2026-10-02T08:50:00Z",
  endedAt: "2026-10-02T10:30:00Z",
  clockStartedAt: "2026-10-02T09:00:00Z",
  clockEndedAt: "2026-10-02T09:56:00Z",
  status: "completed",
  folderPath: "/x",
  ordinal: 14,
  groupRuns: [],
};

function note(id: string, at: string, offsetMs: number | null, extra: Partial<SessionNote> = {}): SessionNote {
  return {
    id,
    sessionId: "s1",
    cohortId: "c",
    at,
    createdAt: at,
    editedAt: null,
    tag: "hardware",
    scope: { kind: "box", animalId: null, box: 2 },
    body: "Beam → flickers",
    offsetMs,
    carryForward: false,
    resolvedAt: null,
    resolvedInSessionId: null,
    ...extra,
  };
}

describe("buildSession", () => {
  it("reads the session clock, orders notes, and prints what changed", () => {
    const entry = {
      state: "ready" as const,
      error: null,
      ...indexLogbook([SESSION], {
        cohortId: "c",
        logs: [{ sessionId: "s1", operator: "CJ", summary: null, updatedAt: null }],
        notes: [
          note("late", "2026-10-02T09:50:00Z", 3_000_000, { carryForward: true }),
          note("early", "2026-10-02T09:08:00Z", 480_000),
        ],
        changes: [
          {
            runId: "r",
            sessionId: "s1",
            animalId: "a1",
            box: 1,
            task: "GRGL",
            recovered: false,
            previousRunId: "p",
            previousSessionId: "ps",
            first: false,
            taskChange: null,
            boxChange: null,
            params: [{ key: "rewardUl", from: 20, to: 25 }],
            paramsKnown: true,
            falseStart: false,
            falseStartSource: null,
          },
        ],
      }),
    };
    const doc = buildSession(SESSION, entry, null, new Map([["a1", "remy1"]]), new Date());
    expect(doc.title).toBe("2O-Bdisc_14");
    expect(doc.elapsed).toBe("56:00");
    expect(doc.setup).toMatch(/^Set-up began/);
    expect(doc.operator).toBe("CJ");
    expect(doc.notes.map((n) => n.offset)).toEqual(["T+08:00", "T+50:00"]);
    expect(doc.notes[1]!.flag).toBe("carry forward");
    expect(doc.notes[0]!.body).toBe("Beam -> flickers");
    expect(doc.changes).toEqual([{ animal: "remy1", box: "box 1", parts: ["rewardUl 20 -> 25"] }]);
    expect(doc.changesNote).toBeNull();
    expect(doc.performance).toBeNull();
  });
});

describe("forPrint", () => {
  it("keeps what the faces cover and marks what they don't", () => {
    expect(forPrint("Dvořák ΔF/F ≥ 3 ±5% 25 µl — ok… 中文🐭")).toBe(
      "Dvořák ΔF/F >= 3 ±5% 25 µl — ok… ???",
    );
  });

  it("maps glyphs the embedded fonts lack, everywhere in a model", () => {
    expect(forPrint({ a: ["Odor A → right"], b: { c: "≈ 3" }, n: 2 })).toEqual({
      a: ["Odor A -> right"],
      b: { c: "~ 3" },
      n: 2,
    });
  });
});

describe("changeParts", () => {
  it("prints changed values and counts settings only one side has", async () => {
    const { changeParts } = await import("./changes");
    const parts = changeParts({
      runId: "r", sessionId: "s", animalId: "a", box: null, task: "6-Odor", recovered: true,
      previousRunId: "p", previousSessionId: "ps", first: false,
      taskChange: { from: "4-Odor", to: "6-Odor" }, boxChange: null, paramsKnown: true,
      falseStart: false, falseStartSource: null,
      params: [
        { key: "holdMs", from: 200, to: 300 },
        { key: "odor5", from: null, to: 1 },
        { key: "odor6", from: null, to: 1 },
        { key: "a", from: 1, to: null },
        { key: "b", from: 1, to: null },
        { key: "c", from: 1, to: null },
        { key: "d", from: 1, to: null },
      ],
    }).map((p) => p.text);
    expect(parts).toEqual([
      "task 4-Odor → 6-Odor",
      "holdMs 200 → 300",
      "odor5, odor6 new, 4 settings dropped",
    ]);
  });
});
