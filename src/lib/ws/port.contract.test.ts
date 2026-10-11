/**
 * What every `SidecarPort` adapter promises a store, run against both: the
 * production `SidecarClient` over a fake WebSocket and Tauri shell, and the
 * `FakeSidecar` the store tests drive. A store test proves something about the
 * app only while the fake behaves like the client, so the fake is held to
 * these same rules.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { SidecarClient } from "./client";
import { FakeSidecar } from "./fakeSidecar";
import type { ConnectionStatus, SidecarPort } from "./port";
import { CMD, ERR, EVT, PROTOCOL_VERSION, SidecarCommandError, type CommandName } from "./protocol";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async () => ({ port: 4242, token: "test-token" })),
}));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(async () => () => {}) }));

/** Let every continuation of a settled promise run. */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** A call's outcome, caught as it is made so a rejection is never unhandled. */
function outcome<T>(call: Promise<T>): Promise<{ ok: true; value: T } | { ok: false; error: unknown }> {
  return call.then(
    (value) => ({ ok: true as const, value }),
    (error: unknown) => ({ ok: false as const, error }),
  );
}

/** One adapter, and the sidecar's side of the conversation with it. */
interface Harness {
  port: SidecarPort;
  connect(): Promise<void>;
  answer(cmd: CommandName, result: unknown): Promise<void>;
  refuse(cmd: CommandName, code: string): Promise<void>;
  drop(): Promise<void>;
  emit(evt: string, data: unknown): void;
  dispose(): void;
}

// --- the production adapter, over a socket the test plays -----------------

class FakeSocket {
  static readonly OPEN = 1;
  static last: FakeSocket | null = null;
  readyState = 0;
  readonly sent: Array<{ id: string; cmd: string }> = [];
  private readonly answered = new Set<string>();
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(_url: string) {
    FakeSocket.last = this;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(): void {
    if (this.readyState === 3) return;
    this.readyState = 3;
    this.onclose?.();
  }

  // the sidecar's side
  open(): void {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  replyTo(cmd: string, reply: Record<string, unknown>): void {
    const call = this.sent.find((c) => c.cmd === cmd && !this.answered.has(c.id));
    if (!call) throw new Error(`no unanswered call to ${cmd}`);
    this.answered.add(call.id);
    this.receive({ v: PROTOCOL_VERSION, corr: call.id, ...reply });
  }
}

function clientHarness(): Harness {
  vi.stubGlobal("WebSocket", FakeSocket);
  const client = new SidecarClient();
  const socket = () => {
    if (!FakeSocket.last) throw new Error("the client never opened a socket");
    return FakeSocket.last;
  };
  return {
    port: client,
    async connect() {
      await client.start();
      socket().open();
      socket().replyTo(CMD.AUTH, { ok: true, result: { authenticated: true } });
      await settle();
    },
    async answer(cmd, result) {
      socket().replyTo(cmd, { ok: true, result });
      await settle();
    },
    async refuse(cmd, code) {
      socket().replyTo(cmd, { ok: false, error: { code, message: code, detail: null } });
      await settle();
    },
    async drop() {
      socket().close();
      await settle();
    },
    emit(evt, data) {
      socket().receive({ v: PROTOCOL_VERSION, evt, ts: 0, data });
    },
    dispose() {
      client.dispose();
      FakeSocket.last = null;
      vi.unstubAllGlobals();
    },
  };
}

// --- the test adapter ------------------------------------------------------

function fakeHarness(): Harness {
  const fake = new FakeSidecar("connecting");
  return {
    port: fake,
    async connect() {
      fake.setStatus("connected");
    },
    answer: (cmd, result) => fake.reply(cmd, result as never),
    refuse: (cmd, code) => fake.refuse(cmd, code as never),
    async drop() {
      fake.setStatus("reconnecting");
      await settle();
    },
    emit: (evt, data) => fake.emit(evt as never, data as never),
    dispose() {},
  };
}

// --- the contract ------------------------------------------------------------

describe.each([
  ["SidecarClient", clientHarness],
  ["FakeSidecar", fakeHarness],
])("%s", (_name, makeHarness) => {
  let harness: Harness;
  afterEach(() => harness.dispose());

  it("rejects a call made before it is connected", async () => {
    harness = makeHarness();
    expect((await outcome(harness.port.call(CMD.SESSIONS_ACTIVE))).ok).toBe(false);
  });

  it("resolves a call with the sidecar's answer", async () => {
    harness = makeHarness();
    await harness.connect();
    const asked = outcome(harness.port.call(CMD.SESSIONS_ACTIVE));
    await harness.answer(CMD.SESSIONS_ACTIVE, { running: null, configuring: [], stale: [] });
    expect(await asked).toEqual({ ok: true, value: { running: null, configuring: [], stale: [] } });
  });

  it("rejects a refused call with the sidecar's code", async () => {
    harness = makeHarness();
    await harness.connect();
    const asked = outcome(harness.port.call(CMD.SESSIONS_ACTIVE));
    await harness.refuse(CMD.SESSIONS_ACTIVE, ERR.SESSION_INVALID);
    const result = await asked;
    expect(result.ok).toBe(false);
    const error = (result as { error: unknown }).error;
    expect(error).toBeInstanceOf(SidecarCommandError);
    expect((error as SidecarCommandError).code).toBe(ERR.SESSION_INVALID);
  });

  it("fails every waiting call when the connection drops", async () => {
    harness = makeHarness();
    await harness.connect();
    const asked = outcome(harness.port.call(CMD.SESSIONS_ACTIVE));
    await harness.drop();
    expect((await asked).ok).toBe(false);
    expect(harness.port.getStatus()).toBe("reconnecting");
  });

  it("reports its status at once and on every change", async () => {
    harness = makeHarness();
    const heard: ConnectionStatus[] = [];
    harness.port.onStatus((status) => heard.push(status));
    expect(heard).toEqual([harness.port.getStatus()]);

    await harness.connect();
    await harness.drop();
    expect(heard.slice(-2)).toEqual(["connected", "reconnecting"]);
  });

  it("delivers an event to each subscriber until it unsubscribes", async () => {
    harness = makeHarness();
    await harness.connect();
    const first: unknown[] = [];
    const second: unknown[] = [];
    const stopFirst = harness.port.on(EVT.SESSION_LIFECYCLE, (data) => first.push(data));
    harness.port.on(EVT.SESSION_LIFECYCLE, (data) => second.push(data));
    const active = { running: null, configuring: [], stale: [] };

    harness.emit(EVT.SESSION_LIFECYCLE, active);
    stopFirst();
    harness.emit(EVT.SESSION_LIFECYCLE, active);

    expect(first).toEqual([active]);
    expect(second).toEqual([active, active]);
  });
});
