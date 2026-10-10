import { describe, expect, it } from "vitest";

import {
  defaultConfig,
  editedOverrides,
  withoutOverrides,
  type TaskProfile,
} from "./types";

/** A behaviour profile declaring these fields with these defaults. */
function profile(defaults: Record<string, unknown>): TaskProfile {
  return {
    taskName: "T",
    kind: "behavior",
    config: Object.entries(defaults).map(([metadataKey, value]) => ({
      metadataKey,
      wireKey: metadataKey.toUpperCase(),
      label: metadataKey,
      type: "int",
      default: value,
    })),
    strobes: {},
    liveMetrics: [],
    controls: [],
    legacyNames: [],
  } as TaskProfile;
}

describe("rebuilding a box's config from the current profile", () => {
  it("lets an untouched field follow a profile default changed mid-setup", () => {
    // The mapping step's row: the operator edited only the hold.
    let overrides: Record<string, unknown> = {};
    const before = profile({ reward_ul: 30, hold_ms: 500 });
    const shown = defaultConfig(before, {}, overrides);
    overrides = editedOverrides(overrides, shown, { ...shown, hold_ms: 800 });

    // Open Task: the reward default goes from 30 to 20, and task.json is regenerated.
    const after = profile({ reward_ul: 20, hold_ms: 500 });

    expect(defaultConfig(after, {}, overrides)).toEqual({ reward_ul: 20, hold_ms: 800 });
  });

  it("lets an untouched field follow a rig default, and keeps the operator's value over both", () => {
    const p = profile({ reward_ul: 30, hold_ms: 500 });
    expect(defaultConfig(p, { reward_ul: 25 }, {})).toEqual({ reward_ul: 25, hold_ms: 500 });
    expect(defaultConfig(p, { reward_ul: 25 }, { reward_ul: 40 })).toEqual({ reward_ul: 40, hold_ms: 500 });
  });

  it("drops an override for a field the profile no longer declares", () => {
    const p = profile({ reward_ul: 30 });
    expect(defaultConfig(p, {}, { retired_ms: 9 })).toEqual({ reward_ul: 30 });
  });
});

describe("editedOverrides", () => {
  it("records only the keys that moved, measured against what was shown", () => {
    const shown = { reward_ul: 30, hold_ms: 500 };
    expect(editedOverrides({}, shown, { reward_ul: 30, hold_ms: 800 })).toEqual({ hold_ms: 800 });
  });

  it("does not turn a stale-looking value into an override", () => {
    // The baseline is 20 now but the form still reports 30 for a field it
    // never moved: nothing was edited, so nothing is recorded.
    const shown = { reward_ul: 30 };
    expect(editedOverrides({}, shown, { reward_ul: 30 })).toEqual({});
  });

  it("keeps a value the operator typed even when it equals the value underneath", () => {
    const shown = { reward_ul: 40 };
    expect(editedOverrides({ reward_ul: 40 }, shown, { reward_ul: 30 })).toEqual({ reward_ul: 30 });
  });
});

describe("withoutOverrides", () => {
  it("drops the reset keys so those fields follow the layers underneath", () => {
    const overrides = { reward_ul: 40, hold_ms: 800 };
    expect(withoutOverrides(overrides, ["reward_ul"])).toEqual({ hold_ms: 800 });
    expect(overrides).toEqual({ reward_ul: 40, hold_ms: 800 });
  });
});
