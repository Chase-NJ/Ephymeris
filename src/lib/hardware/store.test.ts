import { describe, expect, it } from "vitest";

import { FakeSidecar } from "@/lib/ws/fakeSidecar";
import { CMD, EVT } from "@/lib/ws/protocol";

import { BOX_IDS, HardwareStore, type FlashQueueStatus } from "./store";

function attached() {
  const sidecar = new FakeSidecar("connected");
  const store = new HardwareStore();
  const detach = store.attach(sidecar);
  return { sidecar, store, detach };
}

/** A queue snapshot in which these boxes carry these sketches. */
function carrying(carries: Record<number, string>): FlashQueueStatus {
  return {
    boxes: BOX_IDS.map((box) => {
      const path = carries[box];
      return { box, job: null, carries: path ? { path, name: path.split("/").pop()! } : null };
    }),
  };
}

function rx(box: number, ...texts: string[]) {
  return { box, lines: texts.map((text) => ({ dir: "rx" as const, text, ts: 0 })) };
}

describe("port state", () => {
  it("records what the sidecar reports for a box, and nothing for an unknown box", () => {
    const { sidecar, store } = attached();
    const before = store.getAllStatuses();

    sidecar.emit(EVT.PORT_STATE, { box: 2, state: "PASSTHROUGH", prev: "IDLE", reason: "opened" });
    sidecar.emit(EVT.PORT_STATE, { box: 7, state: "ERROR", prev: "IDLE", reason: "no such box" });

    expect(store.getStatus(2)).toEqual({ state: "PASSTHROUGH", prev: "IDLE", reason: "opened" });
    expect(store.getStatus(7).state).toBe("IDLE");
    // Whole-map consumers re-render on a new snapshot, never on a mutated one.
    expect(store.getAllStatuses()).not.toBe(before);
    expect(store.getAllStatuses()[2]?.state).toBe("PASSTHROUGH");
  });

  it("notifies only the box that changed, plus the whole-map key", () => {
    const { sidecar, store } = attached();
    const heard: string[] = [];
    for (const key of ["state:1", "state:2", "state:*"]) {
      store.subscribe(key, () => heard.push(key));
    }
    sidecar.emit(EVT.PORT_STATE, { box: 2, state: "FLASHING", prev: "IDLE", reason: "" });
    expect(heard).toEqual(["state:2", "state:*"]);
  });
});

describe("console output", () => {
  it("appends lines with ids that stay unique across batches", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.PORT_OUTPUT, rx(1, "a", "b"));
    sidecar.emit(EVT.PORT_OUTPUT, rx(1, "c"));
    const lines = store.getLines(1);
    expect(lines.map((l) => l.text)).toEqual(["a", "b", "c"]);
    expect(new Set(lines.map((l) => l.id)).size).toBe(3);
  });

  it("keeps the newest 2000 lines", () => {
    const { sidecar, store } = attached();
    const texts = Array.from({ length: 2005 }, (_, i) => String(i));
    sidecar.emit(EVT.PORT_OUTPUT, rx(3, ...texts));
    const lines = store.getLines(3);
    expect(lines).toHaveLength(2000);
    expect(lines[0]?.text).toBe("5");
    expect(lines.at(-1)?.text).toBe("2004");
  });

  it("clears one box's scrollback", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.PORT_OUTPUT, rx(1, "a"));
    sidecar.emit(EVT.PORT_OUTPUT, rx(2, "b"));
    store.clearLines(1);
    expect(store.getLines(1)).toEqual([]);
    expect(store.getLines(2)).toHaveLength(1);
  });
});

describe("what each board carries", () => {
  it("asks for the flash queue on attach, for a window that missed its replay", async () => {
    const { sidecar, store } = attached();
    expect(sidecar.asked(CMD.FLASH_STATUS)).toHaveLength(1);
    await sidecar.reply(CMD.FLASH_STATUS, carrying({ 4: "/sketches/GRGL" }));
    expect(store.getFlashed(4)).toEqual({ path: "/sketches/GRGL", name: "GRGL" });
  });

  it("follows the queue and keeps an unchanged sketch's identity", () => {
    const { sidecar, store } = attached();
    sidecar.emit(EVT.FLASH_QUEUE, carrying({ 1: "/sketches/A", 2: "/sketches/B" }));
    const kept = store.getFlashed(1);
    const heard: string[] = [];
    store.subscribe("flashed:1", () => heard.push("flashed:1"));
    store.subscribe("flashed:2", () => heard.push("flashed:2"));

    sidecar.emit(EVT.FLASH_QUEUE, carrying({ 1: "/sketches/A" }));

    expect(store.getFlashed(1)).toBe(kept);
    expect(store.getFlashed(2)).toBeNull();
    expect(heard).toEqual(["flashed:2"]);
  });
});

describe("detach", () => {
  it("unsubscribes from every hardware event", () => {
    const { sidecar, detach } = attached();
    detach();
    for (const evt of [
      EVT.PORT_STATE,
      EVT.PORT_OUTPUT,
      EVT.BOARDS_PRESENCE,
      EVT.UTILITY_UPDATED,
      EVT.FLASH_QUEUE,
    ]) {
      expect(sidecar.listeners(evt)).toBe(0);
    }
  });
});
