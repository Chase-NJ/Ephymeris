/**
 * Typed wrappers over the session and prefix commands
 * (`PROTOCOL.md#prefixes-and-sessions`).
 */

import type { SidecarClient } from "../ws/client";
import { CMD } from "../ws/protocol";
import type {
  BoxMapping,
  Prefix,
  Session,
  SessionSnapshot,
  TaskProfile,
} from "./types";

export async function createPrefix(client: SidecarClient, name: string): Promise<Prefix> {
  const r = (await client.call(CMD.PREFIXES_CREATE, { name })) as { prefix: Prefix };
  return r.prefix;
}

export async function deletePrefix(client: SidecarClient, id: string): Promise<void> {
  await client.call(CMD.PREFIXES_DELETE, { id });
}

/**
 * A sketch's Task Profile, or null when it has none — which is fully supported
 * (`TASKS.md#task-profile`): bare `START`, raw strobe log instead of charts.
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
 * Step 1's pre-fill (`ARCHITECTURE.md#configuration`): the next numeric session number for this prefix,
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
  recording = false,
): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_CREATE, {
    cohortId,
    prefixId,
    sessionNumber,
    // Optional on the wire — omitted entirely means "no time limit".
    ...(durationMinutes !== undefined ? { durationMinutes } : {}),
    // Also an Intan recording (`RECORDING.md`). Omitted = behavior only.
    ...(recording ? { recording: true } : {}),
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

export async function startAll(client: SidecarClient, sessionId: string): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_START_ALL, { sessionId })) as {
    session: Session;
  };
  return r.session;
}

/**
 * End the group on the rig and leave the session BETWEEN GROUPS
 * (`ARCHITECTURE.md#group-step`): still running, held, no boxes. The operator then picks
 * the next group — any group — on the group step, or ends the session.
 */
export async function endGroup(client: SidecarClient, sessionId: string): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_END_GROUP, { sessionId })) as {
    session: Session;
  };
  return r.session;
}

/**
 * Continue one of today's sessions with another group — one the app closed on
 * between groups, or one ended too early. Never resumes a group mid-run.
 */
export async function resumeSession(
  client: SidecarClient,
  sessionId: string,
): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_RESUME, { sessionId })) as { session: Session };
  return r.session;
}

export async function endSession(client: SidecarClient, sessionId: string): Promise<Session> {
  const r = (await client.call(CMD.SESSIONS_END, { sessionId })) as { session: Session };
  return r.session;
}

/** Per-box Start — the command itself comes from the confirmed mapping. */
export async function startBox(client: SidecarClient, box: number): Promise<void> {
  await client.call(CMD.PORT_START_SESSION, { box });
}

/** Per-box Stop — sends `STOP`; the board's end strobe ends the run (`ARCHITECTURE.md#running-boxes`). */
export async function stopBox(client: SidecarClient, box: number): Promise<void> {
  await client.call(CMD.PORT_STOP_SESSION, { box });
}

/**
 * Flash one box as part of the session sequence (`ARCHITECTURE.md#flash-sequence`).
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
