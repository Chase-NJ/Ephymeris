/**
 * The strategy plane's axes — `data.md` §11.1.
 *
 * The bug these exist for was silent in the worst way: the plane demanded
 * exactly two declared conditions, so a four-odor task produced **no panel at
 * all** — not an error, not an empty frame with a reason, just the generic
 * "nothing to plot" that a shaping-only archive gets. The operator's reading of
 * that was "the app doesn't know about my task", which was true and unhelpful.
 *
 * Everything here is arithmetic and refusal: which conditions become which
 * axis, how they pool, and when the honest answer is no plane.
 */

import { describe, expect, it } from "vitest";

import type { AnalyticsSummary, ProfileGroup, RunSummary } from "./types";
import { pooledAxis, strategyAxes, strategyProfiles } from "./view";

function metric(
  id: string,
  answerSide: string | null,
  { hits = 10, counted = 20 } = {},
) {
  return {
    id,
    label: `P(${answerSide ?? "?"} well | ${id})`,
    windowSize: 20,
    answerSide,
    pSession: counted ? hits / counted : null,
    pWindow: null,
    hits,
    counted,
    triggered: counted,
    excluded: 0,
    wilsonLow: null,
    wilsonHigh: null,
    lowConfidence: false,
  };
}

function group(
  hash: string,
  metrics: ReturnType<typeof metric>[],
  runCount = 4,
): ProfileGroup {
  return {
    hash,
    taskName: hash,
    kind: "behavior",
    runCount,
    metrics: metrics.map((m) => ({
      id: m.id,
      label: m.label,
      windowSize: m.windowSize,
      answerSide: m.answerSide,
    })),
  } as unknown as ProfileGroup;
}

/** The pooled `__overall__` entry the sidecar prepends to a multi-condition
 *  group. It must never be mistaken for a condition. */
const OVERALL = { ...metric("__overall__", null), label: "Overall accuracy" };

describe("strategyAxes", () => {
  it("folds four conditions onto the two sides they are answered at", () => {
    const axes = strategyAxes(
      group("four", [
        OVERALL,
        metric("o1", "right"),
        metric("o2", "right"),
        metric("o3", "left"),
        metric("o4", "left"),
      ]),
    );
    expect(axes).not.toBeNull();
    // x takes the side of the FIRST declared condition, so a two-condition
    // task keeps the orientation it has always had.
    expect(axes!.x.side).toBe("right");
    expect(axes!.x.ids).toEqual(["o1", "o2"]);
    expect(axes!.y.ids).toEqual(["o3", "o4"]);
    expect(axes!.x.label).toBe("right well ×2");
  });

  it("reduces to today's plane for a two-condition task", () => {
    const axes = strategyAxes(
      group("two", [metric("o1", "right"), metric("o3", "left")]),
    );
    expect(axes!.x.ids).toEqual(["o1"]);
    expect(axes!.y.ids).toEqual(["o3"]);
    // No count suffix when a side carries one condition — the plane a
    // two-odor task drew before any of this.
    expect(axes!.x.label).toBe("right well");
  });

  it("never makes a withhold an axis", () => {
    /*
     * A withhold is the ABSENCE of an answer: no opposing side to plot it
     * against. It also carries the most dangerous `alternateCode` in the app
     * ("any port will do"), which is exactly what a careless axis would read.
     */
    const axes = strategyAxes(
      group("nogo", [
        metric("o1", "right"),
        metric("o3", "left"),
        metric("o5", "withhold"),
      ]),
    );
    expect(axes!.x.ids.concat(axes!.y.ids)).not.toContain("o5");
  });

  it("has no plane when the conditions cannot be opposed", () => {
    // One condition; both conditions on one side; no side derivable at all.
    expect(strategyAxes(group("one", [metric("o1", "right")]))).toBeNull();
    expect(
      strategyAxes(group("same", [metric("o1", "right"), metric("o2", "right")])),
    ).toBeNull();
    expect(
      strategyAxes(group("blind", [metric("o1", null), metric("o3", null)])),
    ).toBeNull();
    expect(strategyAxes(null)).toBeNull();
  });

  it("ignores the pooled entry, which is a summary and not a condition", () => {
    // `__overall__` has no side, so it could only ever be dropped — this pins
    // that it never becomes a third "side" or blocks the split.
    const axes = strategyAxes(
      group("two", [OVERALL, metric("o1", "right"), metric("o3", "left")]),
    );
    expect(axes!.x.ids.concat(axes!.y.ids)).toEqual(["o1", "o3"]);
  });
});

describe("pooledAxis", () => {
  const run = {
    metrics: [
      metric("o1", "right", { hits: 18, counted: 20 }),
      metric("o2", "right", { hits: 1, counted: 4 }),
      metric("o3", "left", { hits: 10, counted: 20 }),
    ],
  } as unknown as RunSummary;

  it("pools over integers, not over the conditions' rates", () => {
    /*
     * THE ONE THAT WOULD BE PLAUSIBLY WRONG. Averaging the two rates gives
     * (0.90 + 0.25) / 2 = 0.575 — a condition the animal met four times
     * dragging the axis as hard as one it met twenty times. Over integers it
     * is 19/24 = 0.79, which is what the session actually was.
     */
    const { p, counted } = pooledAxis(run, ["o1", "o2"]);
    expect(counted).toBe(24);
    expect(p).toBeCloseTo(19 / 24, 6);
    expect(p).not.toBeCloseTo(0.575, 2);
  });

  it("is null, never zero, when nothing on the axis scored", () => {
    // Zero percent and "no trials" are opposite claims about an animal (§9.6).
    expect(pooledAxis(run, ["nothing"])).toEqual({ p: null, counted: 0 });
  });
});

describe("strategyProfiles", () => {
  const summary = {
    profileGroups: [
      group("four", [metric("o1", "right"), metric("o3", "left")], 12),
      group("shaping", [metric("o1", "right")], 3),
      group("empty", [metric("o1", "right"), metric("o2", "right")], 0),
    ],
  } as unknown as AnalyticsSummary;

  it("lists every profile with runs, most-run first", () => {
    const profiles = strategyProfiles(summary);
    expect(profiles.map((entry) => entry.group.hash)).toEqual(["four", "shaping"]);
  });

  it("keeps the unplottable ones, with a reason instead of an absence", () => {
    /*
     * Omitting them would answer "where is my shaping task" with a hole, which
     * reads as a damaged archive rather than as a property of the task.
     */
    const shaping = strategyProfiles(summary).find(
      (entry) => entry.group.hash === "shaping",
    )!;
    expect(shaping.axes).toBeNull();
    expect(shaping.reason).toMatch(/one condition/);
  });

  it("says which KIND of no-plane it is", () => {
    const sameSide = strategyProfiles({
      profileGroups: [
        group("same", [metric("o1", "right"), metric("o2", "right")], 2),
        group("blind", [metric("o1", null), metric("o3", null)], 2),
      ],
    } as unknown as AnalyticsSummary);
    expect(sameSide[0]!.reason).toMatch(/same place/);
    expect(sameSide[1]!.reason).toMatch(/doesn't record which well/);
  });
});
