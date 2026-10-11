import { describe, expect, it } from "vitest";

import { FakeSidecar } from "@/lib/ws/fakeSidecar";
import { CMD, ERR, EVT, type PortStateName, type SessionBox } from "@/lib/ws/protocol";

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

function portState(box: number, state: PortStateName, prev: PortStateName) {
  return { box, state, prev, reason: "test" };
}

/** One mapped box as `runner.snapshot()` reports it. */
function mapped(
  box: number,
  run: Partial<Pick<SessionBox, "running" | "startedAt" | "ended">> = {},
): SessionBox {
  return {
    box,
    animalId: `a${box}`,
    animalName: `Rat${box}`,
    sketchName: "Task",
    sketchPath: "/sketches/Task",
    running: false,
    startedAt: null,
    ended: false,
    ...run,
  };
}

/** Session `s` holds the rig with `group` mapped onto these boxes. */
function holding(group: string | null, ...boxes: SessionBox[]): ActiveSessions {
  return { running: { session: session("s"), groupId: group, boxes }, configuring: [], stale: [] };
}

/** Give a box a finished run's worth of live data: strobes, metrics, its end. */
function finishedRun(sidecar: FakeSidecar, box: number) {
  sidecar.emit(EVT.PORT_OUTPUT, output(box, ["rx", "11\t5"]));
  sidecar.emit(EVT.SESSION_TELEMETRY, {
    box,
    animalId: `a${box}`,
    metrics: [{ id: "accuracy", value: 0.5, n: 1 }],
  });
  sidecar.emit(EVT.SIDECAR_ERROR, { code: "WRITE_FAILED", message: "disk full", detail: { box } });
  sidecar.emit(EVT.SESSION_ANIMAL_ENDED, {
    box,
    animalId: `a${box}`,
    stopReason: "completed",
    filePath: null,
  });
}

/** Whether the store still shows any of a box's last run. */
function shows(store: SessionStore, box: number) {
  return {
    strobes: store.getStrobes(box).length,
    metrics: store.getTelemetry(box).length,
    history: store.getHistory(box, "accuracy").length,
    ended: store.getEnded(box) !== null,
    writeError: store.getWriteError(box) !== null,
  };
}

const ALL_OF_IT = { strobes: 1, metrics: 1, history: 1, ended: true, writeError: true };
const NOTHING = { strobes: 0, metrics: 0, history: 0, ended: false, writeError: false };

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
    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IDLE"));
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

// The store notices a new run on the events it already receives; no caller
// tells it (`ARCHITECTURE.md#overview`: the frontend renders what the sidecar
// reports and never predicts a transition).
describe("a new run clears the last one", () => {
  it("clears a box when its port enters IN_SESSION, and only that box", () => {
    const { sidecar, store } = attached();
    finishedRun(sidecar, 1);
    finishedRun(sidecar, 2);

    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IDLE"));

    expect(shows(store, 1)).toEqual(NOTHING);
    expect(shows(store, 2)).toEqual(ALL_OF_IT);
  });

  it("keeps a running box's data through the connect replay of its state", () => {
    const { sidecar, store } = attached();
    finishedRun(sidecar, 1);
    // Replayed on every connect with `prev` equal to `state`: not a transition.
    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IN_SESSION"));
    expect(shows(store, 1)).toEqual(ALL_OF_IT);
  });

  it("keeps the last Debug run through a refused START, and clears it on the sidecar's arm (B13)", async () => {
    const { sidecar, store } = attached("connected");
    sidecar.emit(EVT.PORT_OUTPUT, output(3, ["rx", "11\t5"]));
    sidecar.emit(EVT.PORT_TELEMETRY, {
      box: 3,
      running: false,
      metrics: [{ id: "accuracy", value: 0.5, n: 1 }],
    });

    // The Debug console's Send START, refused: the board never heard it.
    const sent = sidecar
      .call(CMD.PORT_SEND_START, { box: 3, sketchPath: "/s/T", config: {} })
      .then(
        () => "sent",
        () => "refused",
      );
    await sidecar.refuse(CMD.PORT_SEND_START, ERR.SKETCH_UNKNOWN);
    expect(await sent).toBe("refused");
    expect(store.getStrobes(3)).toHaveLength(1);
    expect(store.getTelemetry(3)).toHaveLength(1);
    expect(store.getHistory(3, "accuracy")).toEqual([0.5]);

    // Accepted: the sidecar arms the run, and that is what clears the box.
    sidecar.emit(EVT.PORT_TELEMETRY, { box: 3, running: true, metrics: [] });
    expect(store.getStrobes(3)).toEqual([]);
    expect(store.getHistory(3, "accuracy")).toEqual([]);
    expect(store.isDebugRunning(3)).toBe(true);

    // Every later payload of the same run keeps what it has gathered.
    sidecar.emit(EVT.PORT_OUTPUT, output(3, ["rx", "12\t9"]));
    sidecar.emit(EVT.PORT_TELEMETRY, {
      box: 3,
      running: true,
      metrics: [{ id: "accuracy", value: 1, n: 1 }],
    });
    expect(store.getStrobes(3)).toEqual([{ code: "12", at: 9 }]);
    expect(store.getHistory(3, "accuracy")).toEqual([1]);
  });

  it("clears every box when a newly confirmed mapping is broadcast", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding(null));
    finishedRun(sidecar, 1);
    finishedRun(sidecar, 5);

    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g2", mapped(1), mapped(2)));

    // Box 5 is not in the new mapping and must not linger either.
    expect(shows(store, 1)).toEqual(NOTHING);
    expect(shows(store, 5)).toEqual(NOTHING);
  });

  it("keeps the run through broadcasts that only move it on", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g", mapped(1), mapped(2)));
    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IDLE"));
    finishedRun(sidecar, 1);

    // Start All, then box 1 finishing, then the group ending.
    sidecar.emit(
      EVT.SESSION_LIFECYCLE,
      holding("g", mapped(1, { running: true, startedAt: "t" }), mapped(2, { running: true, startedAt: "t" })),
    );
    sidecar.emit(EVT.PORT_STATE, portState(1, "IDLE", "IN_SESSION"));
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g", mapped(1, { ended: true }), mapped(2, { running: true, startedAt: "t" })));
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding(null));

    expect(shows(store, 1)).toEqual(ALL_OF_IT);
  });

  it("keeps a Debug run through a repeat of the mapping it already showed", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g", mapped(1)));
    sidecar.emit(EVT.PORT_TELEMETRY, { box: 6, running: true, metrics: [] });
    sidecar.emit(EVT.PORT_OUTPUT, output(6, ["rx", "11\t5"]));

    // An unrelated announce (a session created, a tidy) while the mapping waits.
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g", mapped(1)));

    expect(store.getStrobes(6)).toHaveLength(1);
  });

  it("clears a re-confirm of the same mapping after a box ran, though the broadcast repeats", () => {
    // The open risk: no nonce in the payload. Confirming the same group again
    // with nothing announced in between (a per-box start of a later group does
    // not announce, nor does a run ending) repeats the last broadcast exactly.
    const { sidecar, store } = attached();
    const confirmed = holding("g2", mapped(1), mapped(2));
    sidecar.emit(EVT.SESSION_LIFECYCLE, confirmed);
    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IDLE"));
    finishedRun(sidecar, 1);
    sidecar.emit(EVT.PORT_STATE, portState(1, "IDLE", "IN_SESSION"));

    // Back to Boxes after box 2's start was refused, and confirm again.
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g2", mapped(1), mapped(2)));

    expect(shows(store, 1)).toEqual(NOTHING);
  });

  it("keeps a run still finishing on its port when an announce lands meanwhile", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g2", mapped(1)));
    sidecar.emit(EVT.PORT_STATE, portState(1, "IN_SESSION", "IDLE"));
    finishedRun(sidecar, 1);

    // The runner has let go of the run but the port is still IN_SESSION
    // while its files are written, so the snapshot reads as never started.
    sidecar.emit(EVT.SESSION_LIFECYCLE, holding("g2", mapped(1)));

    expect(shows(store, 1)).toEqual(ALL_OF_IT);
  });

  it("keeps what arrived before the first answer, which has nothing shown before it to forget", async () => {
    const { sidecar, store } = attached("connected");
    sidecar.emit(EVT.PORT_TELEMETRY, { box: 6, running: true, metrics: [] });
    sidecar.emit(EVT.PORT_OUTPUT, output(6, ["rx", "11\t5"]));

    await sidecar.reply(CMD.SESSIONS_ACTIVE, holding("g", mapped(1)));

    expect(store.getStrobes(6)).toHaveLength(1);
  });

  it("keeps the run when a reconnect's answer shows the mapping it already held", async () => {
    const { sidecar, store } = attached("connected");
    await sidecar.reply(CMD.SESSIONS_ACTIVE, holding("g", mapped(1)));
    finishedRun(sidecar, 1);

    sidecar.setStatus("reconnecting");
    sidecar.setStatus("connected");
    await sidecar.reply(CMD.SESSIONS_ACTIVE, holding("g", mapped(1)));

    expect(shows(store, 1)).toEqual(ALL_OF_IT);
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
