/**
 * Where a log note falls on one run's trial tape (`DATA.md#per-trial-tape`,
 * `DATA.md#the-session-clock`). Pure.
 *
 * The tape's axis is trial order, not time, so a note is placed **before the
 * first trial that opened at or after it**. Two clocks meet here and neither is
 * exact: the run's `startedAt` is stamped to the second before the board
 * handshake, and a trial's `atMs` counts from the file's first timestamp. The
 * placement is therefore good to a few seconds — a trial or two on a fast task
 * — and is drawn and labelled as approximate.
 *
 * A note only marks a run it could be about: a session note marks every run,
 * an animal or box note only that animal's or box's. And only while the run
 * was going — a box note from the afternoon group says nothing about the
 * morning animal that sat in the same box.
 */

import type { TrialRecord } from "../analytics/types";
import type { SessionNote } from "./types";

/** How far outside the run's span a note may fall and still be drawn, at the edge. */
export const EDGE_SLACK_MS = 60_000;

export interface TapeMarker {
  note: SessionNote;
  /** Position on the tape in trial units, 0 … trials.length. */
  position: number;
  /** Ms into this run, by the run's clock. */
  runOffsetMs: number;
}

export interface TapeRun {
  animalId: string;
  boxNumber: number | null;
  startedAt: string;
  endedAt: string | null;
}

export function appliesTo(note: SessionNote, run: TapeRun): boolean {
  switch (note.scope.kind) {
    case "animal":
      return note.scope.animalId === run.animalId;
    case "box":
      return run.boxNumber !== null && note.scope.box === run.boxNumber;
    default:
      return true;
  }
}

export function tapeMarkers(
  notes: readonly SessionNote[],
  run: TapeRun,
  trials: readonly TrialRecord[],
): TapeMarker[] {
  const start = Date.parse(run.startedAt);
  const timed = trials.filter((t): t is TrialRecord & { atMs: number } => t.atMs !== null);
  if (Number.isNaN(start) || timed.length === 0) return [];
  const lastAt = timed[timed.length - 1]!.atMs;
  const ended = run.endedAt ? Date.parse(run.endedAt) - start : lastAt;
  const span = Math.max(lastAt, Number.isNaN(ended) ? lastAt : ended);

  const markers: TapeMarker[] = [];
  for (const note of notes) {
    if (!appliesTo(note, run)) continue;
    const at = Date.parse(note.at);
    if (Number.isNaN(at)) continue;
    const offset = at - start;
    if (offset < -EDGE_SLACK_MS || offset > span + EDGE_SLACK_MS) continue;
    const next = timed.find((t) => t.atMs >= offset);
    markers.push({
      note,
      position: next ? next.index : trials.length,
      runOffsetMs: offset,
    });
  }
  return markers.sort((a, b) => a.position - b.position);
}
