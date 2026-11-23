import { describe, expect, it } from "vitest";

import {
  DEFAULT_IMPEDANCE_FLAGS as FLAGS,
  formatOhms,
  measuredAgo,
  normalizeImpedanceFlags,
  siteMarks,
  siteVerdict,
  summarizeImpedance,
  type ImpedanceMeasurement,
} from "./impedance";

function measurement(at: string, sites: Record<string, number>): ImpedanceMeasurement {
  return {
    animalId: "rat1",
    measuredAt: at,
    box: 1,
    sessionId: "s1",
    frequencyHz: 1000,
    file: null,
    sites: Object.fromEntries(Object.entries(sites).map(([c, ohms]) => [c, { ohms, phaseDeg: -70 }])),
  };
}

describe("siteVerdict", () => {
  it("flags open and short by the bounds, before any change", () => {
    expect(siteVerdict(6e6, null, FLAGS)).toBe("open");
    expect(siteVerdict(10e3, null, FLAGS)).toBe("short");
    expect(siteVerdict(6e6, 1e5, FLAGS)).toBe("open"); // also changed, but open says what is wrong
    expect(siteVerdict(1e5, null, FLAGS)).toBe("ok");
  });

  it("flags a site that more than doubled or halved since the last measurement", () => {
    expect(siteVerdict(2.1e5, 1e5, FLAGS)).toBe("changed");
    expect(siteVerdict(0.49e5, 1e5, FLAGS)).toBe("changed");
    expect(siteVerdict(2e5, 1e5, FLAGS)).toBe("ok"); // exactly double is the line
    expect(siteVerdict(1.5e5, 1e5, FLAGS)).toBe("ok");
  });
});

describe("summarizeImpedance", () => {
  it("judges the channels the box records now, against the previous measurement", () => {
    const summary = summarizeImpedance(
      {
        current: measurement("2026-11-15T10:00:00Z", { "A-000": 1e5, "A-001": 7e6, "A-002": 3e5, "A-009": 1e5 }),
        previous: measurement("2026-11-08T10:00:00Z", { "A-000": 1.1e5, "A-002": 1e5 }),
      },
      ["A-000", "A-001", "A-002", "A-003"],
      FLAGS,
    );
    expect(summary.sites.map((s) => [s.channel, s.verdict])).toEqual([
      ["A-000", "ok"],
      ["A-001", "open"],
      ["A-002", "changed"],
    ]);
    expect(summary.counts).toEqual({ open: 1, short: 0, changed: 1, ok: 1 });
    expect(summary.missing).toEqual(["A-003"]); // recorded now, not measured then
    expect(summary.sites[0]?.previousOhms).toBe(1.1e5);
  });

  it("marks each judged site for the probe map: a tone, the value and what it was", () => {
    const summary = summarizeImpedance(
      {
        current: measurement("2026-11-15T10:00:00Z", { "A-000": 1e5, "A-001": 7e6 }),
        previous: measurement("2026-11-08T10:00:00Z", { "A-001": 1e5 }),
      },
      ["A-000", "A-001"],
      FLAGS,
    );
    expect(siteMarks(summary)).toEqual({
      "A-000": { tone: "ok", label: "100 kΩ" },
      "A-001": { tone: "error", label: "7 MΩ · open (was 100 kΩ)" },
    });
  });
});

describe("formatOhms", () => {
  it("picks the unit and keeps three significant figures at most", () => {
    expect(formatOhms(980)).toBe("980 Ω");
    expect(formatOhms(123_000)).toBe("123 kΩ");
    expect(formatOhms(45_600)).toBe("45.6 kΩ");
    expect(formatOhms(1.2e6)).toBe("1.2 MΩ");
    expect(formatOhms(5e6)).toBe("5 MΩ");
  });
});

describe("measuredAgo", () => {
  it("counts calendar days, not 24-hour spans", () => {
    const now = new Date(2026, 10, 15, 9, 0);
    expect(measuredAgo(new Date(2026, 10, 15, 8, 0).toISOString(), now)).toBe("today");
    expect(measuredAgo(new Date(2026, 10, 14, 23, 0).toISOString(), now)).toBe("yesterday");
    expect(measuredAgo(new Date(2026, 10, 12, 9, 0).toISOString(), now)).toBe("3 days ago");
  });
});

describe("normalizeImpedanceFlags", () => {
  it("heals per key and never lets the short bound reach the open one", () => {
    expect(normalizeImpedanceFlags(undefined)).toEqual(FLAGS);
    expect(normalizeImpedanceFlags({ openOhms: 2e6, changeFactor: "x" })).toEqual({ ...FLAGS, openOhms: 2e6 });
    const crossed = normalizeImpedanceFlags({ openOhms: 1e5, shortOhms: 5e5 });
    expect(crossed.shortOhms).toBeLessThan(crossed.openOhms);
  });
});
