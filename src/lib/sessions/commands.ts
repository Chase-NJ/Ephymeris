/**
 * Typed wrappers over the session and prefix commands
 * (`websocket-protocol.md` §3.2).
 */

import type { SidecarClient } from "../ws/client";
import { CMD } from "../ws/protocol";
import type {
  ActiveSessions,
  BoxMapping,
  Prefix,
  Session,
  SessionSnapshot,
  TaskProfile,
} from "./types";

export async function listPrefixes(client: SidecarClient): Promise<Prefix[]> {
  const r = (await client.call(CMD.PREFIXES_LIST)) as { prefixes: Prefix[] };
  return r.prefixes;
}

export async function createPrefix(client: SidecarClient, name: string): Promise<Prefix> {
  const r = (await client.call(CMD.PREFIXES_CREATE, { name })) as { prefix: Prefix };
  return r.prefix;
}

export async function deletePrefix(client: SidecarClient, id: string): Promise<void> {
  await client.call(CMD.PREFIXES_DELETE, { id });
}

/**
 * A sketch's Task Profile, or null when it has none — which is fully supported
 * (`data-saving.md` §6.1): bare `START`, raw strobe log instead of charts.
 */
export async function getTaskProfile(
  client: SidecarClient,
  sketchPath: string,
): Promise<TaskProfile | null> {
  const r = (await client.call(CMD.TASKS_GET_PROFILE, { sketchPath })) as
    | TaskProfile
    | { profile: null };
  return "profile" in r && r.profile === null ? null : (r as TaskProfile);
}

/**
 * Step 1's pre-fill (§2.2): the next numeric session number for this prefix,
 * plus the numbers already used today — the latter drives a *soft* warning,
 * never a block.
 */
export async function suggestSessionNumber(
  client: SidecarClient,
  prefixId: string,
): Promise<{ suggestion: string | null; sameDayNumbers: string[] }> {
  const r = (await client.call(CMD.SESSIONS_SUGGEST_NUMBER, { prefixId })) as {
    suggestion: string | null;
    sameDayNumbers: string[];
  };
  return { suggestion: r.suggestion, sameDayNumbers: r.sameDayNumbers ?? [] };
}

export async function createSession(
  client: SidecarClient,
  cohortId: string,
  prefixId: string,
  sessionNumber: string,
  durationMinutes?: number,
): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_CREATE, {
    cohortId,
    prefixId,
    sessionNumber,
    // Optional on the wire — omitted entirely means "no time limit".
    ...(durationMinutes !== undefined ? { durationMinutes } : {}),
  })) as { session: Session };
  return r.session;
}

/**
 * Discard a session still in `configuring` (Step 2's Back) — marks it
 * `aborted` instead of stranding the record. Rejected once a group has run.
 */
export async function abandonSession(
  client: SidecarClient,
  sessionId: string,
): Promise<void> {
  await client.call(CMD.SESSIONS_ABANDON, { sessionId });
}

export async function confirmMapping(
  client: SidecarClient,
  sessionId: string,
  groupId: string,
  boxes: BoxMapping[],
): Promise<void> {
  await client.call(CMD.SESSIONS_CONFIRM_MAPPING, {
    sessionId,
    groupId,
    boxes: boxes.map((b) => ({
      box: b.box,
      animalId: b.animalId,
      // The flow only enables Confirm once every box has a sketch; an empty
      // string still draws the same SESSION_INVALID rejection a null did.
      sketchPath: b.sketchPath ?? "",
      config: b.config,
    })),
  });
}

/**
 * What Mission Control renders. Asked of the sidecar rather than carried in
 * router state, so reopening the window mid-session shows what's actually
 * running instead of a stale copy.
 */
export async function sessionStatus(
  client: SidecarClient,
  sessionId: string,
): Promise<SessionSnapshot> {
  return (await client.call(CMD.SESSIONS_STATUS, { sessionId })) as SessionSnapshot;
}

/**
 * The global "what is running?" query — no arguments, so a client with no
 * prior knowledge of ids (the Launch page, a reconnect) can discover the
 * running session. The store calls this on every connect; `session.lifecycle`
 * keeps the answer current thereafter.
 */
export async function activeSessions(client: SidecarClient): Promise<ActiveSessions> {
  return (await client.call(CMD.SESSIONS_ACTIVE)) as ActiveSessions;
}

export async function startAll(client: SidecarClient, sessionId: string): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_START_ALL, { sessionId })) as {
    session: Session;
  };
  return r.session;
}

export async function switchGroup(
  client: SidecarClient,
  sessionId: string,
): Promise<string | null> {
  const r = (await client.call(CMD.SESSIONS_SWITCH_GROUP, { sessionId })) as {
    nextGroupId: string | null;
  };
  return r.nextGroupId;
}

export async function endSession(client: SidecarClient, sessionId: string): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_END, { sessionId })) as { session: Session };
  return r.session;
}

/** Per-box Start — the command itself comes from the confirmed mapping. */
export async function startBox(client: SidecarClient, box: number): Promise<void> {
  await client.call(CMD.PORT_START_SESSION, { box });
}

/** Per-box Stop — sends `STOP`; the board's end strobe ends the run (§5.3). */
export async function stopBox(client: SidecarClient, box: number): Promise<void> {
  await client.call(CMD.PORT_STOP_SESSION, { box });
}

/**
 * Flash one box as part of the session sequence (§4).
 *
 * `suppressPassthroughResume` is what makes the box land in `IDLE` so the
 * runner can claim it — the opposite of Debug Mode's auto-resume.
 */
export async function flashForSession(
  client: SidecarClient,
  box: number,
  sketchPath: string,
): Promise<void> {
  await client.call(CMD.PORT_FLASH, {
    box,
    sketchPath,
    suppressPassthroughResume: true,
  });
}
