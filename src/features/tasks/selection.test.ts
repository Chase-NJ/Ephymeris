/**
 * The selection modes in words — `TASKS.md#selection-modes`. These pin the
 * hand mirror of the firmware: what each mode reads, and the shares it deals.
 */

import { describe, expect, it } from "vitest";

import { compositionOf, groupUnused, inactiveNote, presentsNoGo, readsWeights } from "./selection";
import { blankTrial, type TrialTypeDef } from "./types";

const row = (patch: Partial<TrialTypeDef>): TrialTypeDef => ({ ...blankTrial(), ...patch });

const table = [
  row({ responseChannel: "left_well", weight: 3 }),
  row({ responseChannel: "left_well", weight: 1 }),
  row({ responseChannel: "right_well", weight: 2 }),
  row({ isGo: false, responseChannel: null, rewardChannel: null, weight: 2 }),
];

describe("what each mode reads", () => {
  it("knows only the pool presents a no-go and only anti-bias ignores weights", () => {
    expect(presentsNoGo("pool")).toBe(true);
    expect(presentsNoGo("antibias")).toBe(false);
    expect(readsWeights("antibias")).toBe(false);
    expect(readsWeights("weighted")).toBe(true);
  });

  it("folds away a group the mode never reads", () => {
    expect(groupUnused("pool", "Anti-bias selection")).toBe(true);
    expect(groupUnused("pool", "Correction trials")).toBe(true);
    expect(groupUnused("pool", "Trial pool")).toBe(false);
    expect(groupUnused("antibias", "Trial pool")).toBe(true);
    expect(groupUnused("weighted", "Anti-bias selection")).toBe(false);
  });

  it("dims what the pool never consults, and the block size outside it", () => {
    expect(inactiveNote("pool", { metadataKey: "bias_window", group: "Anti-bias selection" })).toBe(
      "not used in pool",
    );
    expect(inactiveNote("pool", { metadataKey: "correction_left", group: "Correction trials" })).toBe(
      "not used in pool",
    );
    expect(inactiveNote("pool", { metadataKey: "lazy_escalation", group: "Abstention penalty" })).toBe(
      "pool never escalates",
    );
    // The flat penalty still applies under the pool.
    expect(inactiveNote("pool", { metadataKey: "lazy_rat_delay", group: "Abstention penalty" })).toBeNull();
    expect(inactiveNote("antibias", { metadataKey: "block_size", group: "Trial pool" })).toBe(
      "not used in anti-bias",
    );
    expect(inactiveNote("pool", { metadataKey: "block_size", group: "Trial pool" })).toBeNull();
    expect(inactiveNote("weighted", { metadataKey: "nogo_well_poll", group: "Trial timing" })).toBe(
      "only pool presents no-go",
    );
  });
});

describe("compositionOf", () => {
  it("splits the session between the sides, uniformly within one under anti-bias", () => {
    const shares = compositionOf(table, "antibias");
    expect(shares.map((s) => s.share)).toEqual([0.25, 0.25, 0.5, 0]);
    expect(shares[3]?.presented).toBe(false);
  });

  it("weighs within a side, never across them, under weighted", () => {
    const shares = compositionOf(table, "weighted");
    expect(shares.map((s) => s.share)).toEqual([0.375, 0.125, 0.5, 0]);
  });

  it("deals the whole session by weight under the pool, no-go included", () => {
    const shares = compositionOf(table, "pool");
    expect(shares.map((s) => s.share)).toEqual([3 / 8, 1 / 8, 2 / 8, 2 / 8]);
    expect(shares.every((s) => s.presented)).toBe(true);
  });

  it("falls back to uniform where the firmware does", () => {
    const zeroed = table.map((t) => ({ ...t, weight: 0 }));
    expect(compositionOf(zeroed, "pool").map((s) => s.share)).toEqual([0.25, 0.25, 0.25, 0.25]);
    expect(compositionOf(zeroed, "weighted").map((s) => s.share)).toEqual([0.25, 0.25, 0.5, 0]);
  });
});
