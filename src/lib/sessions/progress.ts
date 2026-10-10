/**
 * Where a session stands on the rig — Mission Control's guided flow
 * (`ARCHITECTURE.md#running-boxes`).
 *
 * Derived only from what the sidecar reports, never from events this client
 * happened to see: live session events are not replayed on connect
 * (`ARCHITECTURE.md#replay-on-connect`), so a count of `session.animalEnded`
 * reads zero after a reload over a finished group, and a decision built on it
 * discards a session that ran or never offers the wrap-up.
 */

import type { Session, SessionBox } from "./types";

/**
 * Whether the session has run at all — the line between Discard and End.
 *
 * The sidecar moves a session out of `configuring` when any box starts, by
 * Start All or one box at a time, and `sessions.abandon` refuses every other
 * status. So this is exactly the question the sidecar will answer: anything
 * past `configuring` holds real runs and must be ended, never discarded.
 */
export function sessionHasRun(session: Pick<Session, "status"> | null): boolean {
  return session !== null && session.status !== "configuring";
}

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

/**
 * The group on the rig, box by box. `isLive` is the live port state
 * (`IN_SESSION`), which moves faster than a `sessions.status` snapshot; a box
 * live on the port is never counted as ended, whatever an older snapshot says.
 */
export function groupProgress(
  boxes: readonly Pick<SessionBox, "box" | "ended">[],
  isLive: (box: number) => boolean,
): GroupProgress {
  const total = boxes.length;
  const running = boxes.filter((b) => isLive(b.box)).length;
  const ended = boxes.filter((b) => b.ended && !isLive(b.box)).length;
  return {
    total,
    running,
    ended,
    allRunning: total > 0 && running === total,
    done: total > 0 && ended === total,
  };
}
