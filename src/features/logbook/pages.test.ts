import { describe, expect, it } from "vitest";

import type { SessionListItem } from "@/features/analytics/types";
import { FRONT, contents, direction, folios, monthOf, monthTurn, spreadOrder, turn } from "./pages";

function session(id: string, date: string, ordinal: number, number = id): SessionListItem {
  return {
    id,
    cohortId: "c",
    prefixName: "2O-Bdisc",
    sessionNumber: number,
    date,
    startedAt: `${date}T09:00:00Z`,
    endedAt: `${date}T10:00:00Z`,
    clockStartedAt: `${date}T09:00:00Z`,
    clockEndedAt: `${date}T10:00:00Z`,
    status: "completed",
    folderPath: "/x",
    ordinal,
    rounds: [],
  };
}

// Handed over newest first, as the sidecar lists them.
const SESSIONS = [
  session("d", "2026-11-19", 4, "25"),
  session("c", "2026-11-02", 3, "24"),
  session("b", "2026-10-30", 2, "23"),
  session("a", "2026-09-15", 1, "22"),
];

describe("the notebook's pages", () => {
  const order = spreadOrder(SESSIONS);

  it("binds the front matter first, then every session oldest first", () => {
    expect(order).toEqual([FRONT, "a", "b", "c", "d"]);
  });

  it("orders by the sidecar's ordinal, never by session number", () => {
    const renumbered = [session("x", "2026-11-19", 1, "99"), session("y", "2026-11-20", 2, "1")];
    expect(spreadOrder(renumbered)).toEqual([FRONT, "x", "y"]);
  });

  it("turns a page at a time and stops at the covers", () => {
    expect(turn(order, "b", 1)).toBe("c");
    expect(turn(order, "b", -1)).toBe("a");
    expect(turn(order, "a", -1)).toBe(FRONT);
    expect(turn(order, FRONT, -1)).toBe(FRONT);
    expect(turn(order, "d", 1)).toBe("d");
    // A spread that is gone opens at the last written page.
    expect(turn(order, "tidied-away", 1)).toBe("d");
    expect(turn([], null, 1)).toBeNull();
  });

  it("knows which way a leaf turns", () => {
    expect(direction(order, "a", "d")).toBe("forward");
    expect(direction(order, "d", FRONT)).toBe("back");
  });

  it("numbers the front matter in roman and the first session from 1", () => {
    expect(folios(order, FRONT)).toEqual({ verso: "i", recto: "ii" });
    expect(folios(order, "a")).toEqual({ verso: "1", recto: "2" });
    expect(folios(order, "d")).toEqual({ verso: "7", recto: "8" });
  });
});

describe("the contents", () => {
  const months = contents(SESSIONS);

  it("files each session under its month, in page order, with its page", () => {
    expect(months.map((m) => m.label)).toEqual(["September 2026", "October 2026", "November 2026"]);
    expect(months[2]!.rows.map((r) => [r.day, r.weekday, r.title, r.page])).toEqual([
      ["2", "Mon", "2O-Bdisc_24", "5"],
      ["19", "Thu", "2O-Bdisc_25", "7"],
    ]);
  });

  it("marks a session recovered from files", () => {
    const recovered = contents([session("adopted:2O_1_2026-01-05", "2026-01-05", 1)]);
    expect(recovered[0]!.rows[0]!.recovered).toBe(true);
  });

  it("jumps to the first page of the next month with sessions", () => {
    expect(monthOf(months, "c")).toBe("2026-11");
    expect(monthOf(months, FRONT)).toBeNull();
    expect(monthTurn(months, "d", -1)).toBe("b");
    expect(monthTurn(months, "b", -1)).toBe("a");
    expect(monthTurn(months, "a", -1)).toBe(FRONT);
    expect(monthTurn(months, "a", 1)).toBe("b");
    expect(monthTurn(months, "d", 1)).toBe("d");
    expect(monthTurn(months, FRONT, 1)).toBe("a");
    expect(monthTurn(months, FRONT, -1)).toBe(FRONT);
  });
});
