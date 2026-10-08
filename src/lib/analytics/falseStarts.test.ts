/**
 * False starts on the frontend — `DATA.md#false-starts`. The sidecar decides;
 * these pin that the client keeps its two lists apart and still names every
 * set-aside run where runs are listed.
 */

import { describe, expect, it } from "vitest";

import { indexLogbook } from "@/lib/logbook/store";
import type { RunChange } from "@/lib/logbook/types";

import { restartsOf, sessionFalseStartsOf, sessionRunsOf } from "./session";
import type { AnalyticsSummary, RunSummary } from "./types";

function run(id: string, animalId: string, startedAt: string, falseStart = false): RunSummary {
  return {
    runId: id,
    sessionId: "s1",
    animalId,
    startedAt,
    falseStart,
    falseStartSource: falseStart ? "automatic" : null,
    restartedBy: null,
  } as unknown as RunSummary;
}

const summary = {
  animals: [
    { id: "a1", name: "remy1" },
    { id: "a2", name: "remy2" },
  ],
  runs: [run("real", "a1", "10:05"), run("solo", "a2", "10:00")],
  falseStarts: [run("early", "a1", "10:00", true)],
} as unknown as AnalyticsSummary;

describe("session lists", () => {
  it("never mixes a false start into the counted runs", () => {
    expect(sessionRunsOf(summary, "s1").map((r) => r.runId)).toEqual(["real", "solo"]);
    expect(sessionFalseStartsOf(summary, "s1").map((r) => r.runId)).toEqual(["early"]);
  });

  it("lists every run of an animal that restarted, in start order, and nobody else", () => {
    const groups = restartsOf(summary, "s1");
    expect(groups.map((g) => g.animalId)).toEqual(["a1"]);
    expect(groups[0]!.runs.map((r) => r.runId)).toEqual(["early", "real"]);
  });
});

describe("the log's changes", () => {
  it("files a false start apart from the changes it must not be counted among", () => {
    const change = (runId: string, falseStart: boolean) =>
      ({ runId, sessionId: "s1", animalId: "a1", falseStart }) as unknown as RunChange;
    const entry = indexLogbook([], {
      cohortId: "c",
      logs: [],
      notes: [],
      changes: [change("early", true), change("real", false)],
    });
    expect(entry.changesBySession.get("s1")!.map((c) => c.runId)).toEqual(["real"]);
    expect(entry.falseStartsBySession.get("s1")!.map((c) => c.runId)).toEqual(["early"]);
  });
});
