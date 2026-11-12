import { describe, expect, it } from "vitest";

import type { ChannelSetConflict, ChannelSetImportPlan } from "@/lib/ws/protocol";

import { canImport, pinsToSend, refusals, unpinned, withPick } from "./channelSetImport";

const lever = { channel: "lever", kind: "cue", type: "digital_out", pin: null, freePins: [50, 53] };
const laser = { channel: "laser", kind: "emitter", type: "pwm_out", pin: null, freePins: [44, 45] };

function plan(over: Partial<ChannelSetImportPlan> = {}): ChannelSetImportPlan {
  return {
    conflicts: [],
    vocabulary: { adds: [], retires: [], conflicts: [] },
    changed: [],
    newChannels: [],
    breaks: [],
    hereHash: "a",
    importedHash: "b",
    fileHash: "b",
    fileHashVersion: 2,
    identical: false,
    ...over,
  } as ChannelSetImportPlan;
}

const notHere = (channel: string): ChannelSetConflict => ({
  kind: "not_here",
  channel,
  message: `${channel} is in that channel set and not on this rig. Pick a pin for it to add it here.`,
});

describe("pinsToSend", () => {
  it("sends only picks for channels the plan lists as new", () => {
    const p = plan({ newChannels: [lever, laser] });
    expect(pinsToSend(p, { lever: 53, door: 12 })).toEqual({ lever: 53 });
    expect(pinsToSend(p, {})).toEqual({});
    expect(pinsToSend(null, { lever: 53 })).toEqual({});
  });
});

describe("withPick", () => {
  it("sets and clears one channel's pick", () => {
    const picks = withPick({}, "lever", 53);
    expect(picks).toEqual({ lever: 53 });
    expect(withPick(picks, "laser", 44)).toEqual({ lever: 53, laser: 44 });
    expect(withPick(picks, "lever", null)).toEqual({});
  });
});

describe("refusals", () => {
  it("leaves a new channel's not_here to its row and lists everything else", () => {
    const rule: ChannelSetConflict = {
      kind: "rule",
      channel: "laser",
      message: "RIG109 pins.laser: 'laser' is a pwm_out on pin 53, which no timer drives",
    };
    const onlyHere: ChannelSetConflict = { kind: "only_here", channel: "door", message: "door is on this rig…" };
    const p = plan({ newChannels: [lever, laser], conflicts: [notHere("lever"), rule, onlyHere] });
    expect(refusals(p)).toEqual([rule, onlyHere]);
  });

  it("keeps a not_here the plan lists no row for", () => {
    // The sidecar's plan is the judge; a conflict with no picker is shown.
    const p = plan({ conflicts: [notHere("lever")] });
    expect(refusals(p)).toEqual([notHere("lever")]);
  });
});

describe("canImport", () => {
  it("waits until the plan pins every new channel", () => {
    const waiting = plan({ newChannels: [{ ...lever, pin: 53 }, laser], conflicts: [notHere("laser")] });
    expect(unpinned(waiting).map((c) => c.channel)).toEqual(["laser"]);
    expect(canImport(waiting, false)).toBe(false);

    const pinned = plan({ newChannels: [{ ...lever, pin: 53 }, { ...laser, pin: 44 }] });
    expect(canImport(pinned, false)).toBe(true);
  });

  it("holds while a re-plan is in flight, a conflict stands, or nothing changes", () => {
    const pinned = plan({ newChannels: [{ ...lever, pin: 53 }] });
    expect(canImport(pinned, true)).toBe(false);
    expect(canImport(plan({ conflicts: [{ kind: "hash", channel: null, message: "…" }] }), false)).toBe(false);
    expect(canImport(plan({ identical: true }), false)).toBe(false);
    expect(canImport(null, false)).toBe(false);
  });
});
