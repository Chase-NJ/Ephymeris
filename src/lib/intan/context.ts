import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { useSidecar } from "@/lib/ws/context";
import { CMD } from "@/lib/ws/protocol";

import type { IntanStore } from "./store";
import type { IntanStatus, ScopeData, ScopeKind } from "./types";

export const IntanContext = createContext<IntanStore | null>(null);

export function useIntanStore(): IntanStore {
  const store = useContext(IntanContext);
  if (!store) throw new Error("intan hooks must be used inside <IntanProvider>");
  return store;
}

/** The sidecar's last word on RHX and the recording. */
export function useIntanStatus(): IntanStatus {
  const store = useIntanStore();
  return useSyncExternalStore(store.subscribe, store.getStatus);
}

/** How often an open scope tells the sidecar it is still being looked at. The
 *  sidecar sweeps a scope untouched for 15 s, which is how a window that was
 *  killed rather than closed stops costing RHX a streamed channel. */
const KEEPALIVE_MS = 5_000;

export interface ScopeHandle {
  /** Null until the sidecar has opened it, and again if it could not. */
  scopeId: string | null;
  error: string | null;
}

/**
 * Open one live view for as long as the calling component is mounted.
 *
 * `onData` is called outside React, a few times a second — draw from it, do not
 * set state from it unless the value is cheap and changes rarely. `channel` and
 * `params` are pushed to the sidecar when they change rather than reopening the
 * scope, so a SpikeScope switching channel does not drop and re-add a streamed
 * waveform on RHX's side for a channel it is about to ask for again.
 */
export function useScope(
  kind: ScopeKind,
  box: number,
  channel: string | null,
  params: Record<string, unknown>,
  onData: (data: ScopeData) => void,
): ScopeHandle {
  const { client, status } = useSidecar();
  const store = useIntanStore();
  const [handle, setHandle] = useState<ScopeHandle>({ scopeId: null, error: null });
  const onDataRef = useRef(onData);
  onDataRef.current = onData;
  const latest = useRef({ channel, params });
  latest.current = { channel, params };
  const paramsKey = JSON.stringify(params);

  useEffect(() => {
    if (status !== "connected") return;
    let scopeId: string | null = null;
    let cancelled = false;
    let off: (() => void) | null = null;
    let timer: number | null = null;

    void client
      .call(CMD.INTAN_SCOPE_OPEN, {
        kind,
        box,
        channel: latest.current.channel,
        params: latest.current.params,
      })
      .then((reply) => {
        if (cancelled) {
          void client.call(CMD.INTAN_SCOPE_CLOSE, { scopeId: reply.scopeId }).catch(() => undefined);
          return;
        }
        scopeId = reply.scopeId;
        off = store.onScope(scopeId, (data) => onDataRef.current(data));
        timer = window.setInterval(() => {
          if (scopeId) void client.call(CMD.INTAN_SCOPE_UPDATE, { scopeId }).catch(() => undefined);
        }, KEEPALIVE_MS);
        setHandle({ scopeId, error: null });
      })
      .catch((err: unknown) => {
        if (!cancelled) setHandle({ scopeId: null, error: messageOf(err) });
      });

    return () => {
      cancelled = true;
      off?.();
      if (timer !== null) window.clearInterval(timer);
      if (scopeId) void client.call(CMD.INTAN_SCOPE_CLOSE, { scopeId }).catch(() => undefined);
      setHandle({ scopeId: null, error: null });
    };
    // Reopened only when the view's identity changes; channel/params are
    // pushed by the effect below.
  }, [client, store, status, kind, box]);

  useEffect(() => {
    const scopeId = handle.scopeId;
    if (!scopeId) return;
    void client
      .call(CMD.INTAN_SCOPE_UPDATE, { scopeId, channel, params: latest.current.params })
      .then(() => setHandle((h) => (h.error ? { ...h, error: null } : h)))
      .catch((err: unknown) => setHandle((h) => ({ ...h, error: messageOf(err) })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, handle.scopeId, channel, paramsKey]);

  return handle;
}

export function messageOf(err: unknown): string {
  if (err && typeof err === "object" && "message" in err) {
    return String((err as { message: unknown }).message);
  }
  return String(err);
}
