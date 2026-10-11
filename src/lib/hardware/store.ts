/**
 * Client-side mirror of the sidecar's hardware state.
 *
 * Holds per-box port state, console scrollback, board presence and the flash
 * queue, fed by the hardware events (`port.state`, `port.output`,
 * `boards.presence`, `flash.queue`, `utility.updated`) plus the on-connect
 * replay. Subscriptions are keyed per box on purpose: output
 * arrives at up to 20Hz per box (`ARCHITECTURE.md#passthrough-read`), and a chatty
 * box should re-render its own panel, not all six.
 *
 * The sidecar remains authoritative throughout — nothing in here ever *sets* a
 * port state; it only records what the sidecar reported (`ARCHITECTURE.md#invariants`).
 */

import type { SidecarClient } from "../ws/client";
import {
  CMD,
  EVT,
  type DetectedBoard,
  type FlashBoxStatus,
  type FlashQueueStatus,
  type OutputLine,
  type PortStateName,
  type UtilityStatus,
} from "../ws/protocol";

export type {
  DetectedBoard,
  FlashBoxStatus,
  FlashJobStatus,
  FlashQueueStatus,
  PortStateName,
  UtilityBoxState,
  UtilityStatus,
} from "../ws/protocol";

/** One box's state as last reported — `port.state` minus the `box` key. */
export interface PortStatus {
  state: PortStateName;
  prev: PortStateName;
  reason: string;
}

/** A wire `OutputLine` plus a monotonic id assigned on arrival — the stable
 *  React key in a trimmed list. */
export interface ConsoleLine extends OutputLine {
  id: number;
}

/** The sketch the sidecar last flashed to a box's board
 *  (`ARCHITECTURE.md#what-a-board-carries`). */
export interface FlashedSketch {
  path: string;
  name: string;
}

export const BOX_IDS = [1, 2, 3, 4, 5, 6] as const;

/** Mirrors the sidecar's ring capacity — scrollback is debug output, not data. */
const MAX_LINES = 2000;

const INITIAL_STATUS: PortStatus = { state: "IDLE", prev: "IDLE", reason: "no data yet" };
const NO_LINES: ConsoleLine[] = [];
const NO_BOARDS: DetectedBoard[] = [];

const INITIAL_STATUSES: Readonly<Record<number, PortStatus>> = Object.fromEntries(
  BOX_IDS.map((b) => [b, INITIAL_STATUS]),
);

/**
 * Before the first `utility.updated` lands. `configured: false` is the honest
 * pre-connect answer — it renders as "no baseline", which is also what an
 * un-set-up rig looks like, and never claims a box is ready.
 */
const NO_UTILITY: UtilityStatus = {
  configured: false,
  sketchPath: null,
  sketchName: null,
  canIdentify: false,
  held: false,
  message: null,
  boxes: BOX_IDS.map((box) => ({ box, state: "unknown", detail: null, identifying: false })),
};

/** Before the first `flash.queue` lands: nothing queued, nothing known. */
const NO_FLASHES: FlashQueueStatus = {
  boxes: BOX_IDS.map((box) => ({ box, job: null, carries: null })),
};

export class HardwareStore {
  private statuses = new Map<number, PortStatus>(BOX_IDS.map((b) => [b, INITIAL_STATUS]));
  /** Immutable snapshot of all six, replaced on change — for whole-map consumers. */
  private statusesAll: Readonly<Record<number, PortStatus>> = INITIAL_STATUSES;
  private lines = new Map<number, ConsoleLine[]>(BOX_IDS.map((b) => [b, NO_LINES]));
  private boards: DetectedBoard[] = NO_BOARDS;
  /** The flash queue, as last reported (`ARCHITECTURE.md#the-flash-queue`). */
  private flashes: FlashQueueStatus = NO_FLASHES;
  /** What each board carries, from the queue's snapshot — how a console panel
   *  knows which profile to load. Kept per box so an unchanged sketch keeps
   *  its identity across snapshots. */
  private flashed = new Map<number, FlashedSketch | null>(BOX_IDS.map((b) => [b, null]));
  /** The hardware utility baseline, as last reported (`ARCHITECTURE.md#hardware-utility-baseline`). */
  private utility: UtilityStatus = NO_UTILITY;
  private subs = new Map<string, Set<() => void>>();
  private seq = 0;

  /** Wire up to the client's event stream. Returns a detach function. */
  attach(client: SidecarClient): () => void {
    const offs = [
      client.on(EVT.PORT_STATE, (data) => {
        const d = data as PortStatus & { box: number };
        if (!this.statuses.has(d.box)) return;
        const status = { state: d.state, prev: d.prev, reason: d.reason };
        this.statuses.set(d.box, status);
        this.statusesAll = { ...this.statusesAll, [d.box]: status };
        this.notify(`state:${d.box}`);
        this.notify("state:*");
      }),

      client.on(EVT.PORT_OUTPUT, (data) => {
        const d = data as { box: number; lines: Array<Omit<ConsoleLine, "id">> };
        const current = this.lines.get(d.box);
        if (!current || d.lines.length === 0) return;
        const appended = [...current, ...d.lines.map((l) => ({ ...l, id: ++this.seq }))];
        this.lines.set(
          d.box,
          appended.length > MAX_LINES ? appended.slice(-MAX_LINES) : appended,
        );
        this.notify(`output:${d.box}`);
      }),

      client.on(EVT.BOARDS_PRESENCE, (data) => {
        const d = data as { boards?: DetectedBoard[] } | null;
        this.boards = d?.boards ?? NO_BOARDS;
        this.notify("presence");
      }),

      client.on(EVT.UTILITY_UPDATED, (data) => {
        this.utility = data as UtilityStatus;
        this.notify("utility");
      }),

      client.on(EVT.FLASH_QUEUE, (data) => this.takeFlashes(data as FlashQueueStatus)),
    ];
    // Replayed on connect, but a window that attaches later (a scope pop-up)
    // has missed that replay.
    void client
      .call(CMD.FLASH_STATUS, {})
      .then((status) => this.takeFlashes(status))
      .catch(() => undefined);
    return () => offs.forEach((off) => off());
  }

  private takeFlashes(status: FlashQueueStatus): void {
    this.flashes = status;
    for (const row of status.boxes) {
      if (!this.flashed.has(row.box)) continue;
      const before = this.flashed.get(row.box) ?? null;
      const after = row.carries;
      if (before?.path === after?.path) continue;
      this.flashed.set(row.box, after ? { path: after.path, name: after.name } : null);
      this.notify(`flashed:${row.box}`);
    }
    this.notify("flashes");
  }

  // --- snapshots (stable references; replaced only on change) -------------

  getStatus(box: number): PortStatus {
    return this.statuses.get(box) ?? INITIAL_STATUS;
  }

  getAllStatuses(): Readonly<Record<number, PortStatus>> {
    return this.statusesAll;
  }

  getLines(box: number): ConsoleLine[] {
    return this.lines.get(box) ?? NO_LINES;
  }

  getBoards(): DetectedBoard[] {
    return this.boards;
  }

  getUtility(): UtilityStatus {
    return this.utility;
  }

  getFlashed(box: number): FlashedSketch | null {
    return this.flashed.get(box) ?? null;
  }

  getFlashes(): FlashQueueStatus {
    return this.flashes;
  }

  getBoxFlash(box: number): FlashBoxStatus | null {
    return this.flashes.boxes.find((row) => row.box === box) ?? null;
  }

  clearLines(box: number): void {
    if (!this.lines.has(box)) return;
    this.lines.set(box, NO_LINES);
    this.notify(`output:${box}`);
  }

  // --- subscriptions ------------------------------------------------------

  subscribe(key: string, callback: () => void): () => void {
    let set = this.subs.get(key);
    if (!set) {
      set = new Set();
      this.subs.set(key, set);
    }
    set.add(callback);
    return () => {
      set.delete(callback);
    };
  }

  private notify(key: string): void {
    const set = this.subs.get(key);
    if (!set) return;
    for (const callback of set) callback();
  }
}
