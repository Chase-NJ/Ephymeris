/**
 * Where the nodes land — `TASKS.md#layout`.
 *
 * The defect these exist to prevent shipped for months and was invisible in
 * review: the abort band sat at constant rows while the condition fan grew from
 * a constant gap, and the two numbers were hand-fitted to a two-odor task. That
 * fit left **two pixels** of clearance at N=2 and overlapping text at N=4. No
 * exception, no missing glyph — just a drawing that looked deliberate.
 *
 * So the band's assertions are about CLEARANCE, expressed against `measureNode`
 * rather than against remembered pixel values: whatever a node occupies, the
 * band must sit below it, at every condition count, in both hosts, and on the
 * fallback path that no shipped profile can reach. `measureNode` and the drawn
 * glyph both read `nodeMetrics`, which is pinned to worked literals, so
 * clearance against the one is clearance against what is on screen.
 */

import { describe, expect, it } from "vitest";

import type { TaskProfile } from "@/lib/ws/protocol";

import { code, STROBES } from "./__fixtures__/vocabulary";

import {
  BAND_GAP,
  LIVE_GEOMETRY,
  VIEWER_GEOMETRY,
  frameFor,
  measureNode,
  nodeMetrics,
  type Geometry,
} from "./graphLayout";
import { taskGraph, type Condition, type TaskNode } from "./topology";


function profile(n: number, { noGo = false } = {}): TaskProfile {
  const onsets = [1, 2, 3, 4, 5, 6].map((n) => code(`ODOR_${n}_ON`));
  return {
    taskName: `GRGL ${n}-Odor`,
    kind: "behavior",
    config: [],
    strobes: STROBES,
    liveMetrics: onsets.slice(0, n).map((onset, i) => ({
      id: `p_correct_${i + 1}`,
      label: `P(x | odor ${i + 1})`,
      triggerCode: onset,
      successCode: noGo && i === n - 1
        ? code("WATER_POKE_NONE")
        : code(i % 2 ? "WATER_POKE_L" : "WATER_POKE_R"),
      alternateCode: code(i % 2 ? "WATER_POKE_R" : "WATER_POKE_L"),
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

// --- where a node's marks are drawn -----------------------------------------

/*
 * Worked by hand from R = 9, LABEL_BELOW_DY = 15, TICK_BLOCK = 13,
 * CHIP_GAP = 12, CHIP_STEP = 12, TEXT_DESCENT = 3, CHIP_RIGHT_DY = 17,
 * CHIP_ABOVE_DY = 23, LABEL_ABOVE_DY = -18, LABEL_RIGHT_DY = 4. If a constant
 * moves on purpose, rework these; never derive them from the constants.
 */
describe("nodeMetrics", () => {
  const plain: TaskNode = {
    id: "x",
    label: "Poke",
    kind: "state",
    column: 24,
    row: 0,
    governedBy: [],
    entryNames: [],
  };
  /** A collapsed node's conditions — the strip is drawn from these alone. */
  const variants = (n: number): Condition[] =>
    Array.from({ length: n }, (_, i) => ({
      id: `odor_${i + 1}`,
      label: `Odor ${i + 1}`,
      metricLabel: null,
      strobeName: `ODOR_${i + 1}_ON`,
      index: i + 1,
      correctAnswer: null,
    }));

  it("sets a below-anchored label under the glyph", () => {
    expect(nodeMetrics(plain, 0)).toMatchObject({ ticks: false, labelY: 24, up: 9, down: 27 });
  });

  it("stacks a below-anchored node's chips under its label", () => {
    // 75 here against 27 bare is the whole reason this cannot live in
    // `topology.ts`: the live panel draws zero chips and the viewer draws four,
    // so a model-side measurement is wrong for one of the two hosts by 48px.
    expect(nodeMetrics(plain, 4)).toEqual({ ticks: false, labelY: 24, chipY: 36, up: 9, down: 75 });
  });

  it("drops a below-anchored label and its chips under the tick strip", () => {
    const collapsed: TaskNode = { ...plain, variants: variants(4) };
    expect(nodeMetrics(collapsed, 4)).toEqual({
      ticks: true,
      labelY: 37,
      chipY: 49,
      up: 9,
      down: 88,
    });
  });

  it("draws no strip for a node standing only for itself", () => {
    const single: TaskNode = { ...plain, variants: variants(1) };
    expect(nodeMetrics(single, 0)).toMatchObject({ ticks: false, labelY: 24, down: 27 });
  });

  // Shorter than a below-anchored node, which is why five outcomes stack.
  it("sets a right-anchored label beside the glyph, which then reaches no lower than itself", () => {
    const right: TaskNode = { ...plain, labelAnchor: "right" };
    expect(nodeMetrics(right, 0)).toMatchObject({ ticks: false, labelY: 4, up: 9, down: 9 });
  });

  it("trails a right-anchored node's chips below its label", () => {
    const right: TaskNode = { ...plain, labelAnchor: "right" };
    expect(nodeMetrics(right, 4)).toEqual({ ticks: false, labelY: 4, chipY: 17, up: 9, down: 56 });
  });

  it("lifts an above-anchored label over the glyph, leaving only the glyph below", () => {
    const above: TaskNode = { ...plain, labelAnchor: "above" };
    expect(nodeMetrics(above, 0)).toMatchObject({ ticks: false, labelY: -18, up: 26, down: 9 });
  });

  it("hangs an above-anchored node's chips under the glyph", () => {
    const above: TaskNode = { ...plain, labelAnchor: "above" };
    expect(nodeMetrics(above, 4)).toEqual({ ticks: false, labelY: -18, chipY: 23, up: 26, down: 62 });
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
