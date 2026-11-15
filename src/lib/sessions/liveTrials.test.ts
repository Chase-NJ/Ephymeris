/**
 * The live per-trial derivation reads both stream grammars
 * (`TASKS.md#stream-grammar`): grammar 1's ITI codes close a completed trial,
 * grammar 2's END_TRIAL closes every trial and its header opens the next.
 */

import { describe, expect, it } from "vitest";

import { code, STROBES } from "@/lib/tasks/__fixtures__/vocabulary";

import { advance, EMPTY_LIVE_TRIALS, vocabFrom, vocabIsUsable } from "./liveTrials";
import type { StrobeEvent } from "./store";

const vocab = vocabFrom(STROBES);
const log = (...names: string[]): StrobeEvent[] =>
  names.map((name, i) => ({ code: String(code(name)), at: 100 * i }) as StrobeEvent);

const SAMPLED = ["LIGHTS_ON", "ODOR_POKE", "ODOR_1_ON", "ODOR_OFF", "ODOR_UNPOKE", "LIGHTS_OFF"];

describe("stream grammar 2", () => {
  it("is usable from END_TRIAL alone", () => {
    const without = vocabFrom(
      Object.fromEntries(Object.entries(STROBES).filter(([, n]) => !n.startsWith("END_") || n === "END_TRIAL")),
    );
    expect(vocabIsUsable(without)).toBe(true);
  });

  it("closes a rewarded trial on END_TRIAL with the verdict read from CORRECT", () => {
    const state = advance(
      EMPTY_LIVE_TRIALS,
      log("TRIAL_START", "TRIAL_GO_RIGHT", "TRIAL_TYPE_1", ...SAMPLED, "WATER_POKE_R", "CORRECT",
          "FLUID_R", "STOP_FLUID_G_R", "WATER_UNPOKE_R", "END_TRIAL"),
      vocab,
    );
    expect(state.trials).toHaveLength(1);
    expect(state.trials[0]).toMatchObject({ index: 1, odorCode: String(code("ODOR_1_ON")), went: "right", outcome: "earned" });
    expect(state.trials[0]?.hold).toMatchObject({ side: "right", held: true });
  });

  it("records an aborted trial as abstained, since END_TRIAL closes it too", () => {
    const state = advance(
      EMPTY_LIVE_TRIALS,
      log("TRIAL_START", "TRIAL_GO_LEFT", "TRIAL_TYPE_2", "LIGHTS_ON", "LAZY_RAT", "LIGHTS_OFF",
          "INVALID_TRIAL", "END_TRIAL"),
      vocab,
    );
    expect(state.trials).toHaveLength(1);
    expect(state.trials[0]).toMatchObject({ odorCode: null, went: null, outcome: "abstained" });
  });

  it("reads a sampling release and a no-go false alarm", () => {
    const state = advance(
      EMPTY_LIVE_TRIALS,
      log("TRIAL_START", "TRIAL_GO_RIGHT", "TRIAL_TYPE_1", "LIGHTS_ON", "ODOR_POKE", "ODOR_1_ON",
          "ODOR_UNPOKE_EARLY_SAMPLING", "LIGHTS_OFF", "INVALID_TRIAL", "END_TRIAL",
          "TRIAL_START", "TRIAL_NO_GO", "TRIAL_TYPE_3", ...SAMPLED, "WATER_POKE_L", "WATER_POKE_ERROR_L", "END_TRIAL"),
      vocab,
    );
    expect(state.trials.map((t) => t.outcome)).toEqual(["hold-fail", "wrong-well"]);
    expect(state.trials[1]?.went).toBe("left");
  });

  it("starts the next trial clean at its header, whatever a cut-off trial left", () => {
    const state = advance(
      EMPTY_LIVE_TRIALS,
      log("TRIAL_START", "TRIAL_GO_RIGHT", "TRIAL_TYPE_1", ...SAMPLED, "WATER_POKE_R",
          "TRIAL_START", "TRIAL_GO_LEFT", "TRIAL_TYPE_2", "LIGHTS_ON", "ODOR_POKE", "ODOR_3_ON",
          "ODOR_OFF", "ODOR_UNPOKE", "LIGHTS_OFF", "RESP_OMIT", "END_TRIAL"),
      vocab,
    );
    expect(state.trials).toHaveLength(1);
    expect(state.trials[0]).toMatchObject({ odorCode: String(code("ODOR_3_ON")), went: null, outcome: "abstained" });
  });
});

describe("stream grammar 1", () => {
  it("still closes a completed trial on its ITI code", () => {
    const state = advance(
      EMPTY_LIVE_TRIALS,
      log(...SAMPLED, "WATER_POKE_L", "WATER_POKE_ERROR_L", "END_INCORRECT_ITI"),
      vocab,
    );
    expect(state.trials).toHaveLength(1);
    expect(state.trials[0]).toMatchObject({ went: "left", outcome: "wrong-well" });
  });
});
