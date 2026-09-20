import type { SidecarClient } from "@/lib/ws/client";
import { CMD, EVT } from "@/lib/ws/protocol";

import type { IntanStatus, ScopeData } from "./types";

/**
 * The recording domain's store — the `HardwareStore` shape, for the same
 * reasons: the sidecar is authoritative, the store holds the last snapshot it
 * sent, and nothing here predicts a transition.
 *
 * Scope payloads are NOT held here. They arrive several times a second and are
 * drawn straight onto a canvas by the one window that asked for them, so they
 * are fanned out to per-scope listeners and never become React state.
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

type ScopeListener = (data: ScopeData) => void;

export class IntanStore {
  private status: IntanStatus = NO_INTAN;
  private readonly subs = new Set<() => void>();
  private readonly scopeSubs = new Map<string, Set<ScopeListener>>();

  attach(client: SidecarClient): () => void {
    const offs = [
      client.on(EVT.INTAN_STATUS, (data) => {
        this.status = data as IntanStatus;
        this.subs.forEach((cb) => cb());
      }),
      client.on(EVT.INTAN_SCOPE_DATA, (data) => {
        const d = data as ScopeData;
        this.scopeSubs.get(d.scopeId)?.forEach((cb) => cb(d));
      }),
    ];
    // The snapshot is replayed on connect, but a window opened mid-session
    // (a scope) may attach after that replay has gone by.
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

  onScope(scopeId: string, cb: ScopeListener): () => void {
    let set = this.scopeSubs.get(scopeId);
    if (!set) {
      set = new Set();
      this.scopeSubs.set(scopeId, set);
    }
    set.add(cb);
    return () => {
      set.delete(cb);
      if (set.size === 0) this.scopeSubs.delete(scopeId);
    };
  }
}
