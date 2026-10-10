/**
 * Where a session stands in the guided flow, and where each step lives
 * (`ARCHITECTURE.md#the-flow`).
 *
 * Pure: every answer here is derived from what the sidecar reports — the
 * session record, whether it holds the rig, the runner's boxes — and the live
 * port state, never from events this client happened to see. Live session
 * events are not replayed on connect (`ARCHITECTURE.md#replay-on-connect`), so
 * a count of `session.animalEnded` reads zero after a reload over a finished
 * group, and a decision built on it discards a session that ran or never
 * offers the wrap-up. `useSessionFlow` gathers the facts; the step routes
 * render the answers.
 */

import type { Cohort } from "@/lib/cohorts/types";

import {
  groupRunsFor,
  groupsRunCount,
  populatedGroups,
  type Session,
  type SessionBox,
  type SessionSnapshot,
} from "./types";

// --- step URLs ------------------------------------------------------------

/**
 * Every guided step's URL. The session record carries its cohort, so no step
 * needs it in the URL; Boxes and Record carry the group, which before a
 * mapping is confirmed is the operator's choice and nothing the sidecar holds.
 */
export const stepUrl = {
  configure: () => "/session/new",
  group: (sessionId: string) => `/session/${sessionId}/group`,
  boxes: (sessionId: string, groupId: string) =>
    `/session/${sessionId}/mapping?group=${encodeURIComponent(groupId)}`,
  record: (sessionId: string, groupId: string) =>
    `/session/${sessionId}/recording?group=${encodeURIComponent(groupId)}`,
  control: (sessionId: string) => `/session/${sessionId}/control`,
};

/**
 * Where the way back into a held session leads: Mission Control while a group
 * is on the rig, the group step while it is between groups
 * (`ARCHITECTURE.md#group-step`) — an empty cockpit is not the next step there.
 */
export function sessionDoor(running: Pick<SessionSnapshot, "session" | "groupId">): string {
  const id = running.session.id;
  return running.groupId ? stepUrl.control(id) : stepUrl.group(id);
}

// --- the flow -------------------------------------------------------------

export interface GroupProgress {
  /** Boxes of the group on the rig. */
  total: number;
  /** Boxes recording right now, on the live port state. */
  running: number;
  /** Boxes whose run this group has finished, on the runner's `ended`. */
  ended: number;
  allRunning: boolean;
  /** Every box finished and none running — the group is done. */
  done: boolean;
}

/** The group a step is about, for the journey rail's chip. */
export interface GroupChip {
  name: string;
  /** Populated groups that have run in this session, this one included. */
  ran: number;
  count: number;
}

export interface FlowFacts {
  session: Session | null;
  cohort: Cohort | null;
  /** This session holds the rig (`sessions.active`'s running slot). */
  held: boolean;
  /** The group on the rig; null unless held with a group mapped. */
  rigGroupId: string | null;
  /** The rig's boxes; empty unless held. */
  boxes: readonly Pick<SessionBox, "box" | "ended">[];
  /**
   * The group a step is about, when it is not the one on the rig — Boxes and
   * Record name theirs in the URL. Defaults to the rig's.
   */
  groupId?: string | null;
  /**
   * The live port state (`IN_SESSION`), which moves faster than a
   * `sessions.status` snapshot; a box live on the port is never counted as
   * ended, whatever an older snapshot says.
   */
  isLive: (box: number) => boolean;
}

export interface SessionFlow {
  /** `prefix_number`, or null before the record arrives. */
  name: string | null;
  /**
   * Whether the session has run at all — the line between Discard and End.
   * The sidecar moves a session out of `configuring` when any box starts, and
   * `sessions.abandon` refuses every other status, so this is exactly the
   * question the sidecar will answer.
   */
  hasRun: boolean;
  /** Also an Intan recording (`RECORDING.md`), on the record — never the URL. */
  isRecording: boolean;
  progress: GroupProgress;
  /** The cohort has more than one populated group, so switching means something. */
  multiGroup: boolean;
  /** The group this step is about; null unless multi-group. */
  group: GroupChip | null;
  /**
   * Populated groups yet to run in this session, besides the one this step is
   * about. There is no run order, so this is all "last group" can mean.
   */
  groupsWaiting: number;
  /**
   * None waiting: a finished group's natural next step is the wrap-up rather
   * than another group. False until the cohort is known, so the wrap-up never
   * opens on a cohort whose other groups have not been counted.
   */
  lastGroup: boolean;
  /**
   * Reached with a mapping that was never confirmed — a deep link, a reload
   * mid-setup, Back from a partial flash. Still `configuring` with no boxes on
   * the rig is what tells it from a confirmed session not yet started.
   */
  neverConfirmed: boolean;
  /**
   * Where a held session belongs: Mission Control with a group on the rig,
   * the group step between groups. Null for a session that does not hold the
   * rig, which has no fixed place.
   */
  rigStep: "control" | "group" | null;
  /** The finished last group of a session that ran — time for the wrap-up. */
  wrapUpDue: boolean;
}

export function sessionFlow(facts: FlowFacts): SessionFlow {
  const { session, cohort, held, rigGroupId, boxes, isLive } = facts;
  const groupId = facts.groupId ?? rigGroupId;

  const total = boxes.length;
  const running = boxes.filter((b) => isLive(b.box)).length;
  const ended = boxes.filter((b) => b.ended && !isLive(b.box)).length;
  const progress: GroupProgress = {
    total,
    running,
    ended,
    allRunning: total > 0 && running === total,
    done: total > 0 && ended === total,
  };

  const groups = cohort ? populatedGroups(cohort) : [];
  const found = groups.find((g) => g.id === groupId);
  const group =
    cohort && found && groups.length > 1
      ? { name: found.name, ran: groupsRunCount(cohort, session), count: groups.length }
      : null;
  const groupsWaiting = groups.filter(
    (g) => g.id !== groupId && groupRunsFor(session, g.id).length === 0,
  ).length;
  const lastGroup = cohort !== null && groupsWaiting === 0;

  const hasRun = session !== null && session.status !== "configuring";
  const rigStep = !held
    ? null
    : rigGroupId
      ? "control"
      : session?.status === "running"
        ? "group"
        : null;

  return {
    name: session ? `${session.prefixName}_${session.sessionNumber}` : null,
    hasRun,
    isRecording: session?.recording != null,
    progress,
    multiGroup: groups.length > 1,
    group,
    groupsWaiting,
    lastGroup,
    neverConfirmed: session?.status === "configuring" && total === 0,
    rigStep,
    wrapUpDue: progress.done && lastGroup && hasRun,
  };
}

/** Mission Control's rail line — always the single next action. */
export function missionControlHint(flow: SessionFlow, connected: boolean): string {
  const { progress } = flow;
  if (!connected) return "Waiting for the hardware service…";
  if (flow.neverConfirmed) return "This session hasn't started — finish box confirmation first.";
  if (progress.total === 0) {
    // Only name actions that exist: Switch Group is a multi-group control.
    return flow.multiGroup
      ? "No boxes in this group — switch group or end the session."
      : "No boxes in this group — end the session.";
  }
  if (progress.done) {
    return flow.lastGroup
      ? "All boxes finished — End Session saves and wraps up."
      : "Group finished — pick the next group, or end the session.";
  }
  if (progress.running > 0) return "Recording — Stop takes effect at the next trial boundary.";
  if (progress.ended === 0) return "Animals in their boxes? Start All begins recording.";
  return "Start the remaining boxes, or switch group.";
}
