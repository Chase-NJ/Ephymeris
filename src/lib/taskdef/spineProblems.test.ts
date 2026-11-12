/**
 * Problems as instructions with one-click fixes (`TASKS.md#the-spine-editor`).
 * The sidecar says what is wrong; these say what to do, group what one fix
 * answers, and keep every diagnostic so its cell still marks itself.
 */

import { describe, expect, it } from "vitest";

import type { TaskDiagnostic } from "@/lib/ws/protocol";

import type { SpineDefinition } from "./spine";
import { everyLine, problemLines, targetLines, wiringLines } from "./spineProblems";

function def(): SpineDefinition {
  return {
    id: "t",
    name: "T",
    category: "Tasks",
    slots: [
      { id: "port", type: "digital_in" },
      { id: "sample", type: "digital_out" },
    ],
    spine: [{ phase: "wait", on: "port" }, { phase: "present", outputs: ["sample"], ms: 1000 }, { phase: "outcome", line: "sample", ms: 0 }, { phase: "iti", ms: 1000 }],
    rows: [
      { id: "row_1", name: "Odor 1", bind: { port: "odor_port", sample: "odor_line_1" }, rewardMs: 100, rewardPermille: 1000 },
      { id: "row_2", name: "", bind: {}, rewardMs: 100, rewardPermille: 1000 },
      { id: "row_3", name: "Odor 3", bind: { port: "odor_port", sample: "odor_line_3" }, rewardMs: 100, rewardPermille: 1000 },
    ],
    blocks: [{ id: "b1", rows: ["row_1", "row_2"], next: "b1" }],
    params: { stale_key: 5 },
    legacyNames: [],
    notes: "",
  };
}

const d = (code: string, location: string, message: string, kind: TaskDiagnostic["target"]["kind"], index: number | null): TaskDiagnostic => ({
  code,
  location,
  message,
  target: { kind, index },
});

const all: TaskDiagnostic[] = [
  d("SPN108", "rows[1].name", "this row has no name. Its name is what every readout of it is titled", "row", 1),
  d("SPN101", "rows[1].bind.port", "slot 'port' is bound to no channel", "row", 1),
  d("SPN101", "rows[1].bind.sample", "slot 'sample' is bound to no channel", "row", 1),
  d("SPN103", "rows[0].bind.port", "the enter edge of odor_port has no live strobe code. Save the wiring on the Rig page to issue one", "row", 0),
  d("SPN103", "rows[0].bind.port", "the exit edge of odor_port has no live strobe code. Save the wiring on the Rig page to issue one", "row", 0),
  d("SPN106", "rows[2].id", "no block draws row 'row_3'", "row", 2),
  d("SPN106", "sessionTrials", "nothing but End Session ends this session: its blocks loop, or one never ends. Give the session sessionTrials, or every block an end rule and the last no next", "session", null),
  d("SPN110", "params.stale_key", "no parameter of this task is 'stale_key', so its stored value 5 is not used. Move it to the parameter it belongs to, or remove it", "row", null),
];

describe("a row's problems", () => {
  it("say what to do, and group the unbound roles into one line with a fix from a row that binds them", () => {
    const lines = problemLines(all, def(), null, 1);
    expect(lines.map((l) => [l.code, l.instruction])).toEqual([
      ["SPN108", "Name this trial type: its name titles every readout of it."],
      ["SPN101", "2 roles have no channel yet: pick one for each."],
    ]);
    expect(lines[1]!.diagnostics).toHaveLength(2);
    expect(lines[1]!.detail).toEqual(["slot 'port' is bound to no channel", "slot 'sample' is bound to no channel"]);
    expect(lines[1]!.fix?.label).toBe("Bind like Odor 1");
    const fixed = lines[1]!.fix!.apply(def());
    expect(fixed.rows[1]!.bind).toEqual({ port: "odor_port", sample: "odor_line_1" });
    expect(fixed.rows[0]).toEqual(def().rows[0]);
  });

  it("offer no binding fix when no other row binds those roles", () => {
    const alone = def();
    alone.rows = [alone.rows[1]!];
    const lines = problemLines(all.filter((x) => x.target.index === 1).map((x) => ({ ...x, target: { kind: "row" as const, index: 0 }, location: x.location.replace("[1]", "[0]") })), alone, null, 0);
    expect(lines[1]!.fix).toBeNull();
  });

  it("add a row no block draws to the first block", () => {
    const [line] = problemLines(all, def(), null, 2);
    expect(line!.instruction).toBe("No block presents Odor 3: add it to a block, or remove it.");
    expect(line!.fix!.apply(def()).blocks[0]!.rows).toEqual(["row_1", "row_2", "row_3"]);
  });
});

describe("the Wiring line's problems", () => {
  it("take a shared role's binding problems off the row and say them once", () => {
    const rowLines = problemLines(all, def(), null, 1, ["port"]);
    expect(rowLines.map((l) => l.instruction)).toEqual([
      "Name this trial type: its name titles every readout of it.",
      "Pick the channel that plays sample.",
    ]);
    const wiring = wiringLines([...all, { ...all[1]!, target: { kind: "row", index: 0 }, location: "rows[0].bind.port" }], null, ["port"]);
    expect(wiring).toHaveLength(1);
    expect(wiring[0]!.instruction).toBe("Pick the channel that plays port.");
    expect(wiring[0]!.diagnostics).toHaveLength(2);
    expect(wiringLines(all, null, ["port", "sample"])[0]!.instruction).toBe("2 roles have no channel yet: port, sample.");
    expect(wiringLines(all, null, [])).toEqual([]);
  });
});

describe("the task's problems", () => {
  it("fold every missing edge code into one line that points at the Rig page", () => {
    const lines = problemLines(all, def(), null, null);
    expect(lines[0]).toMatchObject({ code: "SPN103", link: "wiring", fix: null });
    expect(lines[0]!.instruction).toMatch(/^2 channel edges have no strobe code yet/);
    expect(lines[0]!.diagnostics).toHaveLength(2);
  });

  it("drop a stored value nothing reads", () => {
    const line = problemLines(all, def(), null, null).find((l) => l.code === "SPN110")!;
    expect(line.instruction).toMatch(/^Nothing in this task reads the stored value stale_key/);
    expect(line.fix!.apply(def()).params).toEqual({});
  });

  it("cap a session only End Session would end", () => {
    const [line] = targetLines(all, def(), "session", null);
    expect(line!.instruction).toMatch(/^Only End Session would end this session/);
    expect(line!.fix!.label).toBe("Add a cap of 400 trials");
    expect(line!.fix!.apply(def()).sessionTrials).toBe(400);
  });

  it("keep the sidecar's words for anything it has no instruction for", () => {
    const odd = d("SPN111", "spine[1].abortOnRelease", "'port' may not be held when this present starts", "phase", 1);
    expect(targetLines([odd], def(), "phase", 1)).toEqual([
      { code: "SPN111", instruction: odd.message, detail: [odd.message], diagnostics: [odd], fix: null, link: null },
    ]);
  });
});

describe("every line", () => {
  it("says each problem once, wherever the editor would", () => {
    const lines = everyLine(all, def(), null, ["port"]);
    const said = lines.flatMap((l) => l.diagnostics);
    // Each diagnostic in exactly one line.
    expect(new Set(said).size).toBe(said.length);
    expect([...said].sort((a, b) => all.indexOf(a) - all.indexOf(b))).toEqual(all);
    expect(lines.map((l) => l.instruction)).toContain("Pick the channel that plays port.");
    expect(lines.filter((l) => l.code === "SPN103")).toHaveLength(1);
  });

  it("says nothing for no problems", () => {
    expect(everyLine([], def(), null, [])).toEqual([]);
  });
});
