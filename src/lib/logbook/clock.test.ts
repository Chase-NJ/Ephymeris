import { describe, expect, it } from "vitest";

import { atOnDay, elapsedSeconds, formatDuration, formatOffset } from "./clock";

describe("clock", () => {
  it("formats durations and offsets", () => {
    expect(formatDuration(0)).toBe("00:00");
    expect(formatDuration(48 * 60 + 45)).toBe("48:45");
    expect(formatDuration(3600 + 5)).toBe("1:00:05");
    expect(formatDuration(-3)).toBe("00:00");
    expect(formatOffset(754_500)).toBe("T+12:34");
    expect(formatOffset(null)).toBe("");
  });

  it("counts an open session to now", () => {
    const now = new Date("2026-10-06T10:00:00Z");
    expect(elapsedSeconds("2026-10-06T09:00:00Z", null, now)).toBe(3600);
    expect(elapsedSeconds("2026-10-06T09:00:00Z", "2026-10-06T09:30:00Z", now)).toBe(1800);
    expect(elapsedSeconds("nope", null, now)).toBeNull();
  });

  it("places a typed time on the session's day in local time", () => {
    const iso = atOnDay("2026-10-06", "09:30");
    expect(iso).not.toBeNull();
    const back = new Date(iso!);
    expect([back.getHours(), back.getMinutes(), back.getDate()]).toEqual([9, 30, 6]);
    expect(atOnDay("2026-10-06", "25:00")).toBeNull();
  });
});
