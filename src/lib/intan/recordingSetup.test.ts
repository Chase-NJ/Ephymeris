import { describe, expect, it } from "vitest";

import { DEFAULT_RECORDING_DEFAULTS, normalizeRecordingDefaults, type RecordingDefaults } from "./defaults";
import {
  applyParsedProbeMap,
  assignPorts,
  configurePayload,
  presentPorts,
  reconcileRows,
  recordingReadiness,
  rememberedDefaults,
  saveDirectory,
  type BoxRow,
  type IntanFacts,
  type MappedBox,
} from "./recordingSetup";
import type { ProbeMap } from "./types";

/**
 * What earlier Record steps remembered, loaded as settings are: box 3 wired to
 * port A, box 5 to port B, and probe maps for Rat-07 and Rat-09. Box 3's entry
 * still carries the per-box probe map an older build stored, Rat-02's, the
 * animal that last recorded there.
 */
const remembered: RecordingDefaults = normalizeRecordingDefaults({
  boxes: {
    "3": { record: true, port: "A", firstChannel: 0, lastChannel: 31, probeMapPath: "/maps/rat02.xml" },
    "5": { record: false, port: "B", firstChannel: 4, lastChannel: 15, probeMapPath: null },
  },
  probeMaps: { "id-Rat-07": "/maps/rat07.xml", "id-Rat-09": "/maps/rat09.xml" },
});

const MAP_07: ProbeMap = { name: "rat07", pages: [], siteCount: 16 };

/** A mapped box as the sidecar reports it; the animal's id is derived from its name. */
function mapped(box: number, animalName: string): MappedBox {
  return { box, animalId: `id-${animalName}`, animalName };
}

function row(box: number, animalName: string, changes: Partial<BoxRow> = {}): BoxRow {
  return {
    box,
    animalId: `id-${animalName}`,
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
  it("seeds each box's wiring from the box's memory, and its probe map from its animal's", () => {
    const rows = reconcileRows([mapped(3, "Rat-07"), mapped(4, "Rat-08")], remembered, []);
    expect(rows).toEqual([
      row(3, "Rat-07", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat07.xml" }),
      row(4, "Rat-08"),
    ]);
  });

  it("starts a new animal with no remembered probe map blank, though its box held another animal's", () => {
    const rows = reconcileRows([mapped(3, "Rat-11")], remembered, []);
    expect(rows).toEqual([row(3, "Rat-11", { port: "A", lastChannel: 31 })]);
  });

  it("brings an animal's remembered probe map to whichever box it is on now", () => {
    const rows = reconcileRows([mapped(5, "Rat-09")], remembered, []);
    expect(rows).toEqual([
      row(5, "Rat-09", { record: false, port: "B", firstChannel: 4, lastChannel: 15, probeMapPath: "/maps/rat09.xml" }),
    ]);
  });

  it("brings the probe map chosen this visit to a box the animal moved to that wasn't in the draft", () => {
    const draft = [row(5, "Rat-07", { port: "B", lastChannel: 15, probeMapPath: "/maps/rat07-today.xml", probeMap: MAP_07 })];
    const rows = reconcileRows([mapped(3, "Rat-07")], remembered, draft);
    expect(rows).toEqual([
      row(3, "Rat-07", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat07-today.xml", probeMap: MAP_07 }),
    ]);
  });

  it("keeps what was typed, probe map included, for the same animal on the same box", () => {
    const typed = [
      row(3, "Rat-07", {
        port: "C",
        firstChannel: 8,
        lastChannel: 23,
        probeMapPath: "/maps/rat07.xml",
        probeMap: { name: "rat07", pages: [], siteCount: 16 },
      }),
    ];
    expect(reconcileRows([mapped(3, "Rat-07")], remembered, typed)).toBe(typed);
  });

  it("keeps the row of an animal renamed meanwhile, under its new name", () => {
    const typed = [row(3, "Rat-07", { port: "C", probeMapPath: "/maps/rat07.xml" })];
    const rows = reconcileRows([{ box: 3, animalId: "id-Rat-07", animalName: "Rat-07b" }], remembered, typed);
    expect(rows).toEqual([{ ...typed[0]!, animalName: "Rat-07b" }]);
  });

  // B5: Back to Boxes, move the animal from box 3 to box 5, return to Record.
  // The draft still holds box 3's row; `intan.configure` must not name box 3.
  it("follows an animal moved from box 3 to box 5 after the draft was saved (B5)", () => {
    const draft = [row(3, "Rat-07", { port: "A", lastChannel: 31 })];
    const rows = reconcileRows([mapped(5, "Rat-07")], remembered, draft);
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
        mapped(4, "Rat-08"),
        mapped(5, "Rat-07"),
      ],
      remembered,
      draft,
    );
    expect(rows).toEqual([
      row(4, "Rat-08", { port: "C", firstChannel: 2, lastChannel: 9 }),
      row(5, "Rat-07", { record: false, port: "B", firstChannel: 4, lastChannel: 15 }),
    ]);
  });

  // Decisions on #38: a box whose animal changed since the draft was saved
  // resets its row. Port and range are the box's wiring, so they come from the
  // box's memory; the probe map is the animal's implant, so it is the one last
  // used for the animal now on the box, wherever it moved.
  it("resets a box whose animal changed since the draft: box wiring from memory, the new animal's probe map", () => {
    const draft = [
      row(3, "Rat-07", { port: "C", firstChannel: 8, lastChannel: 23, probeMapPath: "/maps/rat07.xml", probeMap: MAP_07 }),
    ];
    const rows = reconcileRows([mapped(3, "Rat-09")], remembered, draft);
    expect(rows).toEqual([row(3, "Rat-09", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat09.xml" })]);
  });

  it("resets both rows when two animals swap boxes, and each brings its own probe map", () => {
    const draft = [
      row(3, "Rat-07", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat07-today.xml" }),
      row(5, "Rat-09", { port: "C", lastChannel: 15, probeMapPath: "/maps/rat09-today.xml" }),
    ];
    const rows = reconcileRows([mapped(3, "Rat-09"), mapped(5, "Rat-07")], remembered, draft);
    expect(rows).toEqual([
      row(3, "Rat-09", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat09-today.xml" }),
      row(5, "Rat-07", { record: false, port: "B", firstChannel: 4, lastChannel: 15, probeMapPath: "/maps/rat07-today.xml" }),
    ]);
  });

  it("returns the same rows when the mapping hasn't changed", () => {
    const typed = [row(3, "Rat-07", { port: "C" }), row(4, "Rat-08")];
    const boxes = [
      mapped(3, "Rat-07"),
      mapped(4, "Rat-08"),
    ];
    expect(reconcileRows(boxes, remembered, typed)).toBe(typed);
  });

  it("holds the rows while the mapped boxes are still loading", () => {
    const typed = [row(3, "Rat-07", { port: "C" })];
    expect(reconcileRows([], remembered, typed)).toBe(typed);
  });
});

describe("assignPorts", () => {
  it("lists only the ports with channels, in letter order", () => {
    expect(presentPorts({ C: 32, A: 64, B: 0 })).toEqual(["A", "C"]);
  });

  it("gives each unassigned box the next free port with its whole range", () => {
    const rows = assignPorts([row(1, "R1"), row(2, "R2")], { A: 32, B: 16 });
    expect(rows).toEqual([row(1, "R1", { port: "A", lastChannel: 31 }), row(2, "R2", { port: "B", lastChannel: 15 })]);
  });

  it("moves a box off a port RHX no longer reports, and clips a range past the port's end", () => {
    const rows = assignPorts(
      [row(1, "R1", { port: "D", firstChannel: 40, lastChannel: 63 }), row(2, "R2", { port: "A", lastChannel: 63 })],
      { A: 32, B: 16 },
    );
    expect(rows).toEqual([
      row(1, "R1", { port: "B", firstChannel: 15, lastChannel: 15 }),
      row(2, "R2", { port: "A", lastChannel: 31 }),
    ]);
  });

  it("shares the first port once every port is taken", () => {
    const rows = assignPorts([row(1, "R1", { port: "A", lastChannel: 15 }), row(2, "R2")], { A: 32 });
    expect(rows[1]).toEqual(row(2, "R2", { port: "A", lastChannel: 31 }));
  });

  it("leaves the rows alone while no port is reported, and when nothing moves", () => {
    const rows = [row(1, "R1", { port: "A", lastChannel: 31 })];
    expect(assignPorts(rows, {})).toBe(rows);
    expect(assignPorts(rows, { A: 32 })).toBe(rows);
  });
});

describe("saveDirectory", () => {
  it("is <session>/ephys by default", () => {
    expect(saveDirectory("/data/c1/2O-Bdisc_15/", null)).toBe("/data/c1/2O-Bdisc_15/ephys");
  });

  it("keeps the session's folder name under a chosen root", () => {
    expect(saveDirectory("D:\\data\\c1\\2O-Bdisc_15", "E:\\ephys\\")).toBe("E:\\ephys/2O-Bdisc_15");
  });

  it("is empty until the session's folder is known", () => {
    expect(saveDirectory(null, "/ephys")).toBe("");
  });
});

describe("recordingReadiness", () => {
  const rhx: IntanFacts = {
    connected: true,
    version: "3.4.0",
    controller: "ControllerRecordUSB3",
    sampleRate: 30000,
    synthetic: false,
    runMode: "stop",
    ports: { A: 32 },
    rigHasSync: true,
  };
  const wired = [
    { box: 1, intanDigitalIn: 1 },
    { box: 2, intanDigitalIn: 2 },
  ];
  const config = DEFAULT_RECORDING_DEFAULTS.config;
  const two = [
    row(1, "R1", { port: "A", firstChannel: 0, lastChannel: 15 }),
    row(2, "R2", { port: "A", firstChannel: 16, lastChannel: 31 }),
  ];

  it("is ready with RHX idle, a headstage, sync wiring, every recorded box bound and disjoint ranges", () => {
    const r = recordingReadiness(two, config, rhx, wired, "/data/s/ephys");
    expect(r.checks.map((c) => c.ok)).toEqual([true, true, true, true, true]);
    expect(r.checks.map((c) => c.label)).toEqual([
      "RHX 3.4.0 · ControllerRecordUSB3 · 30 kS/s",
      "RHX is not recording",
      "Headstage on port A",
      "This rig's wiring has a sync channel",
      "Every recorded box has an Intan digital input",
    ]);
    expect(r).toMatchObject({ overlap: null, firstProblem: null, ready: true, hint: "Ready — continue to Mission Control." });
  });

  it("refuses two recorded boxes on one channel, and names the first", () => {
    const clash = [two[0]!, { ...two[1]!, firstChannel: 15 }];
    const r = recordingReadiness(clash, config, rhx, wired, "/data/s/ephys");
    expect(r.overlap).toBe("A-015 is claimed by box 1 and box 2");
    expect(r.firstProblem).toBe("A-015 is claimed by box 1 and box 2");
    expect(r.ready).toBe(false);
  });

  it("ignores a behavior-only box's range and its missing digital input", () => {
    const rows = [two[0]!, { ...two[1]!, box: 3, record: false, firstChannel: 0 }];
    expect(recordingReadiness(rows, config, rhx, wired, "/data/s/ephys").ready).toBe(true);
  });

  it("names the recorded boxes with no digital input bound", () => {
    const r = recordingReadiness(two, config, rhx, [{ box: 1, intanDigitalIn: 1 }, { box: 2, intanDigitalIn: null }], "/d");
    expect(r.checks[4]).toMatchObject({ ok: false, label: "Box 2 has no Intan digital input bound" });
    expect(r.firstProblem).toBe("Box 2 has no Intan digital input bound");
  });

  it("is not ready while RHX is recording, and says so", () => {
    const r = recordingReadiness(two, config, { ...rhx, runMode: "record" }, wired, "/d");
    expect(r.checks[1]).toMatchObject({ ok: false, label: "RHX is already recording — stop it in RHX first" });
    expect(r.hint).toBe("Finish the recording setup.");
  });

  it("asks for a connection first when RHX is not connected", () => {
    const r = recordingReadiness(two, config, { ...rhx, connected: false, ports: {} }, wired, "/d");
    expect(r.checks.map((c) => c.ok)).toEqual([false, false, false, true, true]);
    expect(r.hint).toBe("Connect Ephymeris to Intan RHX.");
  });

  it("is not ready when nothing would be saved, or before the save directory is known", () => {
    const nothing = { ...config, saveWideband: false, saveSpikes: false, saveLowpass: false, saveHighpass: false };
    const r = recordingReadiness(two, nothing, rhx, wired, "/d");
    expect(r).toMatchObject({ savesSomething: false, firstProblem: "Nothing would be saved", ready: false });
    expect(recordingReadiness(two, config, rhx, wired, "").ready).toBe(false);
  });
});

describe("configurePayload", () => {
  const map: ProbeMap = { name: "probe", pages: [], siteCount: 32 };
  const config = DEFAULT_RECORDING_DEFAULTS.config;

  it("sends the recorded boxes only, with a probe map only once it has parsed", () => {
    const rows = [
      row(3, "R3", { port: "A", lastChannel: 31, probeMapPath: "/maps/a.xml", probeMap: map }),
      row(4, "R4", { port: "B", lastChannel: 15, probeMapPath: "/maps/broken.xml", probeError: "bad xml" }),
      row(5, "R5", { record: false, port: "C" }),
    ];
    expect(configurePayload(rows, config, null, "/data/c1/2O-Bdisc_15")).toEqual({
      ...config,
      saveDirectory: "/data/c1/2O-Bdisc_15/ephys",
      boxes: [
        { box: 3, port: "A", firstChannel: 0, lastChannel: 31, probeMapPath: "/maps/a.xml" },
        { box: 4, port: "B", firstChannel: 0, lastChannel: 15, probeMapPath: null },
      ],
    });
  });

  it("follows a moved animal: rows reconciled to box 5 configure box 5, never box 3 (B5)", () => {
    const draft = [row(3, "Rat-07", { port: "A", lastChannel: 31 })];
    const rows = assignPorts(reconcileRows([mapped(5, "Rat-07")], DEFAULT_RECORDING_DEFAULTS, draft), {
      A: 32,
    });
    expect(configurePayload(rows, config, null, "/s").boxes.map((b) => b.box)).toEqual([5]);
  });

  it("remembers each box's wiring under the box, and each probe map under its animal", () => {
    const rows = [
      row(3, "R3", { port: "A", lastChannel: 31, probeMapPath: "/maps/a.xml", probeMap: map }),
      row(5, "R5", { record: false }),
    ];
    const before = { "id-R3": "/maps/old.xml", "id-R5": "/maps/r5.xml", "id-Rat-02": "/maps/rat02.xml" };
    expect(rememberedDefaults(rows, config, "/ephys", before)).toEqual({
      saveRoot: "/ephys",
      config,
      boxes: {
        "3": { record: true, port: "A", firstChannel: 0, lastChannel: 31 },
        "5": { record: false, port: "", firstChannel: 0, lastChannel: -1 },
      },
      // R3's map replaced, R5's cleared on the form and so forgotten, and an
      // animal not on the rig this group keeps its own.
      probeMaps: { "id-R3": "/maps/a.xml", "id-Rat-02": "/maps/rat02.xml" },
    });
  });

  it("follows an animal's probe map through Continue and a later group on another box", () => {
    const first = [row(3, "Rat-07", { port: "A", lastChannel: 31, probeMapPath: "/maps/rat07.xml", probeMap: map })];
    const saved = rememberedDefaults(first, config, null, {});
    const next = reconcileRows([mapped(5, "Rat-07"), mapped(3, "Rat-02")], saved, []);
    expect(next.map((r) => [r.box, r.animalName, r.port, r.probeMapPath])).toEqual([
      [5, "Rat-07", "", "/maps/rat07.xml"],
      [3, "Rat-02", "A", null],
    ]);
  });
});

describe("applyParsedProbeMap", () => {
  it("shows a parsed map on the row that asked for it, and leaves the others", () => {
    const rows = [row(3, "Rat-07", { probeMapPath: "/maps/rat07.xml" }), row(5, "Rat-09")];
    expect(applyParsedProbeMap(rows, 3, "/maps/rat07.xml", { probeMap: MAP_07 })).toEqual([
      row(3, "Rat-07", { probeMapPath: "/maps/rat07.xml", probeMap: MAP_07 }),
      row(5, "Rat-09"),
    ]);
  });

  it("records why a map didn't parse on the row that asked for it", () => {
    const rows = [row(3, "Rat-07", { probeMapPath: "/maps/broken.xml" })];
    expect(applyParsedProbeMap(rows, 3, "/maps/broken.xml", { error: "not a probe map" })).toEqual([
      row(3, "Rat-07", { probeMapPath: "/maps/broken.xml", probeError: "not a probe map" }),
    ]);
  });
});
