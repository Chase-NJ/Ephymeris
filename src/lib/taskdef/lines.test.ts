/**
 * Odor lines and their declared onset codes — `TASKS.md#onset-codes`.
 */

import { describe, expect, it } from "vitest";

import type { RigDocument } from "@/lib/hardware/types";
import type { StrobeVocabulary } from "@/lib/ws/protocol";

import { declaredOnset, isRowOwnedField, lineOptions, onsetOptions } from "./lines";
import { blankTrial } from "./types";

const rig: RigDocument = {
  rig_version: 1,
  channels: {
    odor_line_1: { kind: "emitter", label: "sandalwood", onset_strobe: "ODOR_1_ON" },
    odor_line_3: { kind: "emitter", onset_strobe: "ODOR_3_ON" },
    channel_9: { kind: "emitter" },
    trial_light: { kind: "cue", onset_strobe: "ODOR_9_ON" },
  },
  pins: {},
};

const vocabulary = {
  codes: [
    { name: "ODOR_1_ON", code: 101, origin: "firmware" },
    { name: "ODOR_3_ON", code: 103, origin: "firmware" },
    { name: "ODOR_10_ON", code: 114, origin: "firmware" },
    { name: "LIGHTS_ON", code: 7, origin: "firmware" },
  ],
} as unknown as StrobeVocabulary;

describe("declaredOnset", () => {
  it("reads the rig's declaration and never derives one", () => {
    expect(declaredOnset(rig, "odor_line_1")).toBe("ODOR_1_ON");
    // A line named like a number declares nothing until the wiring says so.
    expect(declaredOnset(rig, "channel_9")).toBeNull();
    // Only an emitter announces an onset.
    expect(declaredOnset(rig, "trial_light")).toBeNull();
  });
});

describe("lineOptions", () => {
  it("lists every emitter with its code read from the vocabulary", () => {
    const options = lineOptions(rig, vocabulary, [], 0);
    expect(options.map((o) => o.value)).toEqual(["odor_line_1", "odor_line_3", "channel_9"]);
    expect(options[0]).toMatchObject({ label: "sandalwood", detail: "ODOR_1_ON · 101" });
    expect(options[2]?.detail).toBe("no onset");
  });

  it("disables a line another row already presents, and names the row", () => {
    const trials = [{ ...blankTrial(), odorChannel: "odor_line_3" }, blankTrial()];
    const forRow1 = lineOptions(rig, vocabulary, trials, 1);
    expect(forRow1.find((o) => o.value === "odor_line_3")).toMatchObject({ disabled: true, detail: "in row 1" });
    // The row that holds it may keep it.
    expect(lineOptions(rig, vocabulary, trials, 0).find((o) => o.value === "odor_line_3")?.disabled).toBe(false);
  });
});

describe("onsetOptions", () => {
  it("offers onset-shaped codes only, and marks one another line declares", () => {
    const options = onsetOptions(rig, vocabulary, "odor_line_3");
    expect(options.map((o) => o.value)).toEqual(["ODOR_1_ON", "ODOR_3_ON", "ODOR_10_ON"]);
    expect(options[0]).toMatchObject({ disabled: true, detail: "on sandalwood" });
    expect(options[1]).toMatchObject({ disabled: false, detail: "103" });
  });
});

describe("isRowOwnedField", () => {
  it("matches the fields the generator reads off a row", () => {
    expect(isRowOwnedField("pool_weight_3")).toBe(true);
    expect(isRowOwnedField("reward_time_12")).toBe(true);
    expect(isRowOwnedField("block_size")).toBe(false);
  });
});
