/**
 * The Record step's rules (`RECORDING.md#record-step`), pure so they can be
 * tested: which rows the form holds for the mapped boxes, whether the setup is
 * ready, and the `intan.configure` it sends. `SessionRecording` gathers the
 * facts and renders the answers.
 */

import type { ProbeMap } from "./types";
import type { RecordingDefaults } from "./defaults";

/** A box's row in the form. `record: false` runs the box behavior-only. */
export interface BoxRow {
  box: number;
  animalName: string;
  record: boolean;
  port: string;
  firstChannel: number;
  lastChannel: number;
  probeMapPath: string | null;
  probeMap: ProbeMap | null;
  probeError: string | null;
}

/** A mapped box as the sidecar reports it; only what a row needs. */
export interface MappedBox {
  box: number;
  animalName: string;
}

/** A new row for a box, from what the last Record step remembered for it. */
function seedRow(box: MappedBox, defaults: RecordingDefaults): BoxRow {
  const memory = defaults.boxes[String(box.box)];
  return {
    box: box.box,
    animalName: box.animalName,
    record: memory?.record ?? true,
    port: memory?.port ?? "",
    firstChannel: memory?.firstChannel ?? 0,
    lastChannel: memory?.lastChannel ?? -1,
    probeMapPath: memory?.probeMapPath ?? null,
    probeMap: null,
    probeError: null,
  };
}

/**
 * The form's rows for the boxes mapped now, given the rows it already holds (a
 * restored draft, or what was typed).
 *
 * Keyed to the CURRENT boxes, never to the rows: a box still mapped keeps what
 * was typed for it, under the animal mapped there now; a box no longer mapped
 * is dropped; a newly mapped box is seeded from the remembered defaults. A
 * draft saved before Back to Boxes otherwise kept a moved animal's old box,
 * and `intan.configure` named a box with no animal on it (B5).
 *
 * The same array comes back when nothing changed, so a repeated answer from
 * the sidecar neither re-renders nor rewrites the draft. No boxes (not loaded
 * yet, or the rig not held) keeps the rows as they are.
 */
export function reconcileRows(
  boxes: readonly MappedBox[],
  defaults: RecordingDefaults,
  draftRows: BoxRow[],
): BoxRow[] {
  if (boxes.length === 0) return draftRows;
  const held = new Map(draftRows.map((r) => [r.box, r]));
  const next = boxes.map((b) => {
    const kept = held.get(b.box);
    if (!kept) return seedRow(b, defaults);
    return kept.animalName === b.animalName ? kept : { ...kept, animalName: b.animalName };
  });
  const unchanged = next.length === draftRows.length && next.every((r, i) => r === draftRows[i]);
  return unchanged ? draftRows : next;
}
