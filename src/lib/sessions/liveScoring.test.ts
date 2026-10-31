import { describe, expect, it } from "vitest";

import { liveScoring } from "./liveScoring";
import type { TaskProfile } from "./types";

function profile(extra: Partial<TaskProfile> = {}): TaskProfile {
  return {
    taskName: "T",
    kind: "behavior",
    config: [],
    strobes: { "221": "START_SESSION", "101": "ODOR_1_ON" },
    liveMetrics: [],
    controls: [],
    legacyNames: [],
    ...extra,
  } as TaskProfile;
}

const metric = {
  id: "p_correct_1",
  label: "P(right well | Odor 1)",
  triggerCode: 101,
  successCode: 249,
  alternateCode: 248,
  alternateCodes: [248],
  windowSize: 20,
};

describe("what a box's live readouts can show, from its profile", () => {
  it("says a spine task is not scored live yet, rather than leaving the panel blank", () => {
    const spine = liveScoring(profile({ spine: { interp: 2 } }));
    expect(spine.scored).toBe(false);
    expect(spine.note).toMatch(/spine tasks/i);
    expect(spine.note).toMatch(/not available yet/i);
    expect(spine.note).toMatch(/recorded/i);
  });

  it("scores a profile that declares live metrics, waiting for its first trials", () => {
    const grgl = liveScoring(profile({ liveMetrics: [metric] }));
    expect(grgl.scored).toBe(true);
    expect(grgl.note).toMatch(/once trials start counting/);
  });

  it("follows the profile, not the task: a spine profile that declares metrics is scored", () => {
    expect(liveScoring(profile({ spine: { interp: 2 }, liveMetrics: [metric] })).scored).toBe(true);
  });

  it("keeps today's readout for a sketch with no profile, or one still loading", () => {
    expect(liveScoring(null).scored).toBe(true);
    expect(liveScoring(undefined).note).toMatch(/once trials start counting/);
  });
});
