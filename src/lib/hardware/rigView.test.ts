import { describe, expect, it } from "vitest";

import { applyPreview, canReset, canSave, type RigView } from "./rigView";
import type { RigProblem, RigStatus } from "./types";

const unloaded: RigProblem = {
  location: "wiring.json",
  message: "wiring.json did not load: … The shipped pins are in force, so no box can start …",
  code: null,
};

function status(over: Partial<RigStatus> = {}): RigStatus {
  return {
    custom: false,
    derivedFrom: "behaviorbox_mega2560.v1",
    board: "Arduino Mega2560 R3",
    editedAt: null,
    pinoutHash: "bfa89f7d62bf622f",
    channelSetHash: "0000000000000000",
    notices: [unloaded],
    canReset: true,
    resetReplaces: ["/data/hardware/wiring.json"],
    canSave: false,
    needsPinConfirmation: false,
    ...over,
  };
}

const loaded: RigView = {
  status: status(),
  problems: [{ location: "pins.odor_port", message: "no pin", code: "RIG101" }],
  breaks: [],
  allocations: [],
};

describe("applyPreview", () => {
  it("replaces the draft's problems and keeps the rig's notices through an edit", () => {
    const next = applyPreview(loaded, { status: status(), problems: [], breaks: [], allocations: [] });
    expect(next.problems).toEqual([]);
    expect(next.status?.notices).toEqual([unloaded]);
  });

  it("keeps the loaded notices if a reply ever omitted its status", () => {
    const next = applyPreview(loaded, { problems: [], breaks: [], allocations: [] });
    expect(next.status?.notices).toEqual([unloaded]);
  });
});

describe("canSave", () => {
  it("renders the sidecar's answer and never works one out", () => {
    const told = (canSave: boolean): RigView => ({ ...loaded, problems: [], status: status({ canSave }) });
    expect(canSave(told(true), false)).toBe(true);
    // No problems and a notice, which once enabled Save here: the sidecar said no.
    expect(canSave(told(false), false)).toBe(false);
    expect(canSave(told(true), true)).toBe(false);
    expect(canSave({ ...loaded, status: null }, false)).toBe(false);
  });
});

describe("canReset", () => {
  it("follows the sidecar's answer, so a refusal naming Reset can always use it", () => {
    expect(canReset(status({ custom: false, canReset: true }), false)).toBe(true);
    expect(canReset(status({ canReset: false, notices: [] }), false)).toBe(false);
    expect(canReset(status(), true)).toBe(false);
    expect(canReset(null, false)).toBe(false);
  });
});
