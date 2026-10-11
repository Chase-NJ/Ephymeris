/**
 * The in-memory `SidecarPort` that store tests drive: the test plays the
 * sidecar. A call waits until the test answers it, so a test decides exactly
 * when each reply lands relative to each event. That ordering is what a store
 * gets wrong (`ARCHITECTURE.md#replay-on-connect`), and a real socket cannot
 * pin it.
 *
 * Imported only by tests; nothing in the app reaches it.
 */

import {
  PROTOCOL_VERSION,
  SidecarCommandError,
  type CommandArgsMap,
  type CommandName,
  type CommandResultMap,
  type ErrorCode,
  type EventDataMap,
  type EventMessage,
  type EventName,
} from "./protocol";
import type {
  CallRest,
  ConnectionStatus,
  EventHandler,
  SidecarPort,
  StatusHandler,
} from "./port";

interface WaitingCall {
  cmd: CommandName;
  args: unknown;
  resolve: (result: unknown) => void;
  reject: (error: unknown) => void;
}

type AnyEventHandler = (data: unknown, message: EventMessage) => void;

/** Let every continuation of a settled promise run. */
function settle(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export class FakeSidecar implements SidecarPort {
  private status: ConnectionStatus;
  private readonly waiting: WaitingCall[] = [];
  private readonly handlers = new Map<string, Set<AnyEventHandler>>();
  private readonly statusHandlers = new Set<StatusHandler>();

  constructor(status: ConnectionStatus = "connecting") {
    this.status = status;
  }

  // --- the port ----------------------------------------------------------

  call<C extends CommandName>(cmd: C, ...rest: CallRest<C>): Promise<CommandResultMap[C]>;
  call(cmd: CommandName, args: unknown = {}): Promise<unknown> {
    return new Promise((resolve, reject) => {
      this.waiting.push({ cmd, args, resolve, reject });
    });
  }

  on<E extends EventName>(evt: E, handler: EventHandler<E>): () => void {
    let handlers = this.handlers.get(evt);
    if (!handlers) {
      handlers = new Set();
      this.handlers.set(evt, handlers);
    }
    const stored = handler as AnyEventHandler;
    handlers.add(stored);
    return () => {
      handlers.delete(stored);
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

  // --- the test's side ---------------------------------------------------

  /** The arguments of every unanswered call to `cmd`, oldest first. */
  asked<C extends CommandName>(cmd: C): Array<CommandArgsMap[C]> {
    return this.waiting
      .filter((call) => call.cmd === cmd)
      .map((call) => call.args as CommandArgsMap[C]);
  }

  /** Answer the oldest unanswered call to `cmd`, and let its caller run. */
  async reply<C extends CommandName>(cmd: C, result: CommandResultMap[C]): Promise<void> {
    this.take(cmd).resolve(result);
    await settle();
  }

  /** Refuse the oldest unanswered call to `cmd`, as the sidecar would. */
  async refuse(
    cmd: CommandName,
    code: ErrorCode,
    message: string = code,
    detail: unknown = null,
  ): Promise<void> {
    this.take(cmd).reject(new SidecarCommandError({ code, message, detail }));
    await settle();
  }

  /** Broadcast an event to every subscriber. */
  emit<E extends EventName>(evt: E, data: EventDataMap[E]): void {
    const message: EventMessage = { v: PROTOCOL_VERSION, evt, ts: Date.now(), data };
    for (const handler of this.handlers.get(evt) ?? []) handler(data, message);
  }

  setStatus(status: ConnectionStatus): void {
    if (this.status === status) return;
    this.status = status;
    for (const handler of this.statusHandlers) handler(status);
  }

  /** How many handlers are subscribed to `evt`. */
  listeners(evt: EventName): number {
    return this.handlers.get(evt)?.size ?? 0;
  }

  private take(cmd: CommandName): WaitingCall {
    const index = this.waiting.findIndex((call) => call.cmd === cmd);
    if (index < 0) throw new Error(`no unanswered call to ${cmd}`);
    return this.waiting.splice(index, 1)[0]!;
  }
}
