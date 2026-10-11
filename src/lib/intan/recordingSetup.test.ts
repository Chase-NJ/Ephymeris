import { describe, expect, it } from "vitest";

import { DEFAULT_RECORDING_DEFAULTS, type RecordingDefaults } from "./defaults";
import {
  assignPorts,
  configurePayload,
  presentPorts,
  reconcileRows,
  recordingReadiness,
  rememberedDefaults,
  saveDirectory,
  type BoxRow,
  type IntanFacts,
} from "./recordingSetup";
import type { ProbeMap } from "./types";

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

  it("returns the same rows when the mapping hasn't changed", () => {
    const typed = [row(3, "Rat-07", { port: "C" }), row(4, "Rat-08")];
    const boxes = [
      { box: 3, animalName: "Rat-07" },
      { box: 4, animalName: "Rat-08" },
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
    const rows = assignPorts(reconcileRows([{ box: 5, animalName: "Rat-07" }], DEFAULT_RECORDING_DEFAULTS, draft), {
      A: 32,
    });
    expect(configurePayload(rows, config, null, "/s").boxes.map((b) => b.box)).toEqual([5]);
  });

  it("remembers every row's port, range and probe as the next starting point", () => {
    const rows = [row(3, "R3", { port: "A", lastChannel: 31, probeMapPath: "/maps/a.xml", probeMap: map }), row(5, "R5", { record: false })];
    expect(rememberedDefaults(rows, config, "/ephys")).toEqual({
      saveRoot: "/ephys",
      config,
      boxes: {
        "3": { record: true, port: "A", firstChannel: 0, lastChannel: 31, probeMapPath: "/maps/a.xml" },
        "5": { record: false, port: "", firstChannel: 0, lastChannel: -1, probeMapPath: null },
      },
    });
  });
});
