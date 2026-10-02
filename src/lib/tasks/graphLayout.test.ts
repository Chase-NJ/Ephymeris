/**
 * Where the nodes land — `TASKS.md#layout`.
 *
 * The defect these exist to prevent shipped for months and was invisible in
 * review: the abort band sat at constant rows while the condition fan grew from
 * a constant gap, and the two numbers were hand-fitted to a two-odor task. That
 * fit left **two pixels** of clearance at N=2 and overlapping text at N=4. No
 * exception, no missing glyph — just a drawing that looked deliberate.
 *
 * So the assertions here are about CLEARANCE, expressed against `measureNode`
 * rather than against remembered pixel values: whatever a node occupies, the
 * band must sit below it, at every condition count, in both hosts, and on the
 * fallback path that no shipped profile can reach.
 */

import { describe, expect, it } from "vitest";

import type { TaskProfile } from "@/lib/ws/protocol";

import {
  BAND_GAP,
  LIVE_GEOMETRY,
  VIEWER_GEOMETRY,
  frameFor,
  measureNode,
  type Geometry,
} from "./graphLayout";
import { taskGraph, type TaskNode } from "./topology";

const STROBES: Record<string, string> = {
  "220": "LIGHTS_ON",
  "221": "LAZY_RAT",
  "222": "ODOR_POKE",
  "223": "ODOR_UNPOKE_EARLY",
  "224": "ODOR_UNPOKE",
  "225": "LIGHTS_OFF",
  "226": "INVALID_TRIAL",
  "227": "END_CORRECT_ITI",
  "228": "END_INCORRECT_ITI",
  "244": "WATER_POKE_NONE",
  "246": "END_SESSION",
  "248": "WATER_POKE_L",
  "249": "WATER_POKE_R",
  "250": "WATER_POKE_ERROR_L",
  "251": "WATER_POKE_ERROR_R",
  "252": "WATER_UNPOKE_EARLY_L",
  "253": "WATER_UNPOKE_EARLY_R",
  "254": "FLUID_L",
  "255": "FLUID_R",
  "101": "ODOR_1_ON",
  "102": "ODOR_2_ON",
  "103": "ODOR_3_ON",
  "104": "ODOR_4_ON",
  "105": "ODOR_5_ON",
  "106": "ODOR_6_ON",
};

function profile(n: number, { noGo = false } = {}): TaskProfile {
  const onsets = [101, 102, 103, 104, 105, 106];
  return {
    taskName: `GRGL ${n}-Odor`,
    kind: "behavior",
    config: [],
    strobes: STROBES,
    liveMetrics: onsets.slice(0, n).map((code, i) => ({
      id: `p_correct_${i + 1}`,
      label: `P(x | odor ${i + 1})`,
      triggerCode: code,
      successCode: noGo && i === n - 1 ? 244 : i % 2 ? 248 : 249,
      alternateCode: i % 2 ? 249 : 248,
      windowSize: 20,
    })),
    controls: [],
    legacyNames: [],
  } as unknown as TaskProfile;
}

/** The viewer's real worst case: every chip the widest node carries. */
const FOUR_CHIPS = () => 4;
const NO_CHIPS = () => 0;

const WIDTH = 980;

/** Lowest pixel any node that is NOT in the abort band reaches. */
function deepestAboveBand(
  model: { nodes: TaskNode[] },
  frame: ReturnType<typeof frameFor>,
  chipsOf: (node: TaskNode) => number,
): number {
  return model.nodes
    .filter((node) => node.lane !== "floor")
    .reduce((low, node) => Math.max(low, frame.y(node) + measureNode(node, chipsOf(node)).down), 0);
}

/** Topmost pixel of the abort band. */
function bandTop(
  model: { nodes: TaskNode[] },
  frame: ReturnType<typeof frameFor>,
): number {
  const floor = model.nodes.filter((node) => node.lane === "floor");
  return Math.min(...floor.map((node) => frame.y(node)));
}

// --- what a node occupies ---------------------------------------------------

describe("measureNode", () => {
  const plain: TaskNode = {
    id: "x",
    label: "Poke",
    kind: "state",
    column: 24,
    row: 0,
    governedBy: [],
    entryNames: [],
  };

  it("grows with the chips the host will actually draw", () => {
    const bare = measureNode(plain, 0).down;
    const chipped = measureNode(plain, 4).down;
    expect(chipped).toBeGreaterThan(bare);
    // The gap between them is the whole reason this cannot live in
    // `topology.ts`: the live panel draws zero chips and the viewer draws four,
    // so a model-side measurement is wrong for one of the two hosts by this
    // much.
    expect(chipped - bare).toBeGreaterThan(40);
  });

  it("budgets room for the tick strip, so the label clears it", () => {
    const collapsed: TaskNode = { ...plain, multiplicity: 4 };
    expect(measureNode(collapsed, 0).down).toBeGreaterThan(measureNode(plain, 0).down);
  });

  it("does not budget a strip for a node standing only for itself", () => {
    expect(measureNode({ ...plain, multiplicity: 1 }, 0)).toEqual(measureNode(plain, 0));
  });

  it("makes a right-anchored node shorter — which is why five outcomes stack", () => {
    const right: TaskNode = { ...plain, labelAnchor: "right" };
    expect(measureNode(right, 0).down).toBeLessThan(measureNode(plain, 0).down);
  });
});

// --- the derived band -------------------------------------------------------

describe("the abort band", () => {
  const hosts: Array<[string, Geometry, (node: TaskNode) => number]> = [
    ["viewer", VIEWER_GEOMETRY, FOUR_CHIPS],
    ["live", LIVE_GEOMETRY, NO_CHIPS],
  ];

  for (const [host, geometry, chipsOf] of hosts) {
    for (const n of [1, 2, 4, 6]) {
      it(`clears every node above it — ${host}, ${n} conditions`, () => {
        const model = taskGraph(profile(n));
        const frame = frameFor(model, WIDTH, geometry, chipsOf);
        expect(bandTop(model, frame)).toBeGreaterThanOrEqual(
          deepestAboveBand(model, frame, chipsOf) + BAND_GAP,
        );
      });
    }

    it(`clears the fan on the congruence fallback — ${host}, 6 conditions, 5 outcomes`, () => {
      /*
       * THE FIXTURE NOTHING ELSE REACHES. A go/no-go mix is the only thing that
       * restores the fan, and it also declares the fifth outcome — so this is
       * simultaneously the tallest drawing the app can produce and the only
       * exercise of a code path no shipped profile can trigger. Left
       * unexercised it would rot, and it would rot into precisely the bug the
       * collapse was written to remove.
       */
      const model = taskGraph(profile(6, { noGo: true }));
      expect(model.congruent).toBe(false);
      const frame = frameFor(model, WIDTH, geometry, chipsOf);
      expect(bandTop(model, frame)).toBeGreaterThanOrEqual(
        deepestAboveBand(model, frame, chipsOf) + BAND_GAP,
      );
    });

    it(`spaces fan arms so they cannot overlap — ${host}`, () => {
      const model = taskGraph(profile(6, { noGo: true }));
      const frame = frameFor(model, WIDTH, geometry, chipsOf);
      const arms = model.nodes
        .filter((node) => node.lane === "fan")
        .map((node) => ({ y: frame.y(node), box: measureNode(node, chipsOf(node)) }))
        .sort((a, b) => a.y - b.y);
      for (let i = 1; i < arms.length; i += 1) {
        const above = arms[i - 1]!;
        const below = arms[i]!;
        expect(below.y - below.box.up).toBeGreaterThanOrEqual(above.y + above.box.down);
      }
    });
  }

  it("is a LOWER bound — content shallower than the band does not pull it up", () => {
    /*
     * Deriving in both directions would make the drawing's proportions a
     * function of how many parameter groups a profile happens to declare, and
     * would silently re-shape every screenshot ever taken of it. A task with no
     * chips at all must draw the band exactly where the authored rows put it.
     */
    const model = taskGraph(profile(2));
    const bare = frameFor(model, WIDTH, VIEWER_GEOMETRY, NO_CHIPS);
    const spine = model.nodes.find((node) => node.id === "start")!;
    const authored = model.nodes.find((node) => node.id === "lazy")!;
    // Measured against the spine rather than against `padT`: `y` is relative to
    // the topmost row, and the outcome fan puts that above the spine.
    expect(bare.y(authored) - bare.y(spine)).toBeCloseTo(
      authored.row * VIEWER_GEOMETRY.rowPx,
      5,
    );

    // ...and with chips deep enough to reach it, the SAME band moves down.
    const chipped = frameFor(model, WIDTH, VIEWER_GEOMETRY, FOUR_CHIPS);
    expect(chipped.y(authored) - chipped.y(spine)).toBeGreaterThan(
      bare.y(authored) - bare.y(spine),
    );
  });
});

// --- the height claim -------------------------------------------------------

describe("frame height", () => {
  it("is constant in the condition count", () => {
    // The entire point of the collapse. Before it: 410px at four conditions
    // and 524px at six, with overlapping text at both.
    const viewer = [1, 2, 4, 6].map(
      (n) => frameFor(taskGraph(profile(n)), WIDTH, VIEWER_GEOMETRY, FOUR_CHIPS).height,
    );
    const live = [1, 2, 4, 6].map(
      (n) => frameFor(taskGraph(profile(n)), WIDTH, LIVE_GEOMETRY, NO_CHIPS).height,
    );
    expect(new Set(viewer).size).toBe(1);
    expect(new Set(live).size).toBe(1);
  });

  it("is linear in the outcome count, which is the honest caveat", () => {
    // A no-go profile declares the fifth outcome (`Withheld`) and is therefore
    // taller. Stating it here so "constant height" is never read as "one
    // height".
    const fourOutcomes = frameFor(
      taskGraph(profile(1)),
      WIDTH,
      VIEWER_GEOMETRY,
      FOUR_CHIPS,
    ).height;
    const fiveOutcomes = frameFor(
      taskGraph(profile(1, { noGo: true })),
      WIDTH,
      VIEWER_GEOMETRY,
      FOUR_CHIPS,
    ).height;
    expect(fiveOutcomes).toBeGreaterThan(fourOutcomes);
  });

  it("puts the live panel's drawing well inside a panel that must not scroll", () => {
    const height = frameFor(
      taskGraph(profile(6)),
      640,
      LIVE_GEOMETRY,
      NO_CHIPS,
    ).height;
    expect(height).toBeLessThan(300);
  });
});
