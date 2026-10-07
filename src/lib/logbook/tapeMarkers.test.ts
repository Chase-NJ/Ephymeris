import { describe, expect, it } from "vitest";

import type { TrialRecord } from "../analytics/types";
import { tapeMarkers, type TapeRun } from "./tapeMarkers";
import type { NoteScope, SessionNote } from "./types";

const RUN: TapeRun = {
  animalId: "a1",
  boxNumber: 3,
  startedAt: "2026-10-06T09:00:00Z",
  endedAt: "2026-10-06T09:10:00Z",
};

const TRIALS: TrialRecord[] = [0, 1, 2, 3].map((index) => ({
  index,
  triggerCode: 101,
  outcome: "rewarded",
  atMs: index * 120_000, // a trial every two minutes
  latencyMs: 500,
}));

function note(at: string, scope: Partial<NoteScope> = {}): SessionNote {
  return {
    id: at,
    sessionId: "s",
    cohortId: "c",
    at,
    createdAt: at,
    editedAt: null,
    tag: "observation",
    scope: { kind: "session", animalId: null, box: null, ...scope },
    body: "x",
    offsetMs: null,
    carryForward: false,
    resolvedAt: null,
    resolvedInSessionId: null,
  };
}

describe("tapeMarkers", () => {
  it("places a note before the first trial that opened after it", () => {
    const [marker] = tapeMarkers([note("2026-10-06T09:03:00Z")], RUN, TRIALS);
    expect(marker?.position).toBe(2);
    expect(marker?.runOffsetMs).toBe(180_000);
  });

  it("puts a note after the last trial at the tape's end", () => {
    const [marker] = tapeMarkers([note("2026-10-06T09:09:00Z")], RUN, TRIALS);
    expect(marker?.position).toBe(TRIALS.length);
  });

  it("only marks the animal or box a note is about", () => {
    const notes = [
      note("2026-10-06T09:01:00Z", { kind: "animal", animalId: "a2" }),
      note("2026-10-06T09:02:00Z", { kind: "box", box: 3 }),
      note("2026-10-06T09:03:00Z", { kind: "box", box: 4 }),
    ];
    expect(tapeMarkers(notes, RUN, TRIALS).map((m) => m.note.scope.box)).toEqual([3]);
  });

  it("ignores a note from outside the run, past a minute's slack", () => {
    expect(tapeMarkers([note("2026-10-06T13:00:00Z")], RUN, TRIALS)).toEqual([]);
    expect(tapeMarkers([note("2026-10-06T08:59:30Z")], RUN, TRIALS)).toHaveLength(1);
  });

  it("draws nothing on a tape with no clock", () => {
    const clockless = TRIALS.map((t) => ({ ...t, atMs: null }));
    expect(tapeMarkers([note("2026-10-06T09:03:00Z")], RUN, clockless)).toEqual([]);
  });
});
