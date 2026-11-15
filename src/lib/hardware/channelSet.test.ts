import { describe, expect, it } from "vitest";

import { edgesOf, patchChannel, servePort } from "./channelSet";
import type { RigChannel } from "./types";

const port: RigChannel = {
  kind: "engagement",
  type: "digital_in",
  role: "port",
  active_level: "low",
  debounce_ms: 0,
  edges: { enter: "ODOR_PORT_ENTER", exit: "ODOR_PORT_EXIT" },
};

describe("edgesOf", () => {
  it("names the edges a type has, in their allocation order", () => {
    expect(edgesOf("digital_in")).toEqual(["enter", "exit"]);
    expect(edgesOf("digital_out")).toEqual(["on", "off"]);
    expect(edgesOf(undefined)).toEqual([]);
  });

  it("gives a train its start and end, and PWM and tone lines on and off", () => {
    expect(edgesOf("digital_out", "train")).toEqual(["train_on", "train_off"]);
    expect(edgesOf("digital_out", "level")).toEqual(["on", "off"]);
    expect(edgesOf("pwm_out")).toEqual(["on", "off"]);
    expect(edgesOf("tone_out")).toEqual(["on", "off"]);
  });
});

describe("patchChannel and driven outputs", () => {
  const cue: RigChannel = {
    kind: "cue",
    type: "digital_out",
    role: "stimulus",
    edges: { on: "LASER_ON", off: "LASER_OFF" },
  };

  it("drops the codes when a line becomes a train: train_on is a different event", () => {
    const next = patchChannel(cue, { mode: "train" });
    expect(next.mode).toBe("train");
    expect(next.edges).toBeUndefined();
  });

  it("keeps the codes of a line stored as mode level through any other edit", () => {
    const stored: RigChannel = { ...cue, mode: "level" };
    const next = patchChannel(stored, { role: "cue" });
    expect(next.edges).toEqual(cue.edges);
    expect("mode" in next).toBe(false);
    expect(patchChannel(stored, { mode: "level" }).edges).toEqual(cue.edges);
  });

  it("stores a level line with no mode, and drops a mode with the type", () => {
    expect("mode" in patchChannel({ ...cue, mode: "train" }, { mode: "level" })).toBe(false);
    expect("mode" in patchChannel({ ...cue, mode: "train" }, { type: "pwm_out" })).toBe(false);
  });
});

describe("patchChannel", () => {
  it("keeps a channel's codes through an edit that changes no type", () => {
    const next = patchChannel(port, { role: "cue", debounce_ms: 4 });
    expect(next.edges).toEqual(port.edges);
    expect(next.role).toBe("cue");
  });

  it("drops codes and input-only fields when an input becomes an output", () => {
    const next = patchChannel(port, { type: "digital_out" });
    expect(next.edges).toBeUndefined();
    expect(next.active_level).toBeUndefined();
    expect(next.debounce_ms).toBeUndefined();
  });

  it("gives a new input a level and a debounce", () => {
    const out: RigChannel = { kind: "emitter", type: "digital_out", role: "stimulus" };
    const next = patchChannel(out, { type: "digital_in" });
    expect(next).toMatchObject({ active_level: "low", debounce_ms: 0 });
  });

  it("moves type and role with the kind, so the two never contradict", () => {
    const next = patchChannel(port, { kind: "reward" });
    expect(next).toMatchObject({ type: "digital_out", role: "reward" });
    expect(next.edges).toBeUndefined();
  });

  it("never touches codes on a kind change within one direction", () => {
    const next = patchChannel(port, { kind: "response" });
    expect(next.edges).toEqual(port.edges);
  });
});

describe("servePort", () => {
  it("sets a reward line's well and serves together, and clears both", () => {
    const line: RigChannel = { kind: "reward", type: "digital_out", role: "reward" };
    expect(servePort(line, "left_well")).toMatchObject({ well: "left_well", serves: "left_well" });
    const cleared = servePort({ ...line, well: "x", serves: "x" }, "");
    expect("well" in cleared || "serves" in cleared).toBe(false);
  });
});
