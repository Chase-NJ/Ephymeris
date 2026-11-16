import type { SidecarPort } from "@/lib/ws/port";
import { CMD, EVT } from "@/lib/ws/protocol";

import type { IntanSpikes, IntanStatus } from "./types";

/**
 * The recording domain's store — the `HardwareStore` shape, for the same
 * reasons: the sidecar is authoritative, the store holds the last snapshot it
 * sent, and nothing here predicts a transition.
 *
 * `intan.spikes` batches are NOT held here. They arrive thirty times a second
 * per box and are drawn straight onto the live firing map, so they are fanned
 * out to per-box listeners and never become React state.
 */
export const NO_INTAN: IntanStatus = {
  state: "disconnected",
  message: null,
  connected: false,
  controller: null,
  version: null,
  sampleRate: null,
  synthetic: false,
  headstagePresent: false,
  runMode: null,
  ports: {},
  confirmsWrites: null,
  rigHasSync: true,
  liveStreams: false,
  recording: null,
  waitingOn: [],
  sync: [],
};

type SpikesListener = (data: IntanSpikes) => void;

export class IntanStore {
  private status: IntanStatus = NO_INTAN;
  private readonly subs = new Set<() => void>();
  private readonly spikeSubs = new Map<number, Set<SpikesListener>>();

  attach(client: SidecarPort): () => void {
    const offs = [
      client.on(EVT.INTAN_STATUS, (data) => {
        this.status = data;
        this.subs.forEach((cb) => cb());
      }),
      client.on(EVT.INTAN_SPIKES, (d) => {
        this.spikeSubs.get(d.box)?.forEach((cb) => cb(d));
      }),
    ];
    // The snapshot is replayed on connect, but this store may attach after
    // that replay has gone by.
    void client
      .call(CMD.INTAN_STATUS, {})
      .then((status) => {
        this.status = status;
        this.subs.forEach((cb) => cb());
      })
      .catch(() => undefined);
    return () => offs.forEach((off) => off());
  }

  getStatus = (): IntanStatus => this.status;

  subscribe = (cb: () => void): (() => void) => {
    this.subs.add(cb);
    return () => this.subs.delete(cb);
  };

  onSpikes(box: number, cb: SpikesListener): () => void {
    let set = this.spikeSubs.get(box);
    if (!set) {
      set = new Set();
      this.spikeSubs.set(box, set);
    }
    set.add(cb);
    return () => {
      set.delete(cb);
      if (set.size === 0) this.spikeSubs.delete(box);
    };
  }
}
