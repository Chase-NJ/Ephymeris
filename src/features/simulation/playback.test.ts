/**
 * Reading a simulated session at its playhead — `TASKS.md#playing-a-simulation-back`.
 *
 * The view draws only what these return, so a wrong cut is a token on the wrong
 * state or a reward counted early, with nothing thrown.
 */

import { describe, expect, it } from "vitest";

import { code, STROBES } from "@/features/tasks/__fixtures__/vocabulary";
import { taskGraph } from "@/features/tasks/topology";
import type { SimulationTelemetry, TaskProfile, TrialTable } from "@/lib/ws/protocol";

import { PRESETS, presetOf, TRAINED, TRAINED_PRESET, withSetting } from "./animals";
import {
  clockLabel,
  flowOf,
  liveAt,
  OUTCOME_SETTLE_MS,
  readStrobes,
  shownCount,
  stageStarts,
  stepTrial,
  telemetryAt,
  trialAt,
  trialTicks,
  waterBy,
  type Strobe,
} from "./playback";

const PROFILE = {
  taskName: "Two odors",
  kind: "behavior",
  config: [],
  strobes: STROBES,
  liveMetrics: [1, 2].map((n) => ({
    id: `p_correct_${n}`,
    label: `P(correct | odor ${n})`,
    triggerCode: code(`ODOR_${n}_ON`),
    successCode: code(n === 1 ? "WATER_POKE_R" : "WATER_POKE_L"),
    alternateCode: code(n === 1 ? "WATER_POKE_L" : "WATER_POKE_R"),
    windowSize: 20,
  })),
  controls: [],
  legacyNames: [],
} as unknown as TaskProfile;

const MODEL = taskGraph(PROFILE);

/** `["LIGHTS_ON", 1000]` pairs as the board would have sent them. */
function session(...sent: Array<[name: string, at: number]>): Strobe[] {
  return readStrobes(sent.map(([name, at]) => [code(name), at]));
}

const TWO_TRIALS = session(
  ["LIGHTS_ON", 1000],
  ["ODOR_POKE", 1500],
  ["ODOR_1_ON", 2000],
  ["ODOR_OFF", 2500],
  ["ODOR_UNPOKE", 2700],
  ["LIGHTS_OFF", 2700],
  ["WATER_POKE_R", 3100],
  ["FLUID_R", 3300],
  ["LIGHTS_ON", 9000],
  ["LAZY_RAT", 13000],
  ["LIGHTS_OFF", 13000],
);

describe("shownCount", () => {
  it("counts a strobe from its own millisecond on", () => {
    expect(shownCount(TWO_TRIALS, 0)).toBe(0);
    expect(shownCount(TWO_TRIALS, 999)).toBe(0);
    expect(shownCount(TWO_TRIALS, 1000)).toBe(1);
    expect(shownCount(TWO_TRIALS, 2700)).toBe(6);
    expect(shownCount(TWO_TRIALS, 1e9)).toBe(TWO_TRIALS.length);
  });
});

describe("liveAt", () => {
  const at = (ms: number) => liveAt(MODEL, STROBES, TWO_TRIALS, shownCount(TWO_TRIALS, ms), ms);

  it("has no token before the first strobe", () => {
    expect(at(500)).toEqual({ node: null, condition: null });
  });

  it("puts the token where a running box's panel would", () => {
    const light = at(1200).node;
    const odor = at(2100).node;
    expect(light).not.toBeNull();
    expect(odor).not.toBeNull();
    expect(odor).not.toBe(light);
    expect(at(1200).node).toBe(light);
  });

  it("moves a silent outcome to the ITI once it has stood for the settle time", () => {
    const wrong = session(["LIGHTS_ON", 1000], ["LIGHTS_OFF", 2700], ["WATER_POKE_L", 3100], ["WATER_POKE_ERROR_L", 3100]);
    const node = (ms: number) => liveAt(MODEL, STROBES, wrong, shownCount(wrong, ms), ms).node;
    expect(node(3100)).toBe("wrong-well");
    expect(node(3100 + OUTCOME_SETTLE_MS - 1)).toBe("wrong-well");
    expect(node(3100 + OUTCOME_SETTLE_MS)).toBe("iti");
  });

  it("leaves a reward where it is: the animal leaving the well is what moves it on", () => {
    expect(at(3300).node).toBe("reward");
    expect(at(3300 + OUTCOME_SETTLE_MS).node).toBe("reward");
  });

  it("reads the same going backwards as forwards", () => {
    const forwards = [1200, 2100, 3300, 9500].map((ms) => at(ms).node);
    const backwards = [9500, 3300, 2100, 1200].map((ms) => at(ms).node).reverse();
    expect(backwards).toEqual(forwards);
  });
});

describe("telemetryAt", () => {
  const moved = [
    { strobe: 2, metrics: [{ id: "a", value: null, n: 0, triggered: 1, counted: 0, hits: 0 }] },
    { strobe: 6, metrics: [{ id: "a", value: 1, n: 1, triggered: 1, counted: 1, hits: 1 }] },
  ] as SimulationTelemetry[];

  it("is empty until the first strobe that moved a metric has been sent", () => {
    expect(telemetryAt(moved, 2)).toEqual([]);
    expect(telemetryAt(moved, 3)).toBe(moved[0]!.metrics);
  });

  it("holds the last values until the next strobe that moves them", () => {
    expect(telemetryAt(moved, 6)).toBe(moved[0]!.metrics);
    expect(telemetryAt(moved, 7)).toBe(moved[1]!.metrics);
    expect(telemetryAt(moved, 99)).toBe(moved[1]!.metrics);
  });
});

describe("flowOf", () => {
  const framed = session(
    ["TRIAL_START", 0],
    ["LIGHTS_ON", 1000],
    ["ODOR_POKE", 1500],
    ["FLUID_R", 3300],
    ["TRIAL_START", 8000],
    ["LIGHTS_ON", 9000],
    ["LAZY_RAT", 13000],
  );

  it("gives each node the share of trials that reached it", () => {
    const flow = flowOf(MODEL, STROBES, framed, framed.length);
    expect(flow.trials).toBe(2);
    expect(flow.shares.get("reward")).toBe(0.5);
    expect(flow.shares.get("lazy")).toBe(0.5);
    const everyTrial = [...flow.shares.values()].filter((share) => share === 1);
    expect(everyTrial.length).toBeGreaterThan(0);
  });

  it("counts only what has been sent", () => {
    const flow = flowOf(MODEL, STROBES, framed, 4);
    expect(flow.trials).toBe(1);
    expect(flow.shares.get("reward")).toBe(1);
    expect(flow.shares.has("lazy")).toBe(false);
  });

  it("has no shares before a trial opens", () => {
    expect(flowOf(MODEL, STROBES, framed, 0)).toEqual({ trials: 0, shares: new Map() });
  });
});

function table(...trials: Array<{ atMs: number; outcome: string | null; rewardMs?: number }>): TrialTable {
  return {
    kind: "grammar2",
    phases: [],
    gaps: [],
    trials: trials.map((trial, index) => ({
      index,
      atMs: trial.atMs,
      outcome: trial.outcome,
      rewarded: trial.rewardMs !== undefined,
      rewardMs: trial.rewardMs ?? null,
    })),
  } as unknown as TrialTable;
}

describe("the timeline", () => {
  const ticks = trialTicks(
    table(
      { atMs: 0, outcome: "correct", rewardMs: 100 },
      { atMs: 8000, outcome: "wrong_response" },
      { atMs: 30000, outcome: null },
      { atMs: 40000, outcome: "withheld" },
      { atMs: 50000, outcome: "hold_broken" },
      { atMs: 60000, outcome: "correct", rewardMs: 150 },
    ),
    70000,
  );

  it("gives a trial the time until the next begins, and the last the session's end", () => {
    expect(ticks.map((tick) => tick.endMs)).toEqual([8000, 30000, 40000, 50000, 60000, 70000]);
  });

  it("colours a trial by how it ended, and one with no outcome as an abort", () => {
    expect(ticks.map((tick) => tick.tone)).toEqual(["earned", "wrong", "abort", "earned", "hold", "earned"]);
  });

  it("is empty for a session with no trial table", () => {
    expect(trialTicks(null, 1000)).toEqual([]);
  });

  it("finds the trial the playhead is in", () => {
    expect(trialAt([], 5)).toBe(-1);
    expect(trialAt(ticks, 0)).toBe(0);
    expect(trialAt(ticks, 7999)).toBe(0);
    expect(trialAt(ticks, 8000)).toBe(1);
    expect(trialAt(ticks, 1e9)).toBe(5);
  });

  it("steps forward to the next trial's start, and past the last to the end", () => {
    expect(stepTrial(ticks, 100, 1, 70000)).toBe(8000);
    expect(stepTrial(ticks, 65000, 1, 70000)).toBe(70000);
  });

  it("steps back to this trial's start, or the one before when it has only just begun", () => {
    expect(stepTrial(ticks, 20000, -1, 70000)).toBe(8000);
    expect(stepTrial(ticks, 8100, -1, 70000)).toBe(0);
    expect(stepTrial(ticks, 100, -1, 70000)).toBe(0);
  });

  it("counts a reward once its trial is over", () => {
    expect(waterBy(ticks, 7999)).toEqual({ rewards: 0, ms: 0 });
    expect(waterBy(ticks, 8000)).toEqual({ rewards: 1, ms: 100 });
    expect(waterBy(ticks, 70000)).toEqual({ rewards: 2, ms: 250 });
  });
});

describe("stageStarts", () => {
  const ramp = session(
    ["TRIAL_START", 0],
    ["END_TRIAL", 5000],
    ["TRIAL_START", 5000],
    ["INVALID_TRIAL", 9000],
    ["END_TRIAL", 9000],
    ["TRIAL_START", 9000],
    ["END_TRIAL", 14000],
    ["TRIAL_START", 14000],
    ["END_TRIAL", 20000],
  );

  it("marks the completed trial that reached each later row's count, repeats not counted", () => {
    expect(stageStarts(ramp, STROBES, [0, 2, 3])).toEqual([
      { stage: 1, atMs: 14000 },
      { stage: 2, atMs: 20000 },
    ]);
  });

  it("marks nothing for a task with no ramp", () => {
    expect(stageStarts(ramp, STROBES, [0])).toEqual([]);
  });
});

describe("clockLabel", () => {
  it("reads minutes and seconds, and hours once there are any", () => {
    expect(clockLabel(0)).toBe("0:00");
    expect(clockLabel(754_000)).toBe("12:34");
    expect(clockLabel(3_754_999)).toBe("1:02:34");
  });
});

describe("the animals", () => {
  it("offers presets that are each a whole, distinct animal", () => {
    expect(TRAINED_PRESET.animal).toEqual(TRAINED);
    for (const preset of PRESETS) expect(presetOf(preset.animal)).toBe(preset);
    expect(new Set(PRESETS.map((p) => p.label)).size).toBe(PRESETS.length);
  });

  it("flags as exploits only the animals that never use the odor", () => {
    for (const preset of PRESETS) expect(preset.exploit).toBe(preset.animal.followsOdorEnd === 0);
  });

  it("keeps an animal that is not learning at one accuracy", () => {
    const sharper = withSetting(TRAINED, "followsOdorEnd", 0.6);
    expect(sharper.followsOdor).toBe(0.6);
    expect(presetOf(sharper)).toBeNull();
  });

  it("starts a learner from chance, and leaves its start alone after that", () => {
    const learner = withSetting(TRAINED, "learningTrials", 100);
    expect(learner.followsOdor).toBe(0);
    expect(withSetting(learner, "followsOdorEnd", 0.7).followsOdor).toBe(0);
    expect(withSetting(learner, "learningTrials", 0).followsOdor).toBe(0.9);
  });
});
