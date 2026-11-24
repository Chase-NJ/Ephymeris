import { describe, expect, it } from "vitest";

import { layOut } from "./SessionRail";
import type { SessionListItem } from "./types";

function session(id: string, date: string): SessionListItem {
  return { id, date } as SessionListItem;
}

describe("session rail layout", () => {
  it("spaces dated sessions by date", () => {
    const { marks, days } = layOut([
      session("a", "2026-11-01"),
      session("b", "2026-11-02"),
      session("c", "2026-11-12"),
    ]);
    expect(days).toBe(11);
    const [a, b, c] = marks.map((m) => m.x);
    expect(b! - a!).toBeGreaterThan(0);
    expect(c! - b!).toBeCloseTo((b! - a!) * 10);
  });

  // A recovered session from a folder with no date in its name arrives with
  // `date: ""`, sorted first; it used to zero the span and stack every mark.
  it("keeps the axis when an undated session sorts first", () => {
    const { marks, days, range, axisLeft, ticks } = layOut([
      session("undated", ""),
      session("a", "2026-11-01"),
      session("b", "2026-11-02"),
      session("c", "2026-11-12"),
    ]);
    expect(days).toBe(11);
    expect(range).toEqual({ from: "2026-11-01", to: "2026-11-12" });
    const x = new Map(marks.map((m) => [m.session.id, m.x]));
    expect(new Set(x.values()).size).toBe(4);
    expect(x.get("undated")!).toBeLessThan(axisLeft);
    expect(x.get("a")!).toBeGreaterThanOrEqual(axisLeft);
    expect(ticks[0]).toMatchObject({ date: "undated", labelled: true });
  });

  it("lays out an archive with no dated session at all", () => {
    const { marks, range, days } = layOut([session("x", ""), session("y", "")]);
    expect(days).toBe(0);
    expect(range).toBeNull();
    expect(marks).toHaveLength(2);
  });
});
