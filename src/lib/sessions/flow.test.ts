import { describe, expect, it } from "vitest";

import type { Cohort } from "@/lib/cohorts/types";

import {
  missionControlHint,
  sessionDoor,
  sessionFlow,
  stepUrl,
  type FlowFacts,
} from "./flow";
import type { Session, SessionStatus } from "./types";

function session(status: SessionStatus = "running", ran: string[] = [], recording = false): Session {
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
    groupRuns: ran.map((groupId, order) => ({
      groupId,
      order,
      startedAt: "2026-10-10T09:05:00",
      endedAt: null,
    })),
    durationMinutes: null,
    recording: recording ? ({} as Session["recording"]) : null,
  };
}

/** A cohort with one box-assigned animal in each named group. */
function cohort(...groups: string[]): Cohort {
  return {
    id: "c1",
    groups: groups.map((id, order) => ({ id, name: `Group ${id}`, order })),
    animals: groups.map((groupId, i) => ({ id: `a${i}`, name: `remy${i}`, groupId, boxNumber: i + 1 })),
  } as unknown as Cohort;
}

const box = (n: number, ended = false) => ({ box: n, ended });
const live = (...boxes: number[]) => (b: number) => boxes.includes(b);

function facts(over: Partial<FlowFacts> = {}): FlowFacts {
  return {
    session: session(),
    cohort: cohort("A"),
    held: true,
    rigGroupId: "A",
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

describe("group progress", () => {
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

describe("the wrap-up", () => {
  const finished = [box(1, true), box(2, true)];

  it("is due when the last group of a session that ran has finished", () => {
    expect(sessionFlow(facts({ boxes: finished })).wrapUpDue).toBe(true);
  });

  it("waits while another group has yet to run", () => {
    const flow = sessionFlow(facts({ boxes: finished, cohort: cohort("A", "B"), session: session("running", ["A"]) }));
    expect([flow.groupsWaiting, flow.lastGroup, flow.wrapUpDue]).toEqual([1, false, false]);
  });

  it("is due once every other group has run, in whatever order", () => {
    const flow = sessionFlow(
      facts({ boxes: finished, cohort: cohort("A", "B"), session: session("running", ["B", "A"]) }),
    );
    expect(flow.wrapUpDue).toBe(true);
  });

  it("never opens before the cohort is known, when other groups cannot be counted", () => {
    const flow = sessionFlow(facts({ boxes: finished, cohort: null }));
    expect([flow.lastGroup, flow.wrapUpDue]).toEqual([false, false]);
  });
});

describe("the group chip", () => {
  it("names the rig's group and counts the groups that ran, multi-group only", () => {
    const flow = sessionFlow(facts({ cohort: cohort("A", "B", "C"), session: session("running", ["A", "A"]) }));
    expect(flow.group).toEqual({ name: "Group A", ran: 1, count: 3 });
    expect(flow.multiGroup).toBe(true);
    expect(sessionFlow(facts()).group).toBeNull();
  });

  it("names the step's own group before the rig holds one", () => {
    const flow = sessionFlow(
      facts({ cohort: cohort("A", "B"), rigGroupId: null, boxes: [], groupId: "B" }),
    );
    expect(flow.group?.name).toBe("Group B");
  });
});

describe("where a session belongs", () => {
  it("is Mission Control while a group is on the rig", () => {
    expect(sessionFlow(facts()).rigStep).toBe("control");
  });

  it("is the group step between groups", () => {
    expect(sessionFlow(facts({ rigGroupId: null, boxes: [] })).rigStep).toBe("group");
  });

  it("is nowhere fixed for a session that does not hold the rig", () => {
    expect(sessionFlow(facts({ held: false, rigGroupId: null, boxes: [] })).rigStep).toBeNull();
  });

  it("spots a mapping that was never confirmed", () => {
    const flow = sessionFlow(facts({ session: session("configuring"), held: false, rigGroupId: null, boxes: [] }));
    expect(flow.neverConfirmed).toBe(true);
    expect(sessionFlow(facts({ session: session("configuring") })).neverConfirmed).toBe(false);
  });
});

describe("step URLs", () => {
  it("carry no cohort, and the group only where the operator chose it", () => {
    expect(stepUrl.configure()).toBe("/session/new");
    expect(stepUrl.group("s1")).toBe("/session/s1/group");
    expect(stepUrl.boxes("s1", "g a")).toBe("/session/s1/mapping?group=g%20a");
    expect(stepUrl.record("s1", "g")).toBe("/session/s1/recording?group=g");
    expect(stepUrl.control("s1")).toBe("/session/s1/control");
  });

  it("lead back into a held session at Mission Control, or the group step between groups", () => {
    expect(sessionDoor({ session: session(), groupId: "A" })).toBe("/session/s1/control");
    expect(sessionDoor({ session: session(), groupId: null })).toBe("/session/s1/group");
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
    expect(hint({ boxes: [box(1, true), box(2, true)] })).toMatch(/End Session saves/);
  });

  it("offers Switch Group only when there is another group", () => {
    expect(hint({ boxes: [] })).toBe("No boxes in this group — end the session.");
    expect(hint({ boxes: [], cohort: cohort("A", "B") })).toMatch(/switch group/);
  });
});
