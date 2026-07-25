/**
 * Client-side mirror of prefix and live-session state.
 *
 * Two independent slices with keyed subscriptions, same shape as
 * `HardwareStore`: the prefix list (fed by `prefixes.updated`, replayed on
 * connect) and per-box live telemetry (fed by `session.telemetry`, which is
 * pushed per metric update rather than batched — far lower frequency than raw
 * strobes, per `websocket-protocol.md` §4).
 */

import type { SidecarClient } from "../ws/client";
import { EVT } from "../ws/protocol";
import type { AnimalEnded, BoxTelemetry, Prefix, TelemetryMetric } from "./types";

const NO_PREFIXES: Prefix[] = [];
const NO_METRICS: TelemetryMetric[] = [];
const NO_HISTORY: number[] = [];

/** Enough points for a legible trace over a long session, not unbounded. */
const HISTORY_LIMIT = 240;

export class SessionStore {
  private prefixes: Prefix[] = NO_PREFIXES;
  private prefixesLoaded = false;
  /** Latest rolling metrics per box. */
  private telemetry = new Map<number, TelemetryMetric[]>();
  /**
   * Recent values per box per metric, oldest first.
   *
   * The sidecar pushes only the current rolling value, so the shape of the
   * session over time exists nowhere else — this is what the live charts draw.
   */
  private history = new Map<number, Map<string, number[]>>();
  /** Finished runs this session, per box. */
  private ended = new Map<number, AnimalEnded>();
  private subs = new Map<string, Set<() => void>>();

  attach(client: SidecarClient): () => void {
    const offs = [
      client.on(EVT.PREFIXES_UPDATED, (data) => {
        const payload = data as { prefixes?: Prefix[] } | null;
        this.prefixes = payload?.prefixes ?? NO_PREFIXES;
        this.prefixesLoaded = true;
        this.notify("prefixes");
      }),

      client.on(EVT.SESSION_TELEMETRY, (data) => {
        const d = data as BoxTelemetry;
        if (typeof d?.box !== "number") return;
        this.telemetry.set(d.box, d.metrics ?? NO_METRICS);
        this.appendHistory(d.box, d.metrics ?? NO_METRICS);
        this.notify(`telemetry:${d.box}`);
      }),

      client.on(EVT.SESSION_ANIMAL_ENDED, (data) => {
        const d = data as AnimalEnded;
        if (typeof d?.box !== "number") return;
        this.ended.set(d.box, d);
        this.notify(`ended:${d.box}`);
        this.notify("ended");
      }),
    ];
    return () => offs.forEach((off) => off());
  }

  // --- prefixes ---------------------------------------------------------

  getPrefixes(): Prefix[] {
    return this.prefixes;
  }

  prefixesAreLoaded(): boolean {
    return this.prefixesLoaded;
  }

  // --- live session -----------------------------------------------------

  getTelemetry(box: number): TelemetryMetric[] {
    return this.telemetry.get(box) ?? NO_METRICS;
  }

  getEnded(box: number): AnimalEnded | null {
    return this.ended.get(box) ?? null;
  }

  /** How many boxes have finished their run this group. */
  getEndedCount(): number {
    return this.ended.size;
  }

  /** One metric's recent values for a box, oldest first. */
  getHistory(box: number, metricId: string): number[] {
    return this.history.get(box)?.get(metricId) ?? NO_HISTORY;
  }

  private appendHistory(box: number, metrics: TelemetryMetric[]): void {
    let perMetric = this.history.get(box);
    if (!perMetric) {
      perMetric = new Map();
      this.history.set(box, perMetric);
    }
    for (const metric of metrics) {
      if (metric.value === null) continue;
      const series = [...(perMetric.get(metric.id) ?? NO_HISTORY), metric.value];
      perMetric.set(
        metric.id,
        series.length > HISTORY_LIMIT ? series.slice(-HISTORY_LIMIT) : series,
      );
    }
  }

  /** Clear per-run state when a new group's boxes are confirmed. */
  resetRun(): void {
    this.telemetry.clear();
    this.history.clear();
    this.ended.clear();
    for (const key of this.subs.keys()) {
      if (key.startsWith("telemetry:") || key.startsWith("ended")) this.notify(key);
    }
  }

  /** Forget one box's finished run when it starts again mid-group. */
  resetBox(box: number): void {
    this.telemetry.delete(box);
    this.history.delete(box);
    this.ended.delete(box);
    this.notify(`telemetry:${box}`);
    this.notify(`ended:${box}`);
    this.notify("ended");
  }

  /** Reset every box that has a finished run on record. */
  resetFinishedBoxes(): void {
    for (const box of [...this.ended.keys()]) this.resetBox(box);
  }

  // --- subscriptions ----------------------------------------------------

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
