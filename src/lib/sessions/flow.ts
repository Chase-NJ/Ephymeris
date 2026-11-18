/**
 * Where a session stands in the guided flow, and where each step lives
 * (`ARCHITECTURE.md#the-flow`).
 *
 * Pure: every answer here is derived from what the sidecar reports — the
 * session record, whether it holds the rig, the runner's boxes — and the live
 * port state, never from events this client happened to see. Live session
 * events are not replayed on connect (`ARCHITECTURE.md#replay-on-connect`), so
 * a count of `session.animalEnded` reads zero after a reload over a finished
 * round, and a decision built on it discards a session that ran or never
 * offers the wrap-up. `useSessionFlow` gathers the facts; the step routes
 * render the answers.
 */

import type { Session, SessionBox, SessionSnapshot } from "./types";

// --- step URLs ------------------------------------------------------------

/** Every guided step's URL. The session record carries its cohort, so no step needs it in the URL. */
export const stepUrl = {
  configure: () => "/session/new",
  boxes: (sessionId: string) => `/session/${sessionId}/mapping`,
  record: (sessionId: string) => `/session/${sessionId}/recording`,
  control: (sessionId: string) => `/session/${sessionId}/control`,
};

/**
 * Where the way back into a held session leads: Mission Control while a round
 * is on the rig, the Boxes step while it is between rounds
 * (`ARCHITECTURE.md#between-rounds`) — an empty cockpit is not the next step there.
 */
export function sessionDoor(running: Pick<SessionSnapshot, "session" | "boxes">): string {
  const id = running.session.id;
  return running.boxes.length > 0 ? stepUrl.control(id) : stepUrl.boxes(id);
}

// --- the flow -------------------------------------------------------------

export interface RoundProgress {
  /** Boxes of the round on the rig. */
  total: number;
  /** Boxes recording right now, on the live port state. */
  running: number;
  /** Boxes whose run this round has finished, on the runner's `ended`. */
  ended: number;
  allRunning: boolean;
  /** Every box finished and none running — the round is done. */
  done: boolean;
}

export interface FlowFacts {
  session: Session | null;
  /** This session holds the rig (`sessions.active`'s running slot). */
  held: boolean;
  /** The rig's boxes; empty unless held with a round mapped. */
  boxes: readonly Pick<SessionBox, "box" | "ended">[];
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
  progress: RoundProgress;
  /**
   * The round this step is about, 1-based: the one on the rig once it has
   * started, otherwise the one being set up.
   */
  round: number;
  /**
   * Reached with a mapping that was never confirmed — a deep link, a reload
   * mid-setup, Back from a partial flash. Still `configuring` with no boxes on
   * the rig is what tells it from a confirmed session not yet started.
   */
  neverConfirmed: boolean;
  /**
   * Where a held session belongs: Mission Control with a round on the rig,
   * the Boxes step between rounds. Null for a session that does not hold the
   * rig, which has no fixed place.
   */
  rigStep: "control" | "boxes" | null;
  /**
   * The round on the rig has finished: time to ask whether more animals run
   * or the session ends (`ARCHITECTURE.md#between-rounds`).
   */
  roundOver: boolean;
}

export function sessionFlow(facts: FlowFacts): SessionFlow {
  const { session, held, boxes, isLive } = facts;

  const total = boxes.length;
  const running = boxes.filter((b) => isLive(b.box)).length;
  const ended = boxes.filter((b) => b.ended && !isLive(b.box)).length;
  const progress: RoundProgress = {
    total,
    running,
    ended,
    allRunning: total > 0 && running === total,
    done: total > 0 && ended === total,
  };

  const rounds = session?.rounds ?? [];
  const open = rounds.some((r) => r.endedAt === null);
  const hasRun = session !== null && session.status !== "configuring";
  const rigStep = !held
    ? null
    : total > 0
      ? "control"
      : session?.status === "running"
        ? "boxes"
        : null;

  return {
    name: session ? `${session.prefixName}_${session.sessionNumber}` : null,
    hasRun,
    isRecording: session?.recording != null,
    progress,
    round: open ? rounds.length : rounds.length + 1,
    neverConfirmed: session?.status === "configuring" && total === 0,
    rigStep,
    roundOver: progress.done && hasRun,
  };
}

/** Mission Control's rail line — always the single next action. */
export function missionControlHint(flow: SessionFlow, connected: boolean): string {
  const { progress } = flow;
  if (!connected) return "Waiting for the hardware service…";
  if (flow.neverConfirmed) return "This session hasn't started — finish box confirmation first.";
  if (progress.total === 0) return "No boxes on the rig — set up the next round, or end the session.";
  if (progress.done) return "Every box finished — run more animals, or end the session.";
  if (progress.running > 0) return "Recording — Stop takes effect at the next trial boundary.";
  if (progress.ended === 0) return "Animals in their boxes? Start All begins recording.";
  return "Start the remaining boxes, or end the round.";
}
