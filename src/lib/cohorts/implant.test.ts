import { describe, expect, it } from "vitest";

import {
  blankImplant,
  cleanImplant,
  depthOn,
  implantProblem,
  isDate,
  parseChannels,
  summarizeImplant,
  twoBundleImplant,
  type Implant,
  type ImplantTarget,
} from "./implant";

function target(name: string, channels: string, edits: Partial<ImplantTarget> = {}): ImplantTarget {
  return { name, region: "", hemisphere: "left", apMm: 3.2, mlMm: 2.4, dvMm: 4.6, channels, ...edits };
}

function implant(edits: Partial<Implant> = {}): Implant {
  return {
    device: "custom 32-channel electrode",
    surgeryDate: "2026-11-30",
    probeMapPath: null,
    targets: [target("OFC", "0-15"), target("DMS", "16-31", { dvMm: 4.0 })],
    lowerings: [],
    ...edits,
  };
}

describe("parseChannels", () => {
  it("reads a range, a list and both", () => {
    expect(parseChannels("0-15")).toEqual(Array.from({ length: 16 }, (_, i) => i));
    expect(parseChannels("0, 2,4")).toEqual([0, 2, 4]);
    expect(parseChannels("0-3,8,10-11")).toEqual([0, 1, 2, 3, 8, 10, 11]);
    expect(parseChannels(" 7 ")).toEqual([7]);
  });

  it("says why anything else is not channels", () => {
    for (const spec of ["", "a", "5-2", "-1", "1,1", "0-3,2", "1-", "1.5", "0-2000"]) {
      expect(typeof parseChannels(spec), spec).toBe("string");
    }
    expect(parseChannels("1,1")).toMatch(/twice/);
  });
});

describe("implantProblem", () => {
  it("passes the lab's two-bundle electrode once its targets are named", () => {
    expect(implantProblem(implant())).toBeNull();
    expect(implantProblem(twoBundleImplant("2026-11-30"))).toBe("Every target needs a name.");
  });

  it("refuses two targets that claim one channel, naming both", () => {
    const overlap = implant({ targets: [target("OFC", "0-15"), target("DMS", "15-31")] });
    expect(implantProblem(overlap)).toBe("OFC and DMS both claim channel 15.");
    expect(implantProblem(implant({ targets: [target("OFC", "0-15"), target("DMS", "16,18,20")] }))).toBeNull();
  });

  it("names the first thing wrong, in the order the form reads", () => {
    expect(implantProblem(implant({ device: " " }))).toMatch(/device/);
    expect(implantProblem(implant({ surgeryDate: "30/11/2026" }))).toMatch(/surgery date/);
    expect(implantProblem(implant({ targets: [] }))).toMatch(/at least one target/);
    expect(implantProblem(implant({ targets: [target("OFC", "0-7"), target("ofc", "8-15")] }))).toMatch(/called/);
    expect(implantProblem(implant({ targets: [target("OFC", "0-15", { dvMm: Number.NaN })] }))).toMatch(/DV/);
    expect(implantProblem(implant({ targets: [target("OFC", "x")] }))).toMatch(/^OFC: /);
    expect(implantProblem(implant({ lowerings: [{ date: "2026-11-01", mm: 0.25 }] }))).toMatch(/before the surgery/);
    expect(implantProblem(implant({ lowerings: [{ date: "2026-12-14", mm: 0 }] }))).toMatch(/not 0/);
    expect(implantProblem(implant({ lowerings: [{ date: "soon", mm: 1 }] }))).toMatch(/date/);
  });
});

describe("depthOn", () => {
  const lowered = implant({
    lowerings: [
      { date: "2026-12-20", mm: 0.5 },
      { date: "2026-12-14", mm: 0.25 },
    ],
  });
  const [ofc, dms] = lowered.targets as [ImplantTarget, ImplantTarget];

  it("is the surgery depth plus every lowering on or before the date", () => {
    expect(depthOn(lowered, ofc, "2026-12-01")).toEqual({ dvMm: 4.6, setOn: "2026-11-30" });
    expect(depthOn(lowered, ofc, "2026-12-14")).toEqual({ dvMm: 4.85, setOn: "2026-12-14" });
    expect(depthOn(lowered, ofc, "2026-12-19")).toEqual({ dvMm: 4.85, setOn: "2026-12-14" });
    expect(depthOn(lowered, ofc, "2026-12-25")).toEqual({ dvMm: 5.35, setOn: "2026-12-20" });
  });

  it("moves every target by the same distance", () => {
    expect(depthOn(lowered, dms, "2026-12-25")).toEqual({ dvMm: 4.75, setOn: "2026-12-20" });
  });
});

describe("the presets and what Save posts", () => {
  it("starts the lab's electrode as two targets of 16 channels", () => {
    const made = twoBundleImplant("2026-11-30");
    expect(made.targets.map((t) => t.channels)).toEqual(["0-15", "16-31"]);
    expect(made.device).toBe("custom 32-channel electrode");
    expect(blankImplant("2026-11-30").targets).toHaveLength(1);
  });

  it("trims text and puts the lowerings in date order", () => {
    const typed = implant({
      device: " probe ",
      probeMapPath: "  ",
      targets: [target(" OFC ", " 0-15 ", { region: " orbitofrontal cortex " })],
      lowerings: [
        { date: "2026-12-20", mm: 0.5 },
        { date: "2026-12-14", mm: 0.25 },
      ],
    });
    const clean = cleanImplant(typed);
    expect(clean.device).toBe("probe");
    expect(clean.probeMapPath).toBeNull();
    expect(clean.targets[0]).toMatchObject({ name: "OFC", channels: "0-15", region: "orbitofrontal cortex" });
    expect(clean.lowerings.map((l) => l.date)).toEqual(["2026-12-14", "2026-12-20"]);
  });

  it("summarizes an implant in one line for the roster", () => {
    expect(summarizeImplant(null)).toBe("No implant");
    expect(summarizeImplant(implant())).toBe("custom 32-channel electrode · OFC, DMS");
    expect(summarizeImplant(blankImplant("2026-11-30"))).toBe("Implant");
  });

  it("knows a real date from a look-alike", () => {
    expect(isDate("2026-11-30")).toBe(true);
    expect(isDate("2026-02-30")).toBe(false);
    expect(isDate("30/11/2026")).toBe(false);
  });
});
