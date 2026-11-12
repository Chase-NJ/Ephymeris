/**
 * The guided first task's rules (`TASKS.md#the-guide`). The spines below are
 * the shapes `taskdef/seeds.py` serves (outputs only), so the stimulus rule is
 * held to the seeds a first-time user actually starts from.
 */

import { describe, expect, it } from "vitest";

import type { TaskDiagnostic } from "@/lib/ws/protocol";

import {
  bindRole,
  GUIDE_STEPS,
  nextStep,
  offerGuide,
  previousStep,
  setScope,
  stepDiagnostics,
  stimulusRoles,
} from "./guide";
import type { SpineDefinition, SpinePhase } from "./spine";

function def(spine: SpinePhase[], slots: string[], rows = 2): SpineDefinition {
  return {
    id: "t",
    name: "",
    kind: "spine",
    spine,
    slots: slots.map((id) => ({ id, type: "digital_out" })),
    rows: Array.from({ length: rows }, (_, i) => ({ id: `r${i + 1}`, name: "", bind: {}, rewardMs: 100, rewardPermille: 1000 })),
    blocks: [{ id: "b1", rows: ["r1", "r2"] }],
    params: {},
  } as unknown as SpineDefinition;
}

/** The full trial #171 gave the 2AFC and go/no-go seeds: the sample is primed before the Present. */
const FULL_TRIAL: SpinePhase[] = [
  { phase: "delay", outputs: ["sample"], ms: 1000 },
  { phase: "wait", on: "port", outputs: ["cue", "sample"], timeoutMs: 4000 },
  { phase: "delay", outputs: ["cue", "sample"], ms: 200 },
  { phase: "present", outputs: ["cue", "sample", "vacuum"], ms: 1000 },
  { phase: "wait", on: "port", outputs: ["cue"] },
  { phase: "response", ms: 5000 },
  { phase: "outcome", ms: 0 },
  { phase: "iti", ms: 3000 },
];

describe("stimulusRoles", () => {
  it("asks the primed sample per trial type, never the vacuum, on the full trial", () => {
    expect(stimulusRoles(def(FULL_TRIAL, ["port", "cue", "sample", "vacuum"]))).toEqual(["sample"]);
  });

  it("asks each of DNMS's two stimuli, and not the line every Present opens", () => {
    const dnms = def(
      [
        ...FULL_TRIAL.slice(0, 4),
        { phase: "delay", outputs: ["cue"], ms: 2000 },
        { phase: "present", outputs: ["cue", "test", "vacuum"], ms: 1000 },
        ...FULL_TRIAL.slice(4),
      ],
      ["port", "cue", "sample", "test", "vacuum"],
      4,
    );
    expect(stimulusRoles(dnms)).toEqual(["sample", "test"]);
  });

  it("asks a trace task's CS, the Present's only output", () => {
    const trace = def(
      [
        { phase: "delay", ms: 2000 },
        { phase: "present", outputs: ["cs"], ms: 2000 },
        { phase: "delay", ms: 1000 },
        { phase: "outcome", ms: 3000 },
        { phase: "iti", ms: 10000 },
      ],
      ["lick", "cs", "us"],
    );
    expect(stimulusRoles(trace)).toEqual(["cs"]);
  });

  it("asks nothing per trial type of a task with no Present", () => {
    const ratio = def([{ phase: "counter", on: "lever", outputs: ["light"] }, { phase: "outcome", ms: 0 }, { phase: "iti", ms: 500 }], ["lever", "light", "reward"], 1);
    expect(stimulusRoles(ratio)).toEqual([]);
  });
});

describe("roles", () => {
  const base = def(FULL_TRIAL, ["port", "cue", "sample", "vacuum"]);

  it("binds a shared role in every trial type, and a per-type role in one", () => {
    const shared = bindRole(base, "port", "odor_port", null);
    expect(shared.rows.map((r) => r.bind.port)).toEqual(["odor_port", "odor_port"]);
    const one = bindRole(shared, "sample", "odor_line_2", 1);
    expect(one.rows.map((r) => r.bind.sample)).toEqual([undefined, "odor_line_2"]);
  });

  it("flips a role either way, sharing the first trial type's channel", () => {
    let d = bindRole(base, "sample", "odor_line_1", 0);
    d = bindRole(d, "sample", "odor_line_2", 1);
    const shared = setScope(["sample"], d, "sample", false);
    expect(shared.perType).toEqual([]);
    expect(shared.def.rows.map((r) => r.bind.sample)).toEqual(["odor_line_1", "odor_line_1"]);
    const back = setScope(shared.perType, shared.def, "sample", true);
    expect(back.perType).toEqual(["sample"]);
    expect(back.def).toBe(shared.def);
  });
});

const diag = (code: string, kind: TaskDiagnostic["target"]["kind"], index: number | null = 0): TaskDiagnostic => ({
  code,
  location: "",
  message: code,
  target: { kind, index },
});

describe("stepDiagnostics", () => {
  const all = [
    diag("SPN108", "row"),
    diag("SPN101", "row"),
    diag("SPN103", "task", null),
    diag("SPN109", "row", 1),
    diag("SPN105", "phase", 3),
    diag("SPN106", "session", null),
    diag("SPN110", "block", 0),
  ];
  const codes = (step: Parameters<typeof stepDiagnostics>[0]) => stepDiagnostics(step, all).map((d) => d.code);

  it("files each problem under the step that can fix it", () => {
    expect(codes("paradigm")).toEqual([]);
    expect(codes("names")).toEqual(["SPN108"]);
    expect(codes("roles")).toEqual(["SPN101", "SPN103"]);
    expect(codes("answers")).toEqual(["SPN109"]);
    expect(codes("timings")).toEqual(["SPN105"]);
    expect(codes("session")).toEqual(["SPN106", "SPN110"]);
  });

  it("shows every problem at Simulate and Save", () => {
    expect(codes("simulate")).toHaveLength(all.length);
    expect(codes("save")).toHaveLength(all.length);
  });
});

describe("steps", () => {
  it("run in the brief's order, with no step after Save or before the paradigm", () => {
    expect(GUIDE_STEPS[0]).toBe("paradigm");
    expect(nextStep("roles")).toBe("answers");
    expect(previousStep("roles")).toBe("names");
    expect(nextStep("save")).toBeNull();
    expect(previousStep("paradigm")).toBeNull();
  });

  it("is offered only while the machine has no spine task", () => {
    expect(offerGuide([])).toBe(true);
    expect(offerGuide([{ spine: false }])).toBe(true);
    expect(offerGuide([{ spine: false }, { spine: true }])).toBe(false);
  });
});
