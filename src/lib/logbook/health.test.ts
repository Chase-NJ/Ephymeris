import { describe, expect, it } from "vitest";

import {
  formatDelta,
  formatGrams,
  formatShare,
  parseWeight,
  readWeight,
  weightTrend,
} from "./health";
import type { HealthEntry } from "./types";

function weighIn(date: string, weightG: number, baseline = false): HealthEntry {
  return { animalId: "a1", date, weightG, baseline, recordedAt: `${date}T09:00:00Z` };
}

describe("reading a weight", () => {
  const history = [
    weighIn("2026-11-10", 340, true),
    weighIn("2026-11-12", 318),
    weighIn("2026-11-16", 300),
    weighIn("2026-11-17", 286),
  ];

  it("reads the day against the weigh-in before it and the marked baseline", () => {
    const reading = readWeight(history, "2026-11-16");
    expect(reading.entry?.weightG).toBe(300);
    expect(reading.previous?.date).toBe("2026-11-12");
    expect(reading.deltaG).toBe(-18);
    expect(reading.reference?.date).toBe("2026-11-10");
    expect(reading.ofReference).toBeCloseTo(300 / 340);
    expect(reading.low).toBe(false);
  });

  it("marks a weigh-in under 85% of baseline as low", () => {
    expect(readWeight(history, "2026-11-17").low).toBe(true);
  });

  it("does not care what order the history arrives in", () => {
    expect(readWeight([...history].reverse(), "2026-11-16").previous?.date).toBe("2026-11-12");
  });

  it("gives no percentage when nothing was marked as baseline", () => {
    const unmarked = [weighIn("2026-11-10", 340), weighIn("2026-11-12", 250)];
    const reading = readWeight(unmarked, "2026-11-12");
    expect(reading.ofReference).toBeNull();
    // 26% lighter than the first weigh-in on record, and still not "low":
    // the first weight on record is not assumed to be a free-feeding one.
    expect(reading.low).toBe(false);
    expect(reading.deltaG).toBe(-90);
  });

  it("uses the latest baseline at or before the day, never a later one", () => {
    const rebased = [...history, weighIn("2026-11-18", 320, true), weighIn("2026-11-19", 310)];
    expect(readWeight(rebased, "2026-11-17").reference?.date).toBe("2026-11-10");
    expect(readWeight(rebased, "2026-11-19").reference?.date).toBe("2026-11-18");
    expect(readWeight(rebased, "2026-11-18").ofReference).toBe(1);
  });

  it("reads a day with no weigh-in as empty, with what came before", () => {
    const reading = readWeight(history, "2026-11-14");
    expect(reading.entry).toBeNull();
    expect(reading.previous?.date).toBe("2026-11-12");
    expect(reading.deltaG).toBeNull();
    expect(reading.ofReference).toBeNull();
  });

  it("trends the last weigh-ins up to the day", () => {
    expect(weightTrend(history, "2026-11-16", 2).map((w) => w.weightG)).toEqual([318, 300]);
    expect(weightTrend(history, "2026-11-01", 5)).toEqual([]);
  });
});

describe("a typed weight", () => {
  it("accepts grams with a point, a comma or a unit", () => {
    expect(parseWeight("312")).toEqual({ kind: "weight", grams: 312 });
    expect(parseWeight(" 312.44 ")).toEqual({ kind: "weight", grams: 312.4 });
    expect(parseWeight("312,4")).toEqual({ kind: "weight", grams: 312.4 });
    expect(parseWeight("28.5 g")).toEqual({ kind: "weight", grams: 28.5 });
  });

  it("reads an emptied cell as a removal", () => {
    expect(parseWeight("  ")).toEqual({ kind: "clear" });
  });

  it("refuses what is not a weight", () => {
    expect(parseWeight("heavy").kind).toBe("invalid");
    expect(parseWeight("-12").kind).toBe("invalid");
    expect(parseWeight("0").kind).toBe("invalid");
    expect(parseWeight("2500").kind).toBe("invalid");
    expect(parseWeight("1e3").kind).toBe("invalid");
  });
});

describe("weights in print", () => {
  it("keeps one decimal and a true minus", () => {
    expect(formatGrams(312)).toBe("312.0");
    expect(formatDelta(2.14)).toBe("+2.1");
    expect(formatDelta(-3.44)).toBe("−3.4");
    expect(formatDelta(0.04)).toBe("0.0");
    expect(formatShare(0.916)).toBe("92%");
  });
});
