/**
 * What the Boxes step shows for each mapped box's flash, read from the
 * sidecar's flash queue (`ARCHITECTURE.md#flash-sequence`). The queue lives in
 * the sidecar, so these cards survive leaving the page; this only translates
 * its snapshot into the step's words.
 */

import type { FlashQueueStatus } from "../ws/protocol";

/** `queued` covers a job still waiting for its port: either way, not yet. */
export type FlashCardState = "idle" | "queued" | "flashing" | "done" | "failed";

export interface FlashCard {
  state: FlashCardState;
  /** Why it waits or failed, in the sidecar's words. */
  detail: string | null;
}

export interface SessionFlashes {
  cards: ReadonlyMap<number, FlashCard>;
  flashedCount: number;
  /** Every mapped box is flashed for this mapping. */
  allFlashed: boolean;
  /** Some mapped box is queued, waiting or flashing. */
  pending: boolean;
}

const IDLE: FlashCard = { state: "idle", detail: null };

/**
 * One card per mapped box. Only a `session` job counts: a Debug flash or a
 * restore of the same box says nothing about this mapping, and the sidecar
 * clears the session's rows whenever a mapping is confirmed. `null` (no
 * mapping confirmed on this screen yet) reads every box as idle.
 */
export function sessionFlashCards(
  status: FlashQueueStatus | null,
  boxes: readonly number[],
): SessionFlashes {
  const rows = new Map((status?.boxes ?? []).map((row) => [row.box, row.job]));
  const cards = new Map<number, FlashCard>();
  for (const box of boxes) {
    const job = rows.get(box);
    if (!job || job.origin !== "session") {
      cards.set(box, IDLE);
      continue;
    }
    const state: FlashCardState = job.state === "waiting" ? "queued" : job.state;
    cards.set(box, { state, detail: job.detail });
  }
  const states = boxes.map((box) => cards.get(box)!.state);
  const flashedCount = states.filter((s) => s === "done").length;
  return {
    cards,
    flashedCount,
    allFlashed: boxes.length > 0 && flashedCount === boxes.length,
    pending: states.some((s) => s === "queued" || s === "flashing"),
  };
}

/**
 * Where a walk that left this step mid-way picks up again: the first box, in
 * walk order, that no session flash has been asked for, or the end of the walk
 * when every box was asked for and one is still flashing or failed.
 *
 * Null when there is nothing to resume: no walk began here, or every box
 * flashed. The second is Mission Control sending the operator back because a
 * board no longer carries its sketch; resuming would read "all flashed" and
 * send them straight back again, so they start from the review instead.
 */
export function resumeWalkAt(
  status: FlashQueueStatus | null,
  walkOrder: readonly number[],
): number | null {
  const { cards, allFlashed } = sessionFlashCards(status, walkOrder);
  const started = walkOrder.filter((box) => cards.get(box)!.state !== "idle");
  if (started.length === 0 || allFlashed) return null;
  const next = walkOrder.findIndex((box) => cards.get(box)!.state === "idle");
  return next === -1 ? walkOrder.length : next;
}
