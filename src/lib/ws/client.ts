/**
 * WebSocket client for the Python sidecar.
 *
 * Owns endpoint discovery (via the Tauri shell), authentication, request/reply
 * correlation, event fan-out, and reconnection with backoff. Consumers observe
 * `onStatus` and react to `connected` — that is the hook the settings push
 * required by `ephymeris_v1.0.md` §4.5 hangs off.
 */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import {
  CMD,
  PROTOCOL_VERSION,
  SidecarCommandError,
  isEvent,
  isReply,
  type EventMessage,
  type ServerMessage,
} from "./protocol";

export type ConnectionStatus =
  | "starting" // waiting for the shell to report the sidecar endpoint
  | "connecting"
  | "connected"
  | "reconnecting"
  | "down"; // sidecar exited or never started

export interface SidecarEndpoint {
  port: number;
  token: string;
}

type EventHandler = (data: unknown, message: EventMessage) => void;
type StatusHandler = (status: ConnectionStatus) => void;

function readManualEndpoint(): SidecarEndpoint | null {
  try {
    const raw = window.localStorage.getItem("ephymeris:endpoint");
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { port?: unknown; token?: unknown };
    if (typeof parsed.port === "number" && typeof parsed.token === "string") {
      return { port: parsed.port, token: parsed.token };
    }
  } catch {
    /* malformed or storage unavailable — behave as if unset */
  }
  return null;
}

/** Reply timeout for ordinary commands. */
const DEFAULT_CALL_TIMEOUT_MS = 15_000;

/**
 * Per-command timeout overrides for work that legitimately runs long. A compile
 * plus upload routinely outlasts the default, and cutting the promise while
 * `arduino-cli` still owns the port would leave the UI disagreeing with the
 * sidecar about what state the port is in.
 */
const CALL_TIMEOUT_OVERRIDES: Readonly<Record<string, number>> = {
  [CMD.PORT_FLASH]: 300_000,
  [CMD.SKETCHES_REFRESH]: 60_000,
};

const BACKOFF_MS = [250, 500, 1_000, 2_000, 4_000, 8_000] as const;

export class SidecarClient {
  private ws: WebSocket | null = null;
  private endpoint: SidecarEndpoint | null = null;
  private status: ConnectionStatus = "starting";
  private attempt = 0;
  private nextId = 0;
  private disposed = false;
  /**
   * Bumped on every start/dispose. Async work started under one generation must
   * not act once a newer one has begun — without this, StrictMode's
   * mount→unmount→remount lets the first mount's in-flight endpoint lookup
   * resolve after the remount and open a second, orphaned socket.
   */
  private generation = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly unlisteners: Array<() => void> = [];

  private readonly pending = new Map<
    string,
    { resolve: (v: unknown) => void; reject: (e: unknown) => void; timer: ReturnType<typeof setTimeout> }
  >();
  private readonly eventHandlers = new Map<string, Set<EventHandler>>();
  private readonly statusHandlers = new Set<StatusHandler>();

  // --- lifecycle ----------------------------------------------------------

  /**
   * Idempotent and re-runnable: StrictMode mounts, unmounts, then remounts in
   * development, so `start` after a `dispose` has to produce a live client
   * again rather than a permanently dead one.
   */
  async start(): Promise<void> {
    this.disposed = false;
    this.attempt = 0;
    const generation = ++this.generation;

    // The shell may already have the endpoint if the sidecar booted before the
    // webview did; otherwise the ready event delivers it.
    try {
      this.track(
        listen<SidecarEndpoint>("sidecar://ready", (e) => {
          this.endpoint = e.payload;
          this.attempt = 0;
          this.open();
        }),
        generation,
      );
      this.track(
        listen("sidecar://down", () => {
          this.endpoint = null;
          this.setStatus("down");
        }),
        generation,
      );
    } catch (err) {
      console.error("could not subscribe to shell events", err);
    }

    try {
      const existing = await invoke<SidecarEndpoint | null>("sidecar_endpoint");
      if (existing && generation === this.generation) {
        this.endpoint = existing;
        this.open();
      }
    } catch (err) {
      if (generation !== this.generation) return;

      // Dev-only fallback: with no Tauri shell (plain-browser preview), allow a
      // manually supplied endpoint so the full UI can be driven against a
      // standalone sidecar:
      //   localStorage.setItem("ephymeris:endpoint", '{"port":NNN,"token":"…"}')
      // localStorage rather than URL params on purpose — the protocol doc's
      // rule that the token never rides in a URL applies in dev too.
      if (import.meta.env.DEV) {
        const manual = readManualEndpoint();
        if (manual) {
          console.info("using manual sidecar endpoint from localStorage (dev only)");
          this.endpoint = manual;
          this.open();
          return;
        }
      }

      console.error("could not query sidecar endpoint", err);
      this.setStatus("down");
    }
  }

  dispose(): void {
    this.generation += 1;
    this.disposed = true;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    for (const unlisten of this.unlisteners.splice(0)) unlisten();
    const ws = this.ws;
    this.ws = null;
    ws?.close();
    this.failAllPending(new Error("client disposed"));
  }

  /** Keep hold of a Tauri unlisten fn, honouring a dispose that beat it home. */
  private track(pending: Promise<() => void>, generation: number): void {
    void pending.then((unlisten) => {
      if (generation !== this.generation) unlisten();
      else this.unlisteners.push(unlisten);
    });
  }

  private open(): void {
    if (this.disposed || !this.endpoint) return;
    this.ws?.close();

    this.setStatus(this.attempt === 0 ? "connecting" : "reconnecting");
    const ws = new WebSocket(`ws://127.0.0.1:${this.endpoint.port}`);
    this.ws = ws;

    ws.onopen = () => void this.authenticate();
    ws.onmessage = (ev) => this.onMessage(ev);
    ws.onerror = () => {
      /* onclose always follows; handled there */
    };
    ws.onclose = () => {
      if (this.ws !== ws) return; // superseded by a newer socket
      this.ws = null;
      this.failAllPending(new Error("sidecar connection closed"));
      this.scheduleReconnect();
    };
  }

  private async authenticate(): Promise<void> {
    if (!this.endpoint) return;
    try {
      await this.call(CMD.AUTH, { token: this.endpoint.token });
      this.attempt = 0;
      this.setStatus("connected");
    } catch (err) {
      console.error("sidecar authentication failed", err);
      this.ws?.close();
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed || !this.endpoint) {
      this.setStatus("down");
      return;
    }
    this.setStatus("reconnecting");
    const delay = BACKOFF_MS[Math.min(this.attempt, BACKOFF_MS.length - 1)] ?? 8_000;
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }

  // --- messaging ----------------------------------------------------------

  /**
   * Send a command and resolve with its result.
   *
   * Rejects with {@link SidecarCommandError} when the sidecar refuses — which
   * is the normal path for illegal state transitions, since the sidecar is the
   * authority on port state, not this frontend.
   */
  call(
    cmd: string,
    args: Record<string, unknown> = {},
    options: { timeoutMs?: number } = {},
  ): Promise<unknown> {
    const ws = this.ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("sidecar is not connected"));
    }

    const timeoutMs =
      options.timeoutMs ?? CALL_TIMEOUT_OVERRIDES[cmd] ?? DEFAULT_CALL_TIMEOUT_MS;
    const id = `c${(this.nextId += 1)}`;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`command timed out: ${cmd}`));
      }, timeoutMs);

      this.pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ v: PROTOCOL_VERSION, id, cmd, args }));
    });
  }

  private onMessage(ev: MessageEvent): void {
    let msg: ServerMessage;
    try {
      msg = JSON.parse(String(ev.data)) as ServerMessage;
    } catch {
      console.error("unparseable frame from sidecar", ev.data);
      return;
    }

    if (isReply(msg)) {
      const entry = this.pending.get(msg.corr);
      if (!entry) return;
      this.pending.delete(msg.corr);
      clearTimeout(entry.timer);
      if (msg.ok) entry.resolve(msg.result);
      else entry.reject(new SidecarCommandError(msg.error));
      return;
    }

    if (isEvent(msg)) {
      const handlers = this.eventHandlers.get(msg.evt);
      if (!handlers) return;
      for (const handler of handlers) {
        try {
          handler(msg.data, msg);
        } catch (err) {
          console.error(`handler for ${msg.evt} threw`, err);
        }
      }
    }
  }

  private failAllPending(reason: Error): void {
    for (const [, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(reason);
    }
    this.pending.clear();
  }

  // --- subscriptions ------------------------------------------------------

  on(evt: string, handler: EventHandler): () => void {
    let handlers = this.eventHandlers.get(evt);
    if (!handlers) {
      handlers = new Set();
      this.eventHandlers.set(evt, handlers);
    }
    handlers.add(handler);
    return () => {
      handlers.delete(handler);
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.status);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  getStatus(): ConnectionStatus {
    return this.status;
  }

  private setStatus(status: ConnectionStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const handler of this.statusHandlers) handler(status);
  }
}
