import { describe, expect, it } from "vitest";

import { groupProgress, sessionHasRun } from "./progress";

const box = (n: number, ended = false) => ({ box: n, ended });
const live = (...boxes: number[]) => (b: number) => boxes.includes(b);

describe("sessionHasRun", () => {
  it("is false only for a session still configuring — the one sessions.abandon accepts", () => {
    expect(sessionHasRun({ status: "configuring" })).toBe(false);
    expect(sessionHasRun({ status: "running" })).toBe(true);
    expect(sessionHasRun({ status: "completed" })).toBe(true);
  });

  it("is false before the snapshot has arrived", () => {
    expect(sessionHasRun(null)).toBe(false);
  });
});

describe("groupProgress", () => {
  it("is done when every box has ended, with no live session events seen (a reload)", () => {
    const p = groupProgress([box(1, true), box(2, true)], live());
    expect(p).toEqual({ total: 2, running: 0, ended: 2, allRunning: false, done: true });
  });

  it("is not done while any box has yet to finish", () => {
    expect(groupProgress([box(1, true), box(2)], live()).done).toBe(false);
    expect(groupProgress([box(1, true), box(2)], live(2)).done).toBe(false);
  });

  it("never counts a box live on the port as ended, whatever an older snapshot says", () => {
    const p = groupProgress([box(1, true), box(2, true)], live(1));
    expect(p.ended).toBe(1);
    expect(p.running).toBe(1);
    expect(p.done).toBe(false);
  });

  it("reports every box running", () => {
    expect(groupProgress([box(1), box(2)], live(1, 2)).allRunning).toBe(true);
    expect(groupProgress([box(1), box(2)], live(1)).allRunning).toBe(false);
  });

  it("is neither done nor all running with no boxes", () => {
    const p = groupProgress([], live());
    expect(p.done).toBe(false);
    expect(p.allRunning).toBe(false);
  });
});
