import { describe, expect, it } from "vitest";

import { binRates, describeSync, niceMax, rankSites, siteMax } from "./eventPsth";
import type { EventPsthSite } from "@/lib/ws/protocol";

function site(channel: string, responsive: EventPsthSite["responsive"], t: number | null, counts: number[][] = [[0]]): EventPsthSite {
  return { channel, counts, deltaHz: null, t, responsive };
}

describe("binRates", () => {
  it("turns spikes summed over trials into Hz per bin", () => {
    // 30 trials, 10 ms bins: 30 spikes in a bin is one per trial, 100 Hz.
    expect(binRates([0, 30, 15], 30, 10)).toEqual([0, 100, 50]);
    expect(binRates([4, 2], 0, 10)).toEqual([0, 0]);
  });
});

describe("niceMax", () => {
  it("rounds up to 1, 2 or 5 times a power of ten", () => {
    expect([0, 0.3, 7, 12, 100, 101].map(niceMax)).toEqual([1, 0.5, 10, 20, 100, 200]);
  });
});

describe("siteMax", () => {
  it("is the highest rate any group reaches, on a round axis", () => {
    const s = site("A-000", "up", 5, [[30, 0], [0, 6]]);
    expect(siteMax(s, { binMs: 10, groups: [{ label: "a", trials: 30 }, { label: "b", trials: 3 }] })).toBe(200);
  });
});

describe("rankSites", () => {
  it("puts responsive sites first, strongest first", () => {
    const ranked = rankSites([site("A-002", "none", 1), site("A-001", "down", -4), site("A-000", "up", 9)]);
    expect(ranked.map((s) => s.channel)).toEqual(["A-000", "A-001", "A-002"]);
  });
});

describe("describeSync", () => {
  it("worries about a missed pulse, or edges that never paired", () => {
    expect(describeSync({ matched: 60, missed: 0, stray: 3, tickPulsed: false })).toEqual({
      text: "60 placed · 0 missed · 3 stray",
      trouble: false,
    });
    expect(describeSync({ matched: 59, missed: 1, stray: 0, tickPulsed: false }).trouble).toBe(true);
    expect(describeSync({ matched: 0, missed: 0, stray: 40, tickPulsed: false }).trouble).toBe(true);
  });
});
