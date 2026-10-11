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

  // B5: Back to Boxes, move the animal from box 3 to box 5, return to Record.
  // The draft still holds box 3's row; `intan.configure` must not name box 3.
  it("follows an animal moved from box 3 to box 5 after the draft was saved (B5)", () => {
    const draft = [row(3, "Rat-07", { port: "A", lastChannel: 31 })];
    const rows = reconcileRows([{ box: 5, animalName: "Rat-07" }], remembered, draft);
    expect(rows.map((r) => r.box)).toEqual([5]);
    expect(rows[0]).toEqual(row(5, "Rat-07", { record: false, port: "B", firstChannel: 4, lastChannel: 15 }));
  });

  it("drops a box no longer mapped and adds a newly mapped one, keeping the rest as typed (B5)", () => {
    const draft = [
      row(3, "Rat-07", { port: "A", lastChannel: 31 }),
      row(4, "Rat-08", { port: "C", firstChannel: 2, lastChannel: 9 }),
    ];
    const rows = reconcileRows(
      [
        { box: 4, animalName: "Rat-08" },
        { box: 5, animalName: "Rat-07" },
      ],
      remembered,
      draft,
    );
    expect(rows).toEqual([
      row(4, "Rat-08", { port: "C", firstChannel: 2, lastChannel: 9 }),
      row(5, "Rat-07", { record: false, port: "B", firstChannel: 4, lastChannel: 15 }),
    ]);
  });

  it("names the animal mapped now on a box kept from the draft (B5)", () => {
    const draft = [row(3, "Rat-07", { port: "A" })];
    const rows = reconcileRows([{ box: 3, animalName: "Rat-09" }], remembered, draft);
    expect(rows).toEqual([row(3, "Rat-09", { port: "A" })]);
  });

  it("holds the rows while the mapped boxes are still loading", () => {
    const typed = [row(3, "Rat-07", { port: "C" })];
    expect(reconcileRows([], remembered, typed)).toBe(typed);
  });
});
