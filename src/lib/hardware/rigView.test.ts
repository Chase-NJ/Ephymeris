import { describe, expect, it } from "vitest";

import { afterSave, applyPreview, canReset, canSave, servedView, type RigView } from "./rigView";
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
    const idle = { saving: false, checking: false };
    expect(canSave(told(true), idle)).toBe(true);
    // No problems and a notice, which once enabled Save here: the sidecar said no.
    expect(canSave(told(false), idle)).toBe(false);
    expect(canSave(told(true), { saving: true, checking: false })).toBe(false);
    expect(canSave({ ...loaded, status: null }, idle)).toBe(false);
  });

  it("is held while a preview is in flight, so a click can't send a stale answer", () => {
    const told: RigView = { ...loaded, problems: [], status: status({ canSave: true }) };
    expect(canSave(told, { saving: false, checking: true })).toBe(false);
  });
});

describe("servedView", () => {
  const baseline: RigView = { ...loaded, status: status({ canSave: false }) };

  it("is the served draft's own answer when the draft is back at the baseline", () => {
    // An edit undone by hand runs no preview; the last preview's `canSave: true`
    // and empty problems must not stay up.
    expect(servedView({ dirty: false, confirmedPins: false }, baseline)).toBe(baseline);
  });

  it("leaves any draft a preview will describe to that preview", () => {
    expect(servedView({ dirty: true, confirmedPins: false }, baseline)).toBeNull();
    expect(servedView({ dirty: false, confirmedPins: true }, baseline)).toBeNull();
  });
});

describe("afterSave", () => {
  // The draft that was held behind RIG108, confirmed and saved.
  const before: RigView = {
    ...loaded,
    problems: [{ location: "pins", message: "These pins come from …", code: "RIG108" }],
    status: status({ needsPinConfirmation: true, canSave: false }),
  };
  const reply = {
    status: status({ custom: true, notices: [], needsPinConfirmation: false, canSave: false }),
    problems: [],
    breaks: [],
    allocations: [{ channel: "trial_light", edge: "on", name: "TRIAL_LIGHT_ON", code: 40 }],
  };

  it("makes the save reply the served draft's view at once, before any reload", () => {
    const next = afterSave(reply);
    // The saved draft is the served draft now, with no confirmation pending:
    // what the editor shows must be the reply, never the pre-save baseline.
    const shown = servedView({ dirty: false, confirmedPins: next.confirmedPins }, next.baseline);
    expect(shown?.status).toEqual(reply.status);
    expect(shown?.problems).toEqual([]);
    expect(shown?.status?.needsPinConfirmation).toBe(false);
    expect(next.view.status).toEqual(reply.status);
    expect(next.issued).toEqual(reply.allocations);
    expect(next.baseline).not.toEqual(before);
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
