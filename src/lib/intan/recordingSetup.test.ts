import { describe, expect, it } from "vitest";

import { DEFAULT_RECORDING_DEFAULTS, type RecordingDefaults } from "./defaults";
import { reconcileRows, type BoxRow } from "./recordingSetup";

/** Defaults remembering box 3 on port A and box 5 on port B. */
const remembered: RecordingDefaults = {
  ...DEFAULT_RECORDING_DEFAULTS,
  boxes: {
    "3": { record: true, port: "A", firstChannel: 0, lastChannel: 31, probeMapPath: "/maps/a.xml" },
    "5": { record: false, port: "B", firstChannel: 4, lastChannel: 15, probeMapPath: null },
  },
};

function row(box: number, animalName: string, changes: Partial<BoxRow> = {}): BoxRow {
  return {
    box,
    animalName,
    record: true,
    port: "",
    firstChannel: 0,
    lastChannel: -1,
    probeMapPath: null,
    probeMap: null,
    probeError: null,
    ...changes,
  };
}

describe("reconcileRows", () => {
  it("seeds each mapped box from what the last Record step remembered for it", () => {
    const rows = reconcileRows(
      [
        { box: 3, animalName: "Rat-07" },
        { box: 4, animalName: "Rat-08" },
      ],
      remembered,
      [],
    );
    expect(rows).toEqual([
      row(3, "Rat-07", { port: "A", lastChannel: 31, probeMapPath: "/maps/a.xml" }),
      row(4, "Rat-08"),
    ]);
  });

  it("keeps what was typed for a box that is still mapped", () => {
    const typed = [row(3, "Rat-07", { port: "C", firstChannel: 8, lastChannel: 23 })];
    expect(reconcileRows([{ box: 3, animalName: "Rat-07" }], remembered, typed)).toEqual(typed);
  });

  it("holds the rows while the mapped boxes are still loading", () => {
    const typed = [row(3, "Rat-07", { port: "C" })];
    expect(reconcileRows([], remembered, typed)).toBe(typed);
  });
});
