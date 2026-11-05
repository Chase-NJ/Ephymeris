/**
 * The editor's words (`TASKS.md#the-spine-editor`): a contingency map as a
 * sentence per response, the notes an outcome class needs, what an early
 * exit is scored as, and the roles and timings the guide asks about. Words
 * only: nothing here validates.
 */

import { describe, expect, it } from "vitest";

import type { RigDocument } from "@/lib/hardware/types";

import type { SpineDefinition } from "./spine";
import {
  channelChoices,
  channelGroups,
  channelWord,
  classNote,
  classScore,
  exitNotes,
  mapSentences,
  msWord,
  phaseCaption,
  roleScopes,
  rowSentence,
  seedShapeWords,
  timingFields,
} from "./spineWords";

const rig = {
  rig_version: 1,
  channels: {
    odor_port: { kind: "engagement", label: "odor port" },
    left_well: { kind: "response", label: "left well" },
    right_well: { kind: "response", label: "right well" },
    odor_line_1: { kind: "emitter", label: "sandalwood" },
    odor_line_2: { kind: "emitter", label: "orange" },
    trial_light: { kind: "cue", label: "trial light" },
    fluid_1: { kind: "reward", label: "left water" },
    fluid_2: { kind: "reward", label: "right water" },
  },
  pins: {},
} as unknown as RigDocument;

/** The 2AFC seed, named and bound, in the lab's full trial (#171). */
function twoAfc(): SpineDefinition {
  return {
    id: "afc",
    name: "2AFC",
    category: "Tasks",
    slots: [
      { id: "port", type: "digital_in" },
      { id: "left", type: "digital_in" },
      { id: "right", type: "digital_in" },
      { id: "cue", type: "digital_out" },
      { id: "sample", type: "digital_out" },
      { id: "vacuum", type: "digital_out" },
      { id: "reward_l", type: "digital_out" },
      { id: "reward_r", type: "digital_out" },
    ],
    spine: [
      { phase: "delay", outputs: ["sample"], ms: 1000 },
      { phase: "wait", on: "port", outputs: ["cue", "sample"], timeoutMs: 4000 },
      { phase: "delay", outputs: ["cue", "sample"], ms: 200, abortOnRelease: "port" },
      { phase: "present", outputs: ["cue", "sample", "vacuum"], ms: 1000, abortOnRelease: "port" },
      { phase: "wait", on: "port", edge: "exit", outputs: ["cue"] },
      { phase: "response", responses: ["left", "right"], ms: 5000, holdMs: 200 },
      { phase: "outcome", ms: 0 },
      { phase: "iti", ms: 3000 },
    ],
    rows: [
      {
        id: "row_1",
        name: "Sandalwood left",
        bind: { port: "odor_port", left: "left_well", right: "right_well", cue: "trial_light", sample: "odor_line_1", vacuum: "vacuum", reward_l: "fluid_1", reward_r: "fluid_2" },
        rewardMs: 100,
        rewardPermille: 1000,
        map: {
          left: { outcome: "correct", line: "reward_l", rewardPermille: 1000, hold: true },
          right: { outcome: "wrong_response", penaltyMs: 20000 },
          timeout: { outcome: "omission" },
        },
      },
      {
        id: "row_2",
        name: "",
        bind: {},
        rewardMs: 100,
        rewardPermille: 1000,
        map: { left: { outcome: "wrong_response" }, right: { outcome: "correct", line: "reward_r", rewardPermille: 800, hold: true }, timeout: { outcome: "omission" } },
      },
    ],
    blocks: [{ id: "b1", rows: ["row_1", "row_2"], trials: 200 }],
    params: {},
    legacyNames: [],
    notes: "",
  };
}

describe("a channel in the user's words", () => {
  it("is its Rig-tab label, else its name in words, grouped by kind in the Rig page's order", () => {
    expect(channelWord("odor_line_1", rig)).toBe("sandalwood");
    expect(channelWord("odor_line_9", rig)).toBe("odor line 9");
    expect(channelWord("odor_line_9", null)).toBe("odor line 9");
    const groups = channelGroups(channelChoices(["fluid_1", "trial_light", "odor_line_1", "odor_line_9", "odor_port"], rig));
    expect(groups.map((g) => [g.label, g.choices.map((c) => c.label)])).toEqual([
      ["ports", ["odor port"]],
      ["stimulus lines", ["sandalwood"]],
      ["reward lines", ["left water"]],
      ["cues", ["trial light"]],
      ["other channels", ["odor line 9"]],
    ]);
  });
});

describe("the contingency map as sentences", () => {
  it("names each response by the channel the row binds, the window's order, the timeout last", () => {
    const def = twoAfc();
    expect(mapSentences(def, def.rows[0]!, rig)).toEqual([
      { key: "left", subject: "Left well", clause: "correct, pays left water, held 200 ms" },
      { key: "right", subject: "Right well", clause: "wrong response · then a 20 s penalty instead of the ITI" },
      { key: "timeout", subject: "No answer in 5 s", clause: "omission" },
    ]);
  });

  it("keeps the role's name while a slot is unbound, and says a probability below 1", () => {
    const def = twoAfc();
    expect(rowSentence(def, def.rows[1]!, rig)).toBe(
      "Left → wrong response · Right → correct, pays reward_r on 80 % of trials, held 200 ms · No answer in 5 s → omission",
    );
  });

  it("says what a row with no response window does", () => {
    const def = twoAfc();
    def.spine = [{ phase: "present", outputs: ["sample"], ms: 2000 }, { phase: "outcome", line: "reward_l", ms: 3000 }, { phase: "iti", ms: 10000 }];
    def.rows[1]!.rewardPermille = 0;
    expect(rowSentence(def, def.rows[0]!, rig)).toBe("No answer is asked: every trial pays left water and scores correct");
    expect(rowSentence(def, def.rows[1]!, rig)).toBe("No answer is asked: every trial pays reward_l on 0 % of trials and scores correct");
  });
});

describe("the notes an outcome class needs", () => {
  it("say where the model surprises people, and nothing where it does not", () => {
    expect(classNote("withheld")).toMatch(/counts as a hit/);
    expect(classNote("abort_before_stimulus")).toMatch(/left out of P\(correct\)/);
    expect(classNote("correct")).toBeNull();
    expect(classNote("correct", false)).toMatch(/every trial of this type scores correct/);
    expect(classNote("wrong_response")).toBeNull();
    expect(classScore("withheld")).toBe("hit");
    expect(classScore("abort_during_sampling")).toBe("left out");
    expect(classScore("omission")).toBe("miss");
  });
});

describe("what an early exit is scored as", () => {
  it("is decided by the first Present: before it an abort before the stimulus, after it during sampling", () => {
    const def = twoAfc();
    expect(exitNotes(def, 1)).toEqual([{ exit: "no port within 4 s", outcome: "abort_before_stimulus" }]);
    expect(exitNotes(def, 2)).toEqual([{ exit: "port let go", outcome: "abort_before_stimulus" }]);
    expect(exitNotes(def, 3)).toEqual([{ exit: "port let go", outcome: "abort_during_sampling" }]);
    expect(exitNotes(def, 4)).toEqual([{ exit: "no timeout: it waits as long as it takes", outcome: "" }]);
    expect(exitNotes(def, 5)).toEqual([
      { exit: "no answer within 5 s", outcome: 'each trial type\'s "no answer" line decides' },
      { exit: "an answer let go before 200 ms", outcome: "hold_broken" },
    ]);
    expect(exitNotes(def, 7)[0]!.outcome).toMatch(/already scored/);
  });

  it("makes a Wait's timeout after the stimulus an omission", () => {
    const def = twoAfc();
    def.spine[4] = { ...def.spine[4]!, timeoutMs: 3000 };
    expect(exitNotes(def, 4)).toEqual([{ exit: "no port within 3 s", outcome: "omission" }]);
  });
});

describe("a phase's caption", () => {
  it("says what it waits for, turns on and how long, in words", () => {
    const def = twoAfc();
    expect(def.spine.map(phaseCaption)).toEqual([
      "1 s",
      "until port is entered · up to 4 s",
      "200 ms · port held",
      "cue, sample, vacuum on · 1 s",
      "until port is left",
      "answer at left or right · 5 s · held 200 ms",
      "pays as the trial type says",
      "3 s between trials",
    ]);
    expect(phaseCaption({ phase: "delay", ms: 2000, watch: ["lick"] })).toBe("2 s · records lick");
    expect(phaseCaption({ phase: "counter", on: "lever", count: 1, countMax: 9, timeoutMs: 600000 })).toBe("1–9 × lever · within 10 min");
    expect(msWord(90000)).toBe("1.5 min");
  });

  it("counts a seed's shape", () => {
    expect(seedShapeWords(twoAfc())).toBe("8 steps · 2 trial types · 8 roles");
  });
});

describe("the roles the guide asks once, and the ones it asks per trial type", () => {
  it("make the output only Present phases drive the stimulus, and everything else shared", () => {
    const def = twoAfc();
    def.rows[1]!.bind = {};
    def.rows[0]!.bind = {};
    expect(roleScopes(def)).toEqual({
      port: "shared",
      left: "shared",
      right: "shared",
      cue: "shared",
      sample: "shared",
      vacuum: "per-type",
      reward_l: "shared",
      reward_r: "shared",
    });
  });

  it("keep a role the rows already bind differently per trial type", () => {
    const def = twoAfc();
    def.rows[1]!.bind = { ...def.rows[0]!.bind, sample: "odor_line_2" };
    expect(roleScopes(def).sample).toBe("per-type");
    expect(roleScopes(def).port).toBe("shared");
  });
});

describe("the timings that matter", () => {
  it("are each timed phase, a Wait's limit and the window's hold, labelled by their place in the trial", () => {
    expect(timingFields(twoAfc())).toEqual([
      { at: 0, key: "ms", label: "Delay before the trial" },
      { at: 1, key: "timeoutMs", label: "Give up waiting for port after" },
      { at: 2, key: "ms", label: "Hold at the port before the stimulus for" },
      { at: 3, key: "ms", label: "Stimulus lasts" },
      { at: 5, key: "ms", label: "Time to answer" },
      { at: 5, key: "holdMs", label: "Hold the answer for" },
      { at: 7, key: "ms", label: "Between trials" },
    ]);
  });
});
