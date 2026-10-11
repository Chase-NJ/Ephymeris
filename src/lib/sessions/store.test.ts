import { describe, expect, it } from "vitest";

import { FakeSidecar } from "@/lib/ws/fakeSidecar";
import { CMD, ERR, EVT } from "@/lib/ws/protocol";

import { SessionStore } from "./store";
import type { ActiveSessions, Session } from "./types";

function session(id: string): Session {
  return {
    id,
    cohortId: "c1",
    prefixId: "p1",
    prefixName: "2O-Bdisc",
    sessionNumber: "15",
    date: "2026-10-10",
    startedAt: "2026-10-10T09:00:00",
    endedAt: null,
    clockStartedAt: "2026-10-10T09:05:00",
    clockEndedAt: null,
    status: "configuring",
    folderPath: `/data/c1/${id}`,
    groupRuns: [],
    durationMinutes: null,
    recording: null,
  };
}

/** Nothing running, these sessions set up. */
function configuring(...ids: string[]): ActiveSessions {
  return { running: null, configuring: ids.map(session), stale: [] };
}

function attached(status: "connecting" | "connected" = "connecting") {
  const sidecar = new FakeSidecar(status);
  const store = new SessionStore();
  const detach = store.attach(sidecar);
  return { sidecar, store, detach };
}

function output(box: number, ...lines: Array<["rx" | "tx", string]>) {
  return { box, lines: lines.map(([dir, text]) => ({ dir, text, ts: 0 })) };
}

describe("the active-session answer", () => {
  it("is asked for on connect and held once it arrives", async () => {
    const { sidecar, store } = attached();
    expect(sidecar.asked(CMD.SESSIONS_ACTIVE)).toHaveLength(0);

    sidecar.setStatus("connected");
    expect(sidecar.asked(CMD.SESSIONS_ACTIVE)).toHaveLength(1);
    expect(store.activeIsLoaded()).toBe(false);

    await sidecar.reply(CMD.SESSIONS_ACTIVE, configuring("a"));
    expect(store.activeIsLoaded()).toBe(true);
    expect(store.getActive()).toEqual(configuring("a"));
  });

  it("is asked for again on every reconnect", async () => {
    const { sidecar, store } = attached("connected");
    // The drop fails the ask in flight, as the real client does.
    sidecar.setStatus("reconnecting");
    sidecar.setStatus("connected");
    expect(sidecar.asked(CMD.SESSIONS_ACTIVE)).toHaveLength(1);

    await sidecar.reply(CMD.SESSIONS_ACTIVE, configuring("after"));
    expect(store.getActive()).toEqual(configuring("after"));
  });

  it("is replaced wholesale by each lifecycle broadcast", () => {
    const { sidecar, store } = attached();
    let heard = 0;
    store.subscribe("active", () => (heard += 1));

    sidecar.emit(EVT.SESSION_LIFECYCLE, configuring("a", "b"));
    sidecar.emit(EVT.SESSION_LIFECYCLE, configuring("c"));

    expect(store.getActive()).toEqual(configuring("c"));
    expect(store.activeIsLoaded()).toBe(true);
    expect(heard).toBe(2);
  });

  it("is not rolled back by an answer that lands after a newer broadcast", async () => {
    const { sidecar, store } = attached("connected");

    // The sidecar read this answer before a transition, then sent it after
    // that transition's broadcast.
    sidecar.emit(EVT.SESSION_LIFECYCLE, configuring("new"));
    await sidecar.reply(CMD.SESSIONS_ACTIVE, configuring("old"));

    expect(store.getActive()).toEqual(configuring("new"));
    // Either could have been the newer, so it asks again and takes that answer.
    expect(sidecar.asked(CMD.SESSIONS_ACTIVE)).toHaveLength(1);
    await sidecar.reply(CMD.SESSIONS_ACTIVE, configuring("newest"));
    expect(store.getActive()).toEqual(configuring("newest"));
  });

  it("stays unloaded when the ask is refused", async () => {
    const { sidecar, store } = attached("connected");
    await sidecar.refuse(CMD.SESSIONS_ACTIVE, ERR.INTERNAL);
    expect(store.activeIsLoaded()).toBe(false);
    expect(store.getActive()).toBeNull();
  });
});

describe("live strobes", () => {
  it("decodes only received code-tab-time lines", () => {
    const { sidecar, store } = attached();
    sidecar.emit(
      EVT.PORT_OUTPUT,
      output(2, ["rx", "11\t1500"], ["tx", "12\t1600"], ["rx", "READY"], ["rx", " 13\t1700 "]),
    );
    expect(store.getStrobes(2)).toEqual([
      { code: "11", at: 1500 },
      { code: "13", at: 1700 },
    ]);
    expect(store.getStrobes(3)).toEqual([]);
  });

  it("bumps the version only when a strobe was added", () => {
    const { sidecar, store } = attached();
    const before = store.getStrobeVersion();
    sidecar.emit(EVT.PORT_OUTPUT, output(1, ["rx", "READY"]));
    expect(store.getStrobeVersion()).toBe(before);
    sidecar.emit(EVT.PORT_OUTPUT, output(1, ["rx", "11\t5"]));
    expect(store.getStrobeVersion()).toBe(before + 1);
  });

  it("forgets a box's strobes when that box starts again", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.PORT_OUTPUT, output(1, ["rx", "11\t5"]));
    sidecar.emit(EVT.PORT_OUTPUT, output(2, ["rx", "11\t5"]));
    store.resetBox(1);
    expect(store.getStrobes(1)).toEqual([]);
    expect(store.getStrobes(2)).toHaveLength(1);
  });
});

describe("telemetry", () => {
  it("keeps the latest metrics and a history that skips missing values", () => {
    const { sidecar, store } = attached();
    const metric = (value: number | null) => [{ id: "accuracy", value, n: 1 }];
    sidecar.emit(EVT.SESSION_TELEMETRY, { box: 4, animalId: "a1", metrics: metric(0.5) });
    sidecar.emit(EVT.SESSION_TELEMETRY, { box: 4, animalId: "a1", metrics: metric(null) });
    sidecar.emit(EVT.SESSION_TELEMETRY, { box: 4, animalId: "a1", metrics: metric(0.75) });

    expect(store.getTelemetry(4)).toEqual(metric(0.75));
    expect(store.getHistory(4, "accuracy")).toEqual([0.5, 0.75]);
  });

  it("takes Debug Mode's running flag from the sidecar's port telemetry", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.PORT_TELEMETRY, { box: 3, running: true, metrics: [] });
    expect(store.isDebugRunning(3)).toBe(true);
    sidecar.emit(EVT.PORT_TELEMETRY, { box: 3, running: false, metrics: [] });
    expect(store.isDebugRunning(3)).toBe(false);
  });
});

describe("write errors", () => {
  it("records a sidecar error that names a box, and ignores one that does not", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.SIDECAR_ERROR, { code: "WRITE_FAILED", message: "disk full", detail: { box: 5 } });
    sidecar.emit(EVT.SIDECAR_ERROR, { code: "INTERNAL", message: "elsewhere", detail: null });
    expect(store.getWriteError(5)).toBe("disk full");
    expect([1, 2, 3, 4, 6].map((box) => store.getWriteError(box))).toEqual([
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("detach", () => {
  it("unsubscribes everything and ignores an answer still in flight", async () => {
    const { sidecar, store, detach } = attached("connected");
    detach();

    for (const evt of [EVT.SESSION_LIFECYCLE, EVT.PORT_OUTPUT, EVT.SESSION_TELEMETRY]) {
      expect(sidecar.listeners(evt)).toBe(0);
    }
    await sidecar.reply(CMD.SESSIONS_ACTIVE, configuring("late"));
    expect(store.activeIsLoaded()).toBe(false);
  });
});
