/**
 * What the frontend needs from the sidecar: commands, events and the
 * connection's status, each typed from the generated protocol maps.
 *
 * Everything outside `SidecarProvider` depends on this rather than on
 * `SidecarClient`, the WebSocket adapter. `FakeSidecar` (`fakeSidecar.ts`) is
 * the second adapter, which store tests drive without a socket or a shell.
 */

import type {
  CommandArgsMap,
  CommandName,
  CommandResultMap,
  EventDataMap,
  EventMessage,
  EventName,
} from "./protocol";

export type ConnectionStatus =
  | "starting" // waiting for the shell to report the sidecar endpoint
  | "connecting"
  | "connected"
  | "reconnecting"
  | "down"; // sidecar exited or never started

export interface CallOptions {
  timeoutMs?: number;
}

/** A command's arguments, omittable only for commands that take none. */
export type CallRest<C extends CommandName> =
  Record<string, never> extends CommandArgsMap[C]
    ? [args?: CommandArgsMap[C], options?: CallOptions]
    : [args: CommandArgsMap[C], options?: CallOptions];

/** Handles one event, typed from the generated `EventDataMap`. */
export type EventHandler<E extends EventName> = (
  data: EventDataMap[E],
  message: EventMessage,
) => void;

export type StatusHandler = (status: ConnectionStatus) => void;

export interface SidecarPort {
  /**
   * Send a command and resolve with its result. Rejects with
   * `SidecarCommandError` when the sidecar refuses, which is the normal path
   * for an illegal state transition: the sidecar is the authority, not this
   * frontend.
   */
  call<C extends CommandName>(cmd: C, ...rest: CallRest<C>): Promise<CommandResultMap[C]>;
  /**
   * Subscribe to one event; returns the unsubscribe. Read `data` as given
   * rather than casting it: a cast to a hand-written shape compiles past the
   * drift this typing exists to catch.
   */
  on<E extends EventName>(evt: E, handler: EventHandler<E>): () => void;
  /** Called at once with the current status, then on every change. */
  onStatus(handler: StatusHandler): () => void;
  getStatus(): ConnectionStatus;
}
