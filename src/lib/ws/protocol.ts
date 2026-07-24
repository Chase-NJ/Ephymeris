/**
 * Canonical wire protocol between this frontend and the Python sidecar.
 *
 * `docs/websocket-protocol.md` is the source of truth; this module and
 * `sidecar/ephymeris_sidecar/protocol.py` are hand-maintained mirrors of it.
 * The sidecar's `tests/test_protocol_contract.py` asserts the two agree on
 * command and event names.
 */

export const PROTOCOL_VERSION = 1;

// --- Commands (client -> server) -------------------------------------------

export const CMD = {
  AUTH: "auth",
  PING: "ping",
  SETTINGS_PUSH: "settings.push",
  SKETCHES_REFRESH: "sketches.refresh",
  PORT_PASSTHROUGH_OPEN: "port.passthrough.open",
  PORT_PASSTHROUGH_CLOSE: "port.passthrough.close",
  PORT_SEND: "port.send",
  PORT_FLASH: "port.flash",
  PORT_RESET: "port.reset",
  PORT_ERROR_ACK: "port.error.ack",

  // Cohorts (cohorts.md §10, merged into websocket-protocol.md §3.1)
  COHORTS_LIST: "cohorts.list",
  COHORTS_GET: "cohorts.get",
  COHORTS_CREATE: "cohorts.create",
  COHORTS_UPDATE: "cohorts.update",
  COHORTS_ARCHIVE: "cohorts.archive",
  COHORTS_RESTORE: "cohorts.restore",
  COHORTS_DELETE: "cohorts.delete",
  COHORTS_SET_DATA_FOLDER: "cohorts.setDataFolder",
  COHORTS_SUGGEST_GROUPS: "cohorts.suggestGroups",

  // Prefixes, task profiles, sessions
  // (data-saving.md §9 + starting-a-session.md §9, merged into
  // websocket-protocol.md §3.2)
  PREFIXES_LIST: "prefixes.list",
  PREFIXES_CREATE: "prefixes.create",
  PREFIXES_DELETE: "prefixes.delete",
  TASKS_GET_PROFILE: "tasks.getProfile",
  SESSIONS_SUGGEST_NUMBER: "sessions.suggestNumber",
  SESSIONS_CREATE: "sessions.create",
  SESSIONS_CONFIRM_MAPPING: "sessions.confirmMapping",
  SESSIONS_STATUS: "sessions.status",
  SESSIONS_START_ALL: "sessions.startAll",
  SESSIONS_SWITCH_GROUP: "sessions.switchGroup",
  SESSIONS_END: "sessions.end",
  PORT_START_SESSION: "port.startSession",
  PORT_STOP_SESSION: "port.stopSession",
} as const;

export type CommandName = (typeof CMD)[keyof typeof CMD];

// --- Events (server -> client) ---------------------------------------------

export const EVT = {
  SERVER_HELLO: "server.hello",
  PORT_STATE: "port.state",
  PORT_OUTPUT: "port.output",
  BOARDS_PRESENCE: "boards.presence",
  FLASH_PROGRESS: "flash.progress",
  SKETCHES_UPDATED: "sketches.updated",
  COHORTS_UPDATED: "cohorts.updated",
  PREFIXES_UPDATED: "prefixes.updated",
  SESSION_TELEMETRY: "session.telemetry",
  SESSION_ANIMAL_ENDED: "session.animalEnded",
  SIDECAR_ERROR: "sidecar.error",
} as const;

export type EventName = (typeof EVT)[keyof typeof EVT];

// --- Error codes -----------------------------------------------------------

export const ERR = {
  BAD_MESSAGE: "BAD_MESSAGE",
  UNKNOWN_COMMAND: "UNKNOWN_COMMAND",
  UNAUTHORIZED: "UNAUTHORIZED",
  PROTOCOL_VERSION_MISMATCH: "PROTOCOL_VERSION_MISMATCH",
  ILLEGAL_TRANSITION: "ILLEGAL_TRANSITION",
  SEND_NOT_PASSTHROUGH: "SEND_NOT_PASSTHROUGH",
  PORT_NOT_BOUND: "PORT_NOT_BOUND",
  PORT_OPEN_FAILED: "PORT_OPEN_FAILED",
  FLASH_FAILED: "FLASH_FAILED",
  SKETCH_UNKNOWN: "SKETCH_UNKNOWN",
  COHORT_NOT_FOUND: "COHORT_NOT_FOUND",
  COHORT_NAME_TAKEN: "COHORT_NAME_TAKEN",
  COHORT_INVALID: "COHORT_INVALID",
  COHORT_NOT_ARCHIVED: "COHORT_NOT_ARCHIVED",
  DATA_FOLDER_INVALID: "DATA_FOLDER_INVALID",
  PREFIX_NAME_TAKEN: "PREFIX_NAME_TAKEN",
  SESSION_INVALID: "SESSION_INVALID",
  SESSION_NOT_READY: "SESSION_NOT_READY",
  TASK_PROFILE_INVALID: "TASK_PROFILE_INVALID",
  DIR_INVALID: "DIR_INVALID",
  INTERNAL: "INTERNAL",
} as const;

export type ErrorCode = (typeof ERR)[keyof typeof ERR];

// --- Envelopes -------------------------------------------------------------

export interface CommandMessage {
  v: number;
  id: string;
  cmd: string;
  args: Record<string, unknown>;
}

export interface ProtocolError {
  code: ErrorCode | string;
  message: string;
  detail?: unknown;
}

export interface ReplyOk {
  v: number;
  corr: string;
  ok: true;
  result: unknown;
}

export interface ReplyErr {
  v: number;
  corr: string;
  ok: false;
  error: ProtocolError;
}

export type Reply = ReplyOk | ReplyErr;

export interface EventMessage {
  v: number;
  evt: string;
  ts: number;
  data: unknown;
  corr?: string;
}

export type ServerMessage = Reply | EventMessage;

export function isEvent(msg: ServerMessage): msg is EventMessage {
  return "evt" in msg;
}

export function isReply(msg: ServerMessage): msg is Reply {
  return "corr" in msg && "ok" in msg;
}

/** Thrown by `SidecarClient.call` when the sidecar rejects a command. */
export class SidecarCommandError extends Error {
  readonly code: string;
  readonly detail: unknown;

  constructor(error: ProtocolError) {
    super(error.message);
    this.name = "SidecarCommandError";
    this.code = error.code;
    this.detail = error.detail;
  }
}
