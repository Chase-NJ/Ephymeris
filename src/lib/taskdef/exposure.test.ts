/**
 * Exposed parameters (`TASKS.md#parameters`): what the picker lists, what the
 * panel shows, and what the Start dialog offers, all from one list.
 */

import { describe, expect, it } from "vitest";

import type { ConfigField, TaskProfile } from "@/lib/ws/protocol";

import {
  expose,
  exposedFields,
  exposedGroups,
  hideAndReset,
  offeredKeys,
  pickerGroups,
  showValue,
} from "./exposure";

function field(key: string, group: string, extra: Partial<ConfigField> = {}, unitless = false): ConfigField {
  const out: ConfigField = { metadataKey: key, wireKey: key.toUpperCase(), label: key.replace(/_/g, " "),
                             type: "int", default: 100, group, ...extra };
  if (!unitless) out.unit = "ms";
  return out;
}

const PROFILE: TaskProfile = {
  taskName: "t",
  kind: "behavior",
  strobes: {},
  liveMetrics: [],
  controls: [],
  legacyNames: [],
  exposed: ["error_delay"],
  config: [
    field("num_trials", "Session", { unit: "trials" }),
    field("block_size", "Trial pool"),
    field("error_delay", "Trial timing"),
    field("standard_iti", "Trial timing"),
    field("lazy_escalation", "Abstention penalty", { type: "bool", default: true }, true),
    field("reward_time_1", "Reward volume"),
    field("pool_weight_1", "Trial pool"),
  ],
};

describe("exposure", () => {
  it("lists every tunable field but the row-owned ones, grouped in trial order", () => {
    const groups = pickerGroups(PROFILE, [], {}, {});
    expect(groups.map((g) => g.group)).toEqual(["Session", "Trial pool", "Trial timing", "Abstention penalty"]);
    expect(groups.flatMap((g) => g.entries.map((e) => e.field.metadataKey))).not.toContain("reward_time_1");
    expect(groups.flatMap((g) => g.entries.map((e) => e.field.metadataKey))).not.toContain("pool_weight_1");
  });

  it("narrows by label, key, group or unit, case-insensitively", () => {
    const keys = (q: string) => pickerGroups(PROFILE, [], {}, {}, q).flatMap((g) => g.entries.map((e) => e.field.metadataKey));
    expect(keys("ITI")).toEqual(["standard_iti"]);
    expect(keys("timing")).toEqual(["error_delay", "standard_iti"]);
    expect(keys("trials")).toEqual(["num_trials"]);
    expect(keys("no such thing")).toEqual([]);
  });

  it("says which rows are exposed and which pin a value", () => {
    const [session] = pickerGroups(PROFILE, ["num_trials"], { num_trials: 200 }, { num_trials: 100 });
    expect(session?.entries[0]).toMatchObject({ exposed: true, value: 200, defaultValue: 100, pinned: true });
    const [, , timing] = pickerGroups(PROFILE, ["num_trials"], {}, {});
    expect(timing?.entries.map((e) => e.exposed)).toEqual([false, false]);
  });

  it("exposes in profile order and drops keys the profile no longer declares", () => {
    expect(expose(PROFILE, ["standard_iti"], "num_trials")).toEqual(["num_trials", "standard_iti"]);
    expect(expose(PROFILE, ["num_trials"], "num_trials")).toEqual(["num_trials"]);
    expect(exposedFields(PROFILE, ["gone", "error_delay"]).map((f) => f.metadataKey)).toEqual(["error_delay"]);
    expect(exposedGroups(PROFILE, ["lazy_escalation", "num_trials"])).toEqual(["Session", "Abstention penalty"]);
  });

  it("hides and resets in one move, dropping the override rather than writing the default", () => {
    const out = hideAndReset(["num_trials", "error_delay"], { num_trials: 200, error_delay: 5 }, "num_trials");
    expect(out.exposed).toEqual(["error_delay"]);
    expect(out.config).toEqual({ error_delay: 5 });
  });

  it("offers the Start dialog the exposed keys, or everything for a profile that declares none", () => {
    expect([...(offeredKeys(PROFILE) ?? [])]).toEqual(["error_delay"]);
    const { exposed: _dropped, ...handWritten } = PROFILE;
    expect(offeredKeys(handWritten as TaskProfile)).toBeNull();
  });

  it("shows a value with its unit and a flag as on or off", () => {
    expect(showValue(field("x", "g"), 250)).toBe("250 ms");
    expect(showValue(field("x", "g", { type: "bool" }, true), true)).toBe("on");
    expect(showValue(field("x", "g"), undefined)).toBe("—");
  });
});
