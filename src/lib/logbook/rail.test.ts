import { describe, expect, it } from "vitest";

import type { SessionListItem } from "../analytics/types";
import {
  GAP_CAP,
  GAP_PX,
  ROW_PX,
  dayNumber,
  layoutRail,
  monthBins,
  monthJump,
  stepFrom,
} from "./rail";

let ordinal = 0;
function session(id: string, date: string, number = id): SessionListItem {
  ordinal += 1;
  return {
    id,
    cohortId: "c",
    prefixName: "P",
    sessionNumber: number,
    date,
    startedAt: `${date}T09:00:00+00:00`,
    endedAt: null,
    clockStartedAt: `${date}T09:00:00+00:00`,
    clockEndedAt: null,
    status: "completed",
    folderPath: "/x",
    ordinal,
    groupRuns: [],
  };
}

describe("layoutRail", () => {
  it("puts the newest session on top and consecutive days one row apart", () => {
    ordinal = 0;
    const rail = layoutRail([session("a", "2026-10-05"), session("b", "2026-10-06")]);
    expect(rail.order).toEqual(["b", "a"]);
    expect(rail.positions.get("b")).toBe(0);
    expect(rail.positions.get("a")).toBe(ROW_PX);
  });

  it("draws a weekend as two empty days, marked as weekend", () => {
    ordinal = 0;
    // Fri 2 Oct → Mon 5 Oct 2026.
    const rail = layoutRail([session("fri", "2026-10-02"), session("mon", "2026-10-05")]);
    const empties = rail.items.filter((i) => i.kind === "empty");
    expect(empties).toHaveLength(2);
    expect(empties.every((i) => i.kind === "empty" && i.weekend)).toBe(true);
    expect(rail.positions.get("fri")).toBe(ROW_PX + 2 * GAP_PX);
  });

  it("stacks sessions on one day and labels only the first", () => {
    ordinal = 0;
    const rail = layoutRail([session("am", "2026-10-06"), session("pm", "2026-10-06")]);
    const rows = rail.items.filter((i) => i.kind === "session");
    expect(rows.map((r) => r.kind === "session" && r.labelsDay)).toEqual([true, false]);
    expect(rail.positions.get("am")).toBe(ROW_PX);
  });

  it("breaks a long gap instead of drawing it to scale", () => {
    ordinal = 0;
    const rail = layoutRail([session("old", "2026-09-01"), session("new", "2026-09-20")]);
    const breaks = rail.items.filter((i) => i.kind === "break");
    expect(breaks).toEqual([expect.objectContaining({ days: 18 })]);
    expect(rail.items.some((i) => i.kind === "empty")).toBe(false);
    // Never closer than the longest gap drawn to scale.
    expect(rail.positions.get("old")).toBeGreaterThan(ROW_PX + GAP_CAP * GAP_PX);
  });

  it("orders by ordinal, never by session number", () => {
    ordinal = 0;
    const nine = session("nine", "2026-10-01", "9");
    const ten = session("ten", "2026-10-02", "10");
    expect(layoutRail([ten, nine]).order).toEqual(["ten", "nine"]);
  });

  it("reads days without a time zone", () => {
    expect(dayNumber("2026-03-29") - dayNumber("2026-03-28")).toBe(1);
    expect(Number.isNaN(dayNumber("not a date"))).toBe(true);
  });
});

describe("stepping", () => {
  it("clamps at both ends and starts at the newest", () => {
    const order = ["c", "b", "a"];
    expect(stepFrom(order, null, 1)).toBe("c");
    expect(stepFrom(order, "c", -1)).toBe("c");
    expect(stepFrom(order, "c", 1)).toBe("b");
    expect(stepFrom(order, "a", 1)).toBe("a");
    expect(stepFrom([], "a", 1)).toBeNull();
  });
});

describe("months", () => {
  it("keeps empty months in the strip and counts per day", () => {
    ordinal = 0;
    const sessions = [
      session("jul", "2026-07-30"),
      session("sep1", "2026-09-02"),
      session("sep2", "2026-09-02"),
    ];
    const bins = monthBins(sessions);
    expect(bins.map((b) => b.key)).toEqual(["2026-07", "2026-08", "2026-09"]);
    expect(bins[1]!.total).toBe(0);
    expect(bins[2]!.days[1]).toBe(2);
    expect(bins[2]!.newestId).toBe("sep2");
  });

  it("jumps over empty months", () => {
    ordinal = 0;
    const sessions = [session("jul", "2026-07-30"), session("sep", "2026-09-02")];
    expect(monthJump(sessions, "sep", -1)).toBe("jul");
    expect(monthJump(sessions, "jul", 1)).toBe("sep");
    expect(monthJump(sessions, "sep", 1)).toBe("sep");
  });
});
