import { describe, expect, it } from "vitest";

import {
  WALK_START,
  assignBox,
  confirmPayload,
  copyOverrides,
  isPlaced,
  mappingReadiness,
  placementOrder,
  seedRound,
  walkReducer,
  walkStop,
  type WalkAction,
  type WalkState,
} from "./placementWalk";
import type { BoxMapping, TaskProfile } from "./types";

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

function mapping(box: number, animalId: string, sketchPath: string | null = null, overrides = {}): BoxMapping {
  return { box, animalId, sketchPath, overrides };
}

/** Run actions from a state, as the step would dispatch them. */
function run(state: WalkState, ...actions: WalkAction[]): WalkState {
  return actions.reduce(walkReducer, state);
}

describe("seedRound", () => {
  const animals = [
    { id: "a1", name: "remy1", boxNumber: 1 },
    { id: "a2", name: "remy2", boxNumber: 4 },
    { id: "a3", name: "remy3", boxNumber: null },
  ];
  const nobody = new Set<string>();

  it("puts each animal on its usual box, with no sketch chosen, and leaves the rest on the bench", () => {
    expect(seedRound(animals, nobody, undefined)).toEqual([mapping(1, "a1"), mapping(4, "a2")]);
  });

  it("gives a shared usual box to the first by name and benches the other", () => {
    const sharing = [
      { id: "b", name: "remy10", boxNumber: 2 },
      { id: "a", name: "remy9", boxNumber: 2 },
    ];
    expect(seedRound(sharing, nobody, undefined)).toEqual([mapping(2, "a")]);
  });

  it("offers only the animals that have not run in this session yet", () => {
    expect(seedRound(animals, new Set(["a1"]), undefined)).toEqual([mapping(4, "a2")]);
    expect(seedRound(animals, new Set(["a1", "a2"]), undefined)).toEqual([]);
  });

  it("restores the operator's draft, a subset of the roster included", () => {
    const draft = [mapping(4, "a1", "/s/Go", { hold_ms: 800 })];
    expect(seedRound(animals, new Set(["a1"]), draft)).toBe(draft);
  });

  it("starts over when a drafted animal was removed in Cohorts meanwhile", () => {
    expect(seedRound(animals, nobody, [mapping(1, "a1", "/s/Go"), mapping(4, "a9", "/s/Go")])).toEqual([
      mapping(1, "a1"),
      mapping(4, "a2"),
    ]);
  });
});

describe("assignBox", () => {
  const round = [mapping(1, "a1", "/s/Go", { hold_ms: 800 }), mapping(2, "a2", "/s/Go")];

  it("puts a benched animal in an empty box", () => {
    expect(assignBox(round, 5, "a3")).toEqual([...round, mapping(5, "a3")]);
  });

  it("moves an animal with its sketch and edits, emptying the box it left", () => {
    expect(assignBox(round, 6, "a1")).toEqual([mapping(2, "a2", "/s/Go"), mapping(6, "a1", "/s/Go", { hold_ms: 800 })]);
  });

  it("swaps two animals when the one picked is in another box", () => {
    expect(assignBox(round, 2, "a1")).toEqual([
      mapping(1, "a2", "/s/Go"),
      mapping(2, "a1", "/s/Go", { hold_ms: 800 }),
    ]);
  });

  it("benches whoever held the box when the one picked comes off the bench", () => {
    expect(assignBox(round, 2, "a3")).toEqual([mapping(1, "a1", "/s/Go", { hold_ms: 800 }), mapping(2, "a3")]);
  });

  it("changes nothing when the animal is already there", () => {
    expect(assignBox(round, 1, "a1")).toEqual(round);
  });

  it("empties a box", () => {
    expect(assignBox(round, 1, null)).toEqual([mapping(2, "a2", "/s/Go")]);
  });
});

describe("copyOverrides", () => {
  it("gives every other box on the same sketch the same edits, and no other box", () => {
    const round = [
      mapping(1, "a1", "/s/Go", { hold_ms: 800 }),
      mapping(2, "a2", "/s/Go", { iti_ms: 5 }),
      mapping(3, "a3", "/s/Other", { hold_ms: 1 }),
      mapping(4, "a4"),
    ];
    expect(copyOverrides(round, 1)).toEqual([
      round[0],
      mapping(2, "a2", "/s/Go", { hold_ms: 800 }),
      round[2],
      round[3],
    ]);
  });

  it("changes nothing from a box with no sketch", () => {
    const round = [mapping(1, "a1"), mapping(2, "a2")];
    expect(copyOverrides(round, 1)).toEqual(round);
  });
});

describe("placementOrder", () => {
  it("walks the bench by box number, whatever order the animals are in", () => {
    const order = placementOrder([mapping(5, "a"), mapping(2, "b"), mapping(3, "c")]);
    expect(order.map((m) => m.box)).toEqual([2, 3, 5]);
  });
});

describe("mappingReadiness", () => {
  const go = profile({ hold_ms: 500 });
  const bound = new Set([1, 2, 3]);

  it("is ready once every box has a sketch whose profile has been read", () => {
    const r = mappingReadiness([mapping(1, "a", "/s/Go"), mapping(2, "b", "/s/Go")], { "/s/Go": go }, {}, bound);
    expect(r).toEqual({
      duplicateBox: null,
      allChosen: true,
      erroredBoxes: [],
      unconfiguredBoxes: [],
      ready: true,
      problem: null,
    });
  });

  it("counts a sketch with no profile as read, and waits for one still being read", () => {
    const m = [mapping(1, "a", "/s/Bare"), mapping(2, "b", "/s/Go")];
    expect(mappingReadiness(m, { "/s/Bare": null, "/s/Go": go }, {}, bound).ready).toBe(true);
    const waiting = mappingReadiness(m, { "/s/Bare": null }, {}, bound);
    expect(waiting).toMatchObject({ ready: false, problem: "Reading the chosen sketches' parameters…" });
  });

  it("asks for a sketch on every box", () => {
    const r = mappingReadiness([mapping(1, "a", "/s/Go"), mapping(2, "b")], { "/s/Go": go }, {}, bound);
    expect(r).toMatchObject({ allChosen: false, ready: false, problem: "Pick a task for every animal, then place them." });
  });

  it("asks for an animal when the round is empty", () => {
    const r = mappingReadiness([], {}, {}, new Set([1, 2]));
    expect(r).toMatchObject({ ready: false, problem: "Put an animal in a box to set up this round." });
  });

  it("refuses two animals on one box", () => {
    const r = mappingReadiness([mapping(2, "a", "/s/Go"), mapping(2, "b", "/s/Go")], { "/s/Go": go }, {}, bound);
    expect(r).toMatchObject({ duplicateBox: 2, allChosen: false, problem: "Two animals share box 2 — move one first." });
  });

  it("holds Confirm while a mapped box is in ERROR, and says that first", () => {
    const r = mappingReadiness(
      [mapping(1, "a", "/s/Go"), mapping(3, "b")],
      { "/s/Go": go },
      { 3: { state: "ERROR" }, 1: { state: "IDLE" } },
      bound,
    );
    expect(r).toMatchObject({ erroredBoxes: [3], ready: false, problem: "Box 3 needs acknowledging before it can flash." });
  });

  it("names mapped boxes with no board, without refusing them", () => {
    const r = mappingReadiness([mapping(6, "a", "/s/Go"), mapping(4, "b", "/s/Go")], { "/s/Go": go }, {}, bound);
    expect(r).toMatchObject({ unconfiguredBoxes: [4, 6], ready: true });
  });
});

describe("confirmPayload", () => {
  it("merges each box's config from the profile now, the rig's defaults and the operator's edits", () => {
    const profiles = { "C:\\sketches\\Go": profile({ reward_ul: 30, hold_ms: 500, iti_ms: 2000 }), "/s/Bare": null };
    const sent = confirmPayload(
      [mapping(1, "a1", "C:\\sketches\\Go", { hold_ms: 800 }), mapping(2, "a2", "/s/Bare", { stale: 1 })],
      profiles,
      { Go: { reward_ul: 25, retired_key: 9 } },
    );
    expect(sent).toEqual([
      { box: 1, animalId: "a1", sketchPath: "C:\\sketches\\Go", config: { reward_ul: 25, hold_ms: 800, iti_ms: 2000 } },
      { box: 2, animalId: "a2", sketchPath: "/s/Bare", config: {} },
    ]);
  });
});

describe("walkReducer", () => {
  const order = [mapping(2, "b"), mapping(3, "c"), mapping(5, "a")];
  const count = order.length;

  it("starts the walk at the first box on confirm", () => {
    const s = run(WALK_START, { type: "confirmed", skipWalk: false, count });
    expect(s).toEqual({ phase: "placing", index: 0, resumed: true });
    expect(walkStop(s, order)?.box).toBe(2);
  });

  it("skips the walk with every box placed for They're already in", () => {
    const s = run(WALK_START, { type: "confirmed", skipWalk: true, count });
    expect(s.phase).toBe("placed");
    expect(walkStop(s, order)).toBeNull();
    expect(order.every((m) => isPlaced(s, order, m.animalId))).toBe(true);
  });

  it("walks the bench box by box, and is placed after the last", () => {
    let s = run(WALK_START, { type: "confirmed", skipWalk: false, count }, { type: "advance", count });
    expect(walkStop(s, order)?.box).toBe(3);
    expect(isPlaced(s, order, "b")).toBe(true);
    expect(isPlaced(s, order, "c")).toBe(false);
    s = run(s, { type: "advance", count }, { type: "advance", count });
    expect(s.phase).toBe("placed");
    expect(walkStop(s, order)).toBeNull();
  });

  it("places every remaining box at once", () => {
    const s = run(WALK_START, { type: "confirmed", skipWalk: false, count }, { type: "advance", count }, {
      type: "placeAll",
      count,
    });
    expect(s).toEqual({ phase: "placed", index: count, resumed: true });
  });

  it("steps back one box, and from the first back to the review for good", () => {
    let s = run(WALK_START, { type: "confirmed", skipWalk: false, count }, { type: "advance", count }, { type: "retreat" });
    expect(s).toEqual({ phase: "placing", index: 0, resumed: true });
    s = run(s, { type: "retreat" });
    expect(s).toEqual({ phase: "review", index: 0, resumed: true });
    // A walk deliberately left is not picked up again from the flash queue.
    expect(run(s, { type: "resume", at: 1, count })).toBe(s);
  });

  it("walks again from the first box without re-confirming", () => {
    const s = run(WALK_START, { type: "confirmed", skipWalk: true, count }, { type: "walkAgain" });
    expect(s).toEqual({ phase: "placing", index: 0, resumed: true });
  });

  it("resumes a walk left mid-way at the box the flash queue names, once per visit", () => {
    const s = run(WALK_START, { type: "resume", at: 1, count });
    expect(s).toEqual({ phase: "placing", index: 1, resumed: true });
    expect(walkStop(s, order)?.box).toBe(3);
    expect(run(s, { type: "retreat" }, { type: "resume", at: 2, count })).toEqual({
      phase: "placing",
      index: 0,
      resumed: true,
    });
  });

  it("resumes past the last box as placed, while a flash is still running", () => {
    expect(run(WALK_START, { type: "resume", at: count, count })).toEqual({ phase: "placed", index: count, resumed: true });
  });

  it("stays in the review when there is nothing to resume", () => {
    expect(run(WALK_START, { type: "resume", at: null, count })).toBe(WALK_START);
    expect(run(WALK_START, { type: "resume", at: 0, count: 0 })).toBe(WALK_START);
  });

  it("does not resume over a walk this visit already confirmed", () => {
    const s = run(WALK_START, { type: "confirmed", skipWalk: false, count }, { type: "retreat" });
    expect(run(s, { type: "resume", at: 2, count })).toBe(s);
  });

  it("ignores walk steps outside the walk", () => {
    expect(run(WALK_START, { type: "advance", count })).toBe(WALK_START);
    expect(run(WALK_START, { type: "placeAll", count })).toBe(WALK_START);
    expect(run(WALK_START, { type: "retreat" })).toBe(WALK_START);
  });
});
