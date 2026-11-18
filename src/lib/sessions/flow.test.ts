import { describe, expect, it } from "vitest";

import {
  missionControlHint,
  sessionDoor,
  sessionFlow,
  stepUrl,
  type FlowFacts,
} from "./flow";
import type { Session, SessionStatus } from "./types";

/** `rounds` are the ends of the rounds it ran, in order; null is one still open. */
function session(
  status: SessionStatus = "running",
  rounds: (string | null)[] = [],
  recording = false,
): Session {
  return {
    id: "s1",
    cohortId: "c1",
    prefixId: "p1",
    prefixName: "2O-Bdisc",
    sessionNumber: "15",
    date: "2026-10-10",
    startedAt: "2026-10-10T09:00:00",
    endedAt: null,
    clockStartedAt: "2026-10-10T09:05:00",
    clockEndedAt: null,
    status,
    folderPath: "/data/c1/2O-Bdisc_15",
    rounds: rounds.map((endedAt, order) => ({
      order,
      startedAt: "2026-10-10T09:05:00",
      endedAt,
      label: null,
    })),
    durationMinutes: null,
    recording: recording ? ({} as Session["recording"]) : null,
  };
}

const box = (n: number, ended = false) => ({ box: n, ended });
const live = (...boxes: number[]) => (b: number) => boxes.includes(b);

function facts(over: Partial<FlowFacts> = {}): FlowFacts {
  return {
    session: session(),
    held: true,
    boxes: [box(1), box(2)],
    isLive: live(),
    ...over,
  };
}

describe("has the session run", () => {
  it("is false only while configuring — the one status sessions.abandon accepts", () => {
    expect(sessionFlow(facts({ session: session("configuring") })).hasRun).toBe(false);
    expect(sessionFlow(facts({ session: session("running") })).hasRun).toBe(true);
    expect(sessionFlow(facts({ session: session("completed") })).hasRun).toBe(true);
  });

  it("is false before the record has arrived", () => {
    expect(sessionFlow(facts({ session: null })).hasRun).toBe(false);
  });
});

describe("round progress", () => {
  it("is done when every box has ended, with no live session events seen (a reload)", () => {
    const { progress } = sessionFlow(facts({ boxes: [box(1, true), box(2, true)] }));
    expect(progress).toEqual({ total: 2, running: 0, ended: 2, allRunning: false, done: true });
  });

  it("never counts a box live on the port as ended, whatever an older snapshot says", () => {
    const { progress } = sessionFlow(facts({ boxes: [box(1, true), box(2, true)], isLive: live(1) }));
    expect([progress.ended, progress.running, progress.done]).toEqual([1, 1, false]);
  });

  it("reports every box running", () => {
    expect(sessionFlow(facts({ isLive: live(1, 2) })).progress.allRunning).toBe(true);
    expect(sessionFlow(facts({ isLive: live(1) })).progress.allRunning).toBe(false);
  });

  it("is neither done nor all running with no boxes", () => {
    const { progress } = sessionFlow(facts({ boxes: [] }));
    expect([progress.done, progress.allRunning]).toEqual([false, false]);
  });
});

describe("the end of a round", () => {
  const finished = [box(1, true), box(2, true)];

  it("is reached when every box of a session that ran has finished", () => {
    expect(sessionFlow(facts({ boxes: finished })).roundOver).toBe(true);
  });

  it("is not reached while a box is still to finish, or before anything ran", () => {
    expect(sessionFlow(facts({ boxes: [box(1, true), box(2)] })).roundOver).toBe(false);
    expect(sessionFlow(facts({ boxes: finished, session: session("configuring") })).roundOver).toBe(false);
  });
});

describe("the round a step is about", () => {
  it("is the first before anything has run", () => {
    expect(sessionFlow(facts({ session: session("configuring") })).round).toBe(1);
  });

  it("is the one on the rig while it is open", () => {
    expect(sessionFlow(facts({ session: session("running", ["t1", null]) })).round).toBe(2);
  });

  it("is the next one between rounds", () => {
    expect(sessionFlow(facts({ session: session("running", ["t1", "t2"]), boxes: [] })).round).toBe(3);
  });
});

describe("where a session belongs", () => {
  it("is Mission Control while a round is on the rig", () => {
    expect(sessionFlow(facts()).rigStep).toBe("control");
  });

  it("is the Boxes step between rounds", () => {
    expect(sessionFlow(facts({ boxes: [] })).rigStep).toBe("boxes");
  });

  it("is nowhere fixed for a session that does not hold the rig", () => {
    expect(sessionFlow(facts({ held: false, boxes: [] })).rigStep).toBeNull();
  });

  it("spots a mapping that was never confirmed", () => {
    const flow = sessionFlow(facts({ session: session("configuring"), held: false, boxes: [] }));
    expect(flow.neverConfirmed).toBe(true);
    expect(sessionFlow(facts({ session: session("configuring") })).neverConfirmed).toBe(false);
  });
});

describe("step URLs", () => {
  it("carry the session and nothing else", () => {
    expect(stepUrl.configure()).toBe("/session/new");
    expect(stepUrl.boxes("s1")).toBe("/session/s1/mapping");
    expect(stepUrl.record("s1")).toBe("/session/s1/recording");
    expect(stepUrl.control("s1")).toBe("/session/s1/control");
  });

  it("lead back into a held session at Mission Control, or the Boxes step between rounds", () => {
    expect(sessionDoor({ session: session(), boxes: [{ box: 1 }] as never })).toBe("/session/s1/control");
    expect(sessionDoor({ session: session(), boxes: [] })).toBe("/session/s1/mapping");
  });
});

describe("Mission Control's hint", () => {
  const hint = (over: Partial<FlowFacts>, connected = true) =>
    missionControlHint(sessionFlow(facts(over)), connected);

  it("names the single next action", () => {
    expect(hint({}, false)).toMatch(/Waiting for the hardware/);
    expect(hint({})).toMatch(/Start All begins/);
    expect(hint({ isLive: live(1) })).toMatch(/Stop takes effect/);
    expect(hint({ boxes: [box(1, true), box(2)] })).toMatch(/remaining boxes/);
    expect(hint({ boxes: [box(1, true), box(2, true)] })).toMatch(/run more animals, or end/);
    expect(hint({ boxes: [] })).toMatch(/set up the next round/);
  });
});
